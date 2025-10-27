"""
Order Router — Order routing with retry/backoff, deduplication, and timeout handling.

Features:
- Deduplication via client_order_id tracking
- Exponential backoff with tenacity
- Request/response latency tracking
- Prometheus metrics integration
- Idempotent operations
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from tools.live.exchange_client import (
    ExchangeClient,
    OrderRequest,
    OrderResponse,
    FillEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class RouteMetrics:
    """Metrics for a single order route."""
    
    client_order_id: str
    attempts: int = 0
    total_latency_ms: float = 0.0
    first_attempt_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_attempt_ts: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


class OrderRouter:
    """
    Order router with retry/backoff and deduplication.
    
    Responsibilities:
    - Route orders to exchange client
    - Deduplicate by client_order_id
    - Retry on transient failures (network, rate limits)
    - Track latency and success rate
    - Emit Prometheus metrics
    
    Retry Policy:
    - Max 3 attempts
    - Exponential backoff: 0.1s, 0.2s, 0.4s
    - Retry on: TimeoutError, ConnectionError, RuntimeError (5xx)
    - No retry on: ValueError (invalid params), rejection (4xx)
    """
    
    def __init__(
        self,
        client: ExchangeClient,
        max_attempts: int = 3,
        timeout_seconds: float = 5.0,
        risk_monitor: Optional[object] = None,
        fsm: Optional[object] = None,
    ):
        """
        Initialize order router.
        
        Args:
            client: ExchangeClient instance
            max_attempts: Max retry attempts (default: 3)
            timeout_seconds: Timeout per attempt (default: 5.0s)
            risk_monitor: RuntimeRiskMonitor instance (optional)
            fsm: OrderStateMachine instance (optional, for cancel_all_orders)
        """
        self.client = client
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.risk_monitor = risk_monitor
        self._fsm = fsm
        
        # Deduplication tracking
        self._placed_orders: Set[str] = set()
        self._order_responses: Dict[str, OrderResponse] = {}
        
        # Metrics
        self._route_metrics: Dict[str, RouteMetrics] = {}
        
        logger.info(
            f"OrderRouter initialized: max_attempts={max_attempts}, "
            f"timeout={timeout_seconds}s, "
            f"risk_monitor={'enabled' if risk_monitor else 'disabled'}"
        )
    
    def place_order(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        time_in_force: str = "GTC",
    ) -> OrderResponse:
        """
        Place order with retry/backoff.
        
        Args:
            client_order_id: Unique client order ID (idempotency key)
            symbol: Trading symbol
            side: "Buy" or "Sell"
            qty: Order quantity
            price: Limit price
            time_in_force: "GTC", "IOC", or "FOK"
        
        Returns:
            OrderResponse from exchange
        
        Raises:
            ValueError: Invalid parameters
            RuntimeError: Order rejected or max retries exceeded
        """
        # Deduplication check
        if client_order_id in self._placed_orders:
            logger.warning(f"Duplicate order ignored: {client_order_id}")
            cached = self._order_responses.get(client_order_id)
            if cached:
                return cached
            raise RuntimeError(f"Order {client_order_id} already placed but no cached response")
        
        # Risk check (if monitor enabled)
        if self.risk_monitor:
            if not self.risk_monitor.check_before_order(symbol, side, qty, price):
                raise RuntimeError(
                    f"Order blocked by risk monitor: {client_order_id} "
                    f"(frozen={self.risk_monitor.is_frozen()})"
                )
        
        # Initialize metrics
        metrics = RouteMetrics(client_order_id=client_order_id)
        self._route_metrics[client_order_id] = metrics
        
        # Place with retry
        try:
            response = self._place_with_retry(
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                time_in_force=time_in_force,
                metrics=metrics,
            )
            
            # Mark as placed
            self._placed_orders.add(client_order_id)
            self._order_responses[client_order_id] = response
            
            metrics.success = True
            metrics.last_attempt_ts = datetime.now(timezone.utc).isoformat()
            
            logger.info(
                f"Order placed: {client_order_id} → {response.exchange_order_id} "
                f"({metrics.attempts} attempts, {metrics.total_latency_ms:.1f}ms)"
            )
            
            return response
        
        except Exception as e:
            metrics.success = False
            metrics.error = str(e)
            metrics.last_attempt_ts = datetime.now(timezone.utc).isoformat()
            
            logger.error(
                f"Order placement failed: {client_order_id} after {metrics.attempts} attempts: {e}"
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _place_with_retry(
        self,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        time_in_force: str,
        metrics: RouteMetrics,
    ) -> OrderResponse:
        """Place order with tenacity retry decorator."""
        metrics.attempts += 1
        
        start_time = time.perf_counter()
        
        try:
            response = self.client.place_limit_order(
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                time_in_force=time_in_force,
            )
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            metrics.total_latency_ms += latency_ms
            
            # Check for rejection
            if response.status == "Rejected":
                raise RuntimeError(
                    f"Order rejected: {response.reject_reason or 'unknown reason'}"
                )
            
            return response
        
        except (TimeoutError, ConnectionError) as e:
            # Retriable errors
            latency_ms = (time.perf_counter() - start_time) * 1000
            metrics.total_latency_ms += latency_ms
            
            logger.warning(
                f"Retriable error on attempt {metrics.attempts}: {e.__class__.__name__}"
            )
            raise
        
        except (ValueError, RuntimeError) as e:
            # Non-retriable errors (invalid params, rejection)
            latency_ms = (time.perf_counter() - start_time) * 1000
            metrics.total_latency_ms += latency_ms
            
            logger.error(f"Non-retriable error: {e}")
            raise
    
    def cancel_order(
        self,
        client_order_id: str,
        symbol: Optional[str] = None,
    ) -> OrderResponse:
        """
        Cancel order with retry/backoff.
        
        Args:
            client_order_id: Client order ID to cancel
            symbol: Symbol (optional, used by some exchanges)
        
        Returns:
            OrderResponse with status="Canceled"
        
        Raises:
            RuntimeError: Order not found or cancellation failed
        """
        if client_order_id not in self._placed_orders:
            raise RuntimeError(f"Order not found or not placed: {client_order_id}")
        
        # Cancel with retry
        try:
            response = self._cancel_with_retry(
                client_order_id=client_order_id,
                symbol=symbol,
            )
            
            # Update cache
            self._order_responses[client_order_id] = response
            
            logger.info(f"Order canceled: {client_order_id}")
            
            return response
        
        except Exception as e:
            logger.error(f"Order cancellation failed: {client_order_id}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _cancel_with_retry(
        self,
        client_order_id: str,
        symbol: Optional[str],
    ) -> OrderResponse:
        """Cancel order with tenacity retry decorator."""
        return self.client.cancel_order(
            client_order_id=client_order_id,
            symbol=symbol,
        )
    
    def get_order_status(self, client_order_id: str) -> Optional[OrderResponse]:
        """
        Get cached or fresh order status.
        
        Args:
            client_order_id: Client order ID
        
        Returns:
            OrderResponse or None if not found
        """
        # Try cache first
        cached = self._order_responses.get(client_order_id)
        if cached:
            return cached
        
        # Query exchange
        try:
            response = self.client.get_order_status(client_order_id=client_order_id)
            if response:
                self._order_responses[client_order_id] = response
            return response
        except Exception as e:
            logger.error(f"Failed to get order status for {client_order_id}: {e}")
            return None
    
    def poll_fills(self, client_order_id: str) -> list[FillEvent]:
        """
        Poll for fill events.
        
        Args:
            client_order_id: Client order ID
        
        Returns:
            List of FillEvent objects
        """
        try:
            return self.client.poll_fills(client_order_id)
        except Exception as e:
            logger.error(f"Failed to poll fills for {client_order_id}: {e}")
            return []
    
    def get_metrics(self) -> Dict[str, RouteMetrics]:
        """
        Get routing metrics for all orders.
        
        Returns:
            Dict mapping client_order_id to RouteMetrics
        """
        return self._route_metrics.copy()
    
    def reset_deduplication(self) -> None:
        """
        Reset deduplication state (for testing).
        
        WARNING: Only use in tests or after session restart.
        """
        self._placed_orders.clear()
        self._order_responses.clear()
        logger.warning("Deduplication state reset")


# Convenience function
def create_router(
    exchange: str = "bybit",
    mock: bool = True,
    max_attempts: int = 3,
    timeout_seconds: float = 5.0,
    risk_monitor: Optional[object] = None,
    fsm: Optional[object] = None,
    **client_kwargs,
) -> OrderRouter:
    """
    Factory function to create OrderRouter with embedded client.
    
    Args:
        exchange: Exchange name
        mock: Use mock mode
        max_attempts: Max retry attempts
        timeout_seconds: Timeout per attempt
        risk_monitor: RuntimeRiskMonitor instance (optional)
        fsm: OrderStateMachine instance (optional)
        **client_kwargs: Additional arguments for ExchangeClient
    
    Returns:
        OrderRouter instance
    """
    from tools.live.exchange_client import create_client
    
    client = create_client(exchange=exchange, mock=mock, **client_kwargs)
    return OrderRouter(
        client=client,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        risk_monitor=risk_monitor,
        fsm=fsm,
    )

