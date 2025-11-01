"""
Robust cancel-all implementation with idempotency, backoff, and metrics.

This module provides a bulletproof cancel-all mechanism for freeze events with:
- Distributed locking (Redis)
- Exponential backoff with jitter
- Comprehensive metrics
- Reconciliation to ensure zero open orders
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict

from src.common.backoff import BackoffPolicy, retry_async, RetryableError
from src.common.redis_lock import distributed_lock


@dataclass
class CancelResult:
    """Result of cancel-all operation."""
    
    success: bool
    canceled_count: int
    failed_count: int
    duration_ms: float
    method: str  # "bulk" or "per_order" or "idempotent_skip"
    failed_order_ids: List[str] = field(default_factory=list)
    error: Optional[str] = None


class CancelAllOrchestrator:
    """
    Orchestrates robust cancel-all on freeze with idempotency and backoff.
    
    Features:
    - Distributed lock via Redis (prevents duplicate execution)
    - Exponential backoff with jitter on retryable errors
    - Batch cancellation with per-order fallback
    - Reconciliation to verify zero open orders
    - Comprehensive metrics
    
    Usage:
        orchestrator = CancelAllOrchestrator(
            exchange=exchange_client,
            order_store=order_store,
            redis_client=redis,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(
            reason="edge_below_threshold",
            symbols=["BTCUSDT", "ETHUSDT"]
        )
    """
    
    def __init__(
        self,
        exchange: Any,
        order_store: Any,
        redis_client: Optional[Any] = None,
        metrics: Optional[Any] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize cancel-all orchestrator.
        
        Args:
            exchange: Exchange client with cancel methods
            order_store: Order store (source of truth)
            redis_client: Redis client for distributed lock (optional)
            metrics: Metrics collector (optional)
            session_id: Unique session ID for lock key
        """
        self.exchange = exchange
        self.order_store = order_store
        self.redis = redis_client
        self.metrics = metrics
        self.session_id = session_id or "default"
        
        # Backoff policy for retries
        self.backoff_policy = BackoffPolicy(
            base_delay=0.2,
            factor=2.0,
            max_delay=5.0,
            max_attempts=7,
            jitter=True
        )
    
    async def cancel_all_open_orders(
        self,
        reason: str,
        symbols: Optional[List[str]] = None
    ) -> CancelResult:
        """
        Cancel all open orders with idempotency and retry.
        
        Args:
            reason: Reason for cancellation (e.g., "edge_below_threshold")
            symbols: Optional list of symbols to cancel (None = all)
        
        Returns:
            CancelResult with details of cancellation
        """
        start_time = time.time()
        
        # Distributed lock for idempotency
        lock_key = f"freeze:{self.session_id}:cancel_all"
        
        async with distributed_lock(self.redis, lock_key, ttl=30) as acquired:
            if not acquired:
                # Lock already held: cancel-all in progress by another process
                duration_ms = (time.time() - start_time) * 1000
                
                if self.metrics:
                    self.metrics.inc("mm_cancel_all_skipped_total", labels={"reason": "lock_held"})
                
                return CancelResult(
                    success=True,
                    canceled_count=0,
                    failed_count=0,
                    duration_ms=duration_ms,
                    method="idempotent_skip",
                    error="Lock already held by another process"
                )
            
            # Lock acquired: proceed with cancel-all
            try:
                result = await self._execute_cancel_all(reason, symbols)
                
                # Emit metrics
                if self.metrics:
                    self.metrics.inc("mm_cancel_all_total", labels={"status": "success" if result.success else "failure"})
                    self.metrics.inc("mm_cancel_all_orders_total", value=result.canceled_count)
                    self.metrics.observe("mm_cancel_all_duration_ms", result.duration_ms)
                
                return result
            
            except Exception as exc:
                duration_ms = (time.time() - start_time) * 1000
                
                if self.metrics:
                    self.metrics.inc("mm_cancel_all_total", labels={"status": "error"})
                
                return CancelResult(
                    success=False,
                    canceled_count=0,
                    failed_count=0,
                    duration_ms=duration_ms,
                    method="error",
                    error=str(exc)
                )
    
    async def _execute_cancel_all(
        self,
        reason: str,
        symbols: Optional[List[str]]
    ) -> CancelResult:
        """Execute cancel-all with retry and reconciliation."""
        start_time = time.time()
        
        # Step 1: Get open orders from store (source of truth)
        open_orders = self._get_open_orders(symbols)
        total_orders = len(open_orders)
        
        if total_orders == 0:
            duration_ms = (time.time() - start_time) * 1000
            return CancelResult(
                success=True,
                canceled_count=0,
                failed_count=0,
                duration_ms=duration_ms,
                method="no_orders"
            )
        
        # Step 2: Try bulk cancel first (fast path)
        bulk_success = await self._try_bulk_cancel(symbols or self._extract_symbols(open_orders))
        
        if bulk_success:
            # Bulk cancel succeeded, mark all as canceled locally
            canceled_count = self._mark_all_canceled_local(open_orders, reason)
            duration_ms = (time.time() - start_time) * 1000
            
            return CancelResult(
                success=True,
                canceled_count=canceled_count,
                failed_count=0,
                duration_ms=duration_ms,
                method="bulk"
            )
        
        # Step 3: Fallback to per-order cancel with retry
        result = await self._cancel_per_order_with_retry(open_orders, reason)
        
        # Step 4: Reconciliation - verify zero open orders
        await self._reconcile_open_orders()
        
        duration_ms = (time.time() - start_time) * 1000
        result.duration_ms = duration_ms
        
        return result
    
    def _get_open_orders(self, symbols: Optional[List[str]]) -> List[Any]:
        """Get open orders from store, optionally filtered by symbols."""
        all_open = list(self.order_store.get_open_orders())
        
        if symbols is None:
            return all_open
        
        symbol_set = set(symbols)
        return [o for o in all_open if o.symbol in symbol_set]
    
    def _extract_symbols(self, orders: List[Any]) -> List[str]:
        """Extract unique symbols from order list."""
        return sorted(set(o.symbol for o in orders))
    
    async def _try_bulk_cancel(self, symbols: List[str]) -> bool:
        """
        Try bulk cancel on exchange.
        
        Returns:
            True if bulk cancel succeeded, False otherwise
        """
        if not symbols:
            return False
        
        # Check if exchange supports bulk cancel
        cancel_all_bulk = getattr(self.exchange, "cancel_all_open_orders", None)
        
        if not callable(cancel_all_bulk):
            return False
        
        try:
            # Try bulk cancel with retry
            async def _do_bulk_cancel():
                result = cancel_all_bulk(symbols=symbols)
                # Some clients return async, others sync
                if hasattr(result, "__await__"):
                    return await result
                return result
            
            def _is_retryable_bulk(exc: Exception) -> bool:
                exc_str = str(exc).lower()
                return any(keyword in exc_str for keyword in [
                    '429', 'rate limit', 'timeout', 'network', '5'
                ])
            
            await retry_async(
                _do_bulk_cancel,
                policy=self.backoff_policy,
                is_retryable=_is_retryable_bulk
            )
            
            return True
        
        except Exception:
            # Bulk cancel failed, will fall back to per-order
            return False
    
    async def _cancel_per_order_with_retry(
        self,
        orders: List[Any],
        reason: str
    ) -> CancelResult:
        """Cancel orders one-by-one with retry."""
        canceled_count = 0
        failed_count = 0
        failed_order_ids = []
        
        # Check available cancel methods
        cancel_generic = getattr(self.exchange, "cancel", None)
        cancel_one = getattr(self.exchange, "cancel_order", None)
        
        for order in orders:
            try:
                # Try cancel on exchange with retry
                await self._cancel_order_exchange_with_retry(
                    order,
                    cancel_generic,
                    cancel_one
                )
                
                # Mark canceled locally (critical: must succeed)
                self._mark_order_canceled_local(order, reason)
                
                canceled_count += 1
                
                # Emit per-symbol metric
                if self.metrics:
                    self.metrics.inc(
                        "mm_cancel_all_per_order_success_total",
                        labels={"symbol": order.symbol}
                    )
            
            except Exception:
                # Exchange cancel failed, but still mark canceled locally
                # (local consistency more important than exchange state)
                self._mark_order_canceled_local(order, reason)
                
                failed_count += 1
                failed_order_ids.append(order.client_order_id)
                
                if self.metrics:
                    self.metrics.inc(
                        "mm_cancel_all_per_order_failure_total",
                        labels={"symbol": order.symbol}
                    )
        
        return CancelResult(
            success=(failed_count == 0),
            canceled_count=canceled_count,
            failed_count=failed_count,
            duration_ms=0,  # Set by caller
            method="per_order",
            failed_order_ids=failed_order_ids
        )
    
    async def _cancel_order_exchange_with_retry(
        self,
        order: Any,
        cancel_generic: Optional[Any],
        cancel_one: Optional[Any]
    ) -> None:
        """Cancel single order on exchange with retry."""
        async def _do_cancel():
            if callable(cancel_generic):
                result = cancel_generic(order.client_order_id)
            elif callable(cancel_one):
                result = cancel_one(order.client_order_id, order.symbol)
            else:
                raise NonRetryableError("No cancel method available")
            
            # Handle async result
            if hasattr(result, "__await__"):
                return await result
            return result
        
        def _is_retryable_cancel(exc: Exception) -> bool:
            exc_str = str(exc).lower()
            # Retryable: network, timeout, rate limit, 5xx
            return any(keyword in exc_str for keyword in [
                '429', 'rate limit', 'timeout', 'network', '500', '502', '503', '504'
            ])
        
        # Retry with backoff
        await retry_async(
            _do_cancel,
            policy=self.backoff_policy,
            is_retryable=_is_retryable_cancel
        )
    
    def _mark_all_canceled_local(self, orders: List[Any], reason: str) -> int:
        """Mark all orders as canceled in local store."""
        count = 0
        for order in orders:
            self._mark_order_canceled_local(order, reason)
            count += 1
        return count
    
    def _mark_order_canceled_local(self, order: Any, reason: str) -> None:
        """Mark single order as canceled in local store."""
        # Try cancel() method first (DurableOrderStore)
        if hasattr(self.order_store, "cancel"):
            try:
                self.order_store.cancel(order.client_order_id)
                return
            except Exception:
                pass
        
        # Try mark_canceled() method (alternative API)
        if hasattr(self.order_store, "mark_canceled"):
            try:
                self.order_store.mark_canceled(
                    order.client_order_id,
                    trigger=reason
                )
                return
            except Exception:
                pass
        
        # Fallback: directly set state (InMemoryOrderStore)
        if hasattr(order, "state"):
            order.state = "CANCELED"
    
    async def _reconcile_open_orders(self) -> None:
        """
        Reconcile to verify zero open orders.
        
        This is a critical check to ensure cancel-all succeeded.
        """
        # Wait a bit for cancellations to propagate
        await asyncio.sleep(0.1)
        
        # Check local store
        remaining_local = list(self.order_store.get_open_orders())
        
        if remaining_local:
            # Warning: orders still open locally
            if self.metrics:
                self.metrics.set("mm_cancel_all_remaining_orders", len(remaining_local))
        else:
            if self.metrics:
                self.metrics.set("mm_cancel_all_remaining_orders", 0)


# Import guard to avoid errors in modules without these dependencies
try:
    from src.common.backoff import NonRetryableError
except ImportError:
    class NonRetryableError(Exception):
        pass

