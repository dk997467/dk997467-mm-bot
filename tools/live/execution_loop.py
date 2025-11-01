"""
Execution Loop for Shadow Trading with Risk Integration.

Pure stdlib implementation with deterministic behavior.
Supports both InMemoryOrderStore and DurableOrderStore with idempotency.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from tools.live.exchange import (
    FakeExchangeClient,
    IExchangeClient,
    PlaceOrderRequest,
    Side,
    OrderStatus,
)
from tools.live.order_store import InMemoryOrderStore, OrderState
from tools.live.risk_monitor import RuntimeRiskMonitor
from tools.live import maker_policy
from tools.live import metrics as live_metrics
from tools.obs import jsonlog
from tools.obs import metrics

# P0.10: Testnet Soak & Canary imports
from tools.live import fees as fees_module
from tools.live import kill_switch
from tools.live import recon as recon_module
from tools.live import symbol_filters

logger = logging.getLogger(__name__)
# Structured logger for observability
_structured_logger = jsonlog.get_logger("mm.execution", default_ctx={"component": "execution_loop"})


class IOrderStore(Protocol):
    """Protocol for order stores (in-memory or durable)."""
    
    def generate_client_order_id(self) -> str:
        """Generate client order ID."""
        ...
    
    def get_open_orders(self) -> list[Any]:
        """Get open orders."""
        ...


@dataclass
class Quote:
    """Market quote."""
    symbol: str
    bid: float
    ask: float
    timestamp_ms: int = 0
    # Back-compat aliases used by integration tests:
    timestamp: int | None = None
    bid_qty: float | None = None
    ask_qty: float | None = None
    
    def __post_init__(self):
        """Map 'timestamp' → 'timestamp_ms' if provided."""
        if self.timestamp_ms == 0 and self.timestamp is not None:
            self.timestamp_ms = int(self.timestamp)


@dataclass
class ExecutionParams:
    """Parameters for execution loop."""
    symbols: list[str]
    iterations: int
    max_inventory_usd_per_symbol: float
    max_total_notional_usd: float
    edge_freeze_threshold_bps: float
    base_qty: float = 0.01  # Base order quantity
    spread_bps: float = 5.0  # Spread in basis points


class ExecutionLoop:
    """
    Execution loop for shadow trading.
    
    Integrates:
    - Exchange client (fake or real)
    - Order store (in-memory or durable)
    - Runtime risk monitor
    - Position tracking
    - Idempotent operations with DurableOrderStore
    - Recovery from restart
    """

    def __init__(
        self,
        exchange: IExchangeClient,
        order_store: InMemoryOrderStore | Any,  # InMemoryOrderStore or DurableOrderStore
        risk_monitor: RuntimeRiskMonitor,
        clock: Callable[[], int] | None = None,
        enable_idempotency: bool = False,
        network_enabled: bool = False,
        testnet: bool = False,
        maker_only: bool = True,
        post_only_offset_bps: float = 1.5,
        min_qty_pad: float = 1.1,
        recon_interval_s: int = 60,
        fee_schedule: fees_module.FeeSchedule | None = None,
    ):
        self.exchange = exchange
        self.order_store = order_store
        self.risk_monitor = risk_monitor
        self._clock = clock or self._default_clock
        self.enable_idempotency = enable_idempotency
        
        # P0.3 Live-prep parameters
        self.network_enabled = network_enabled
        self.testnet = testnet
        self.maker_only = maker_only
        self.post_only_offset_bps = post_only_offset_bps
        self.min_qty_pad = min_qty_pad
        
        # P0.10: Recon & fees parameters
        self.recon_interval_s = recon_interval_s
        self.fee_schedule = fee_schedule
        self._last_recon_ms = 0
        self._last_recon_report: recon_module.ReconReport | None = None
        
        # P0.10: Kill-switch for live mode
        kill_switch.confirm_live_enable(
            network_enabled=network_enabled,
            testnet=testnet,
        )
        
        # P0.10: Symbol filters cache
        self._symbol_filters_cache = symbol_filters.SymbolFiltersCache(
            clock=self._clock,
            ttl_s=600,  # 10 minutes TTL
        )

        # Statistics
        self.stats = {
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
            "orders_canceled": 0,
            "risk_blocks": 0,
            "freeze_events": 0,
            "recoveries": 0,
            "duplicate_operations": 0,
            "orders_blocked": 0,
            "recon_runs": 0,
        }
        
        # Idempotency tracking
        self._freeze_idem_key: str | None = None
        
        # Freeze state tracking (for metrics)
        self._was_frozen = False
        
        # Set maker-only gauge
        metrics.MAKER_ONLY_ENABLED.set(1.0 if maker_only else 0.0)

    def _default_clock(self) -> int:
        """Default clock (respects MM_FREEZE_UTC_ISO)."""
        freeze_iso = os.getenv("MM_FREEZE_UTC_ISO")
        if freeze_iso:
            dt = datetime.fromisoformat(freeze_iso.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        return int(time.time() * 1000)

    def on_quote(self, quote: Quote, params: ExecutionParams) -> None:
        """
        Handle market quote and attempt to place orders.
        
        Workflow:
        1. Check if frozen
        2. Generate order parameters
        3. Check risk limits
        4. Place order if approved
        """
        if self.risk_monitor.is_frozen():
            logger.info(f"Skipping {quote.symbol}: system frozen")
            return

        # Generate bid/ask orders
        mid = (quote.bid + quote.ask) / 2.0
        spread = mid * params.spread_bps / 10000.0

        buy_price = mid - spread / 2
        sell_price = mid + spread / 2

        # Try to place buy order
        if self.risk_monitor.check_before_order(
            symbol=quote.symbol,
            side="Buy",
            qty=params.base_qty,
            price=buy_price,
        ):
            self._place_order(
                quote.symbol,
                Side.BUY,
                params.base_qty,
                buy_price,
                best_bid=quote.bid,
                best_ask=quote.ask,
            )
        else:
            self.stats["risk_blocks"] += 1
            logger.debug(f"Risk blocked: {quote.symbol} Buy")
            # Log risk block
            _structured_logger.warn(
                "order_blocked",
                symbol=quote.symbol,
                side="Buy",
                qty=params.base_qty,
                price=buy_price,
                reason="risk_limit",
            )
            metrics.ORDERS_BLOCKED.inc(symbol=quote.symbol, reason="risk_limit")

        # Try to place sell order
        if self.risk_monitor.check_before_order(
            symbol=quote.symbol,
            side="Sell",
            qty=params.base_qty,
            price=sell_price,
        ):
            self._place_order(
                quote.symbol,
                Side.SELL,
                params.base_qty,
                sell_price,
                best_bid=quote.bid,
                best_ask=quote.ask,
            )
        else:
            self.stats["risk_blocks"] += 1
            logger.debug(f"Risk blocked: {quote.symbol} Sell")
            # Log risk block
            _structured_logger.warn(
                "order_blocked",
                symbol=quote.symbol,
                side="Sell",
                qty=params.base_qty,
                price=sell_price,
                reason="risk_limit",
            )
            metrics.ORDERS_BLOCKED.inc(symbol=quote.symbol, reason="risk_limit")

    def _place_order(
        self,
        symbol: str,
        side: Side,
        qty: float,
        price: float,
        best_bid: float | None = None,
        best_ask: float | None = None,
    ) -> None:
        """
        Place an order via exchange (with optional idempotency and maker-only checks).
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY or SELL)
            qty: Order quantity
            price: Order price
            best_bid: Current best bid (for maker-only checks)
            best_ask: Current best ask (for maker-only checks)
        """
        # Generate client order ID
        client_order_id = self.order_store.generate_client_order_id()
        timestamp_ms = self._clock()
        
        # P0.3: Apply maker-only policy if enabled
        if self.maker_only:
            # Get symbol filters
            filters = {"tickSize": 0.01, "stepSize": 0.001, "minQty": 0.001}
            if hasattr(self.exchange, "get_symbol_filters"):
                filters = self.exchange.get_symbol_filters(symbol)
            
            tick_size = filters["tickSize"]
            step_size = filters["stepSize"]
            min_qty = filters["minQty"]
            
            # 1. Round quantity to step_size
            rounded_qty = float(maker_policy.round_qty(qty, step_size))
            
            # 2. Check minQty with padding
            min_qty_required = min_qty * self.min_qty_pad
            if not maker_policy.check_min_qty(rounded_qty, min_qty_required):
                # Block order: quantity too small
                self.stats["orders_blocked"] += 1
                _structured_logger.warn(
                    "order_blocked",
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side.value,
                    qty=rounded_qty,
                    min_qty_required=min_qty_required,
                    reason="min_qty",
                )
                metrics.ORDERS_BLOCKED.inc(symbol=symbol, reason="min_qty")
                return
            
            # 3. Calculate post-only price (if we have market data)
            if best_bid is not None and best_ask is not None:
                # Determine reference price based on side
                ref_price = best_bid if side == Side.BUY else best_ask
                
                # Calculate post-only price with offset
                adjusted_price = float(
                    maker_policy.calc_post_only_price(
                        side=side.value,
                        ref_price=ref_price,
                        offset_bps=self.post_only_offset_bps,
                        tick_size=tick_size,
                    )
                )
                
                # Check if adjusted price still crosses market
                if maker_policy.check_price_crosses_market(
                    side=side.value,
                    price=adjusted_price,
                    best_bid=best_bid,
                    best_ask=best_ask,
                ):
                    # Block order: price would cross market even after adjustment
                    self.stats["orders_blocked"] += 1
                    _structured_logger.warn(
                        "order_blocked",
                        client_order_id=client_order_id,
                        symbol=symbol,
                        side=side.value,
                        original_price=price,
                        adjusted_price=adjusted_price,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        reason="cross_price",
                    )
                    metrics.ORDERS_BLOCKED.inc(symbol=symbol, reason="cross_price")
                    return
                
                # Use adjusted price and log adjustment
                if abs(adjusted_price - price) > 1e-8:
                    metrics.POST_ONLY_ADJUSTMENTS.inc(symbol=symbol, side=side.value)
                    logger.debug(
                        f"Post-only adjustment: {symbol} {side.value} "
                        f"{price:.2f} -> {adjusted_price:.2f}"
                    )
                
                price = adjusted_price
            
            # Use rounded quantity
            qty = rounded_qty
        
        # Check if using DurableOrderStore with idempotency
        if self.enable_idempotency and hasattr(self.order_store, "place_order"):
            # Use idempotent place_order
            idem_key = f"place:{client_order_id}:{symbol}:v1"
            result = self.order_store.place_order(
                symbol=symbol,
                side=side.value,
                qty=qty,
                price=price,
                timestamp_ms=timestamp_ms,
                idem_key=idem_key,
            )
            
            if result.was_duplicate:
                self.stats["duplicate_operations"] += 1
                logger.debug(f"Duplicate place detected: {idem_key}")
                return
            
            if not result.success:
                self.stats["orders_rejected"] += 1
                logger.warning(f"Failed to place: {result.message}")
                return
        
        # Submit to exchange
        req = PlaceOrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
        )

        try:
            place_start_ms = self._clock()
            # Note: method name varies by exchange client (place_limit vs place_limit_order)
            if hasattr(self.exchange, "place_limit_order"):
                resp = self.exchange.place_limit_order(req)
            elif hasattr(self.exchange, "place_limit"):
                resp = self.exchange.place_limit(req)
            else:
                raise AttributeError(f"Exchange client {type(self.exchange)} has no place order method")
            latency_ms = self._clock() - place_start_ms

            if resp.status == OrderStatus.OPEN:
                self.stats["orders_placed"] += 1
                logger.info(f"Placed: {client_order_id} {symbol} {side.value} {qty}@{price}")
                
                # Observability: structured log + metrics
                _structured_logger.info(
                    "order_placed",
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side.value,
                    qty=qty,
                    price=price,
                    latency_ms=latency_ms,
                )
                metrics.ORDERS_PLACED.inc(symbol=symbol)
                metrics.ORDER_LATENCY.observe(latency_ms, symbol=symbol)
                
                # Create order in store if using InMemoryOrderStore
                if not self.enable_idempotency and hasattr(self.order_store, "_orders"):
                    # InMemoryOrderStore path: create order entry directly
                    from tools.live.order_store import Order
                    order = Order(
                        client_order_id=client_order_id,
                        symbol=symbol,
                        side=side.value,
                        qty=qty,
                        price=price,
                        state=OrderState.OPEN,
                        created_at_ms=timestamp_ms,
                        updated_at_ms=self._clock(),
                        order_id=getattr(resp, "order_id", None),
                    )
                    self.order_store._orders[client_order_id] = order
                
                # Update state if using durable store
                if self.enable_idempotency and hasattr(self.order_store, "update_order_state"):
                    idem_key = f"state:{client_order_id}:open:v1"
                    self.order_store.update_order_state(
                        client_order_id=client_order_id,
                        state=OrderState.OPEN,
                        timestamp_ms=self._clock(),
                        idem_key=idem_key,
                        order_id=resp.order_id,
                    )
            else:
                self.stats["orders_rejected"] += 1
                logger.warning(f"Rejected: {client_order_id} {resp.message}")
                
                # Observability: log rejection
                _structured_logger.warn(
                    "order_rejected",
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side.value,
                    reason=resp.message,
                )
                metrics.ORDERS_REJECTED.inc(symbol=symbol)
                
                # Create rejected order in store if using InMemoryOrderStore
                if not self.enable_idempotency and hasattr(self.order_store, "_orders"):
                    from tools.live.order_store import Order
                    order = Order(
                        client_order_id=client_order_id,
                        symbol=symbol,
                        side=side.value,
                        qty=qty,
                        price=price,
                        state=OrderState.REJECTED,
                        created_at_ms=timestamp_ms,
                        updated_at_ms=self._clock(),
                        message=resp.message,
                    )
                    self.order_store._orders[client_order_id] = order

        except Exception as e:
            self.stats["orders_rejected"] += 1
            logger.error(f"Error placing order: {e}")
            
            # Observability: log error
            _structured_logger.error(
                "order_placement_error",
                client_order_id=client_order_id,
                symbol=symbol,
                error=str(e),
            )
            metrics.ORDERS_REJECTED.inc(symbol=symbol)

    def on_fill(self) -> None:
        """Process fill events from exchange."""
        # Get fills source - can be callable or iterator/list
        fills_source = getattr(self.exchange, "stream_fills", None)
        if fills_source is None:
            return
        
        # Support callable and already-iterable
        fills = fills_source() if callable(fills_source) else fills_source
        if fills is None:
            return
        
        try:
            for fill in fills:
                # Notify risk monitor
                self.risk_monitor.on_fill(
                    symbol=fill.symbol,
                    side=fill.side,
                    qty=fill.qty,
                    price=fill.price,
                )

                self.stats["orders_filled"] += 1
                logger.info(f"Fill: {fill.order_id} {fill.qty}@{fill.price}")
                
                # Observability: log fill
                _structured_logger.info(
                    "order_filled",
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    qty=fill.qty,
                    price=fill.price,
                )
                metrics.ORDERS_FILLED.inc(symbol=fill.symbol)
        except TypeError:
            # If non-iterable object passed, ignore silently for stability
            return

    def on_edge_update(self, symbol: str, net_bps: float) -> None:
        """Update edge and check for freeze."""
        was_frozen = self.risk_monitor.is_frozen()
        
        self.risk_monitor.on_edge_update(symbol=symbol, net_bps=net_bps)
        
        # Update edge gauge
        metrics.EDGE_BPS.set(net_bps, symbol=symbol)
        
        if not was_frozen and self.risk_monitor.is_frozen():
            self.stats["freeze_events"] += 1
            logger.warning(f"System FROZEN: edge={net_bps}bps < threshold")
            
            # Observability: log freeze
            _structured_logger.warning(
                "freeze_triggered",
                symbol=symbol,
                edge_bps=net_bps,
                threshold_bps=self.risk_monitor.edge_freeze_threshold_bps,
                reason="edge_below_threshold",
            )
            
            # Increment freeze events metric exactly once per transition to frozen
            if not self._was_frozen:
                self._was_frozen = True
                metrics.inc_freeze_event()
            
            self._cancel_all_open_orders(reason="edge_below_threshold")

    def _cancel_all_open_orders(self, reason: str = "freeze") -> None:
        """Cancel all open orders (triggered by freeze) - idempotent."""
        # Generate idempotency key for this freeze event
        if not self._freeze_idem_key:
            freeze_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            self._freeze_idem_key = f"cancel_all:freeze_{freeze_ts}"
        
        # If using DurableOrderStore with idempotency
        if self.enable_idempotency and hasattr(self.order_store, "cancel_all_open"):
            result = self.order_store.cancel_all_open(
                timestamp_ms=int(self._clock() * 1000),
                idem_key=self._freeze_idem_key,
            )
            
            if result.was_duplicate:
                self.stats["duplicate_operations"] += 1
                logger.info(f"Freeze cancel_all was duplicate: {self._freeze_idem_key}")
                return
            
            if result.success:
                # Extract canceled count from message
                canceled_count = 0
                if "Canceled" in result.message and "orders" in result.message:
                    try:
                        parts = result.message.split()
                        canceled_count = int(parts[1])
                    except (IndexError, ValueError):
                        pass
                self.stats["orders_canceled"] += canceled_count
                logger.info(f"Idempotent cancel_all: {result.message}")
                
                # Observability: log cancel_all completion
                _structured_logger.info(
                    "cancel_all_done",
                    canceled_count=canceled_count,
                    idem_key=self._freeze_idem_key,
                    trigger=reason,
                )
            return
        
        # Fallback: non-idempotent cancel
        # Get open orders from order_store (source of truth for local state)
        open_orders = list(self.order_store.get_open_orders())
        
        canceled = 0
        
        # Best-effort: попробовать отменить на бирже
        # Try generic cancel() first (works for FakeExchangeClient and BybitRestClient)
        cancel_generic = getattr(self.exchange, "cancel", None)
        cancel_one = getattr(self.exchange, "cancel_order", None)
        cancel_all_bulk = getattr(self.exchange, "cancel_all_open_orders", None)
        
        try:
            if callable(cancel_all_bulk):
                # Если есть пакетная отмена — используем
                symbols = sorted({o.symbol for o in open_orders})
                if symbols:
                    cancel_all_bulk(symbols=symbols)
                    logger.info(f"Bulk cancel on exchange for symbols: {symbols}")
            elif callable(cancel_generic):
                # Generic cancel(client_order_id) - works for most exchanges
                for o in open_orders:
                    try:
                        cancel_generic(o.client_order_id)
                    except Exception as e:
                        # ignore exchange cancel errors — локальная консистентность важнее
                        logger.debug(f"Exchange cancel failed for {o.client_order_id}: {e}")
            elif callable(cancel_one):
                for o in open_orders:
                    try:
                        # cancel_order signature: (client_order_id, symbol)
                        cancel_one(o.client_order_id, o.symbol)
                    except Exception as e:
                        # ignore exchange cancel errors — локальная консистентность важнее
                        logger.debug(f"Exchange cancel failed for {o.client_order_id}: {e}")
        except Exception as e:
            # ignore exchange errors entirely
            logger.debug(f"Exchange cancel_all failed: {e}")
        
        # Локальная отмена — обязательна
        for o in open_orders:
            did_cancel = False
            
            # Try cancel() first (changes state to CANCELED, order remains in store)
            if hasattr(self.order_store, "cancel"):
                try:
                    self.order_store.cancel(o.client_order_id)
                    did_cancel = True
                except Exception as e:
                    logger.debug(f"Failed to cancel {o.client_order_id}: {e}")
            
            # If cancel failed, try remove() (physically removes order)
            if not did_cancel and hasattr(self.order_store, "remove"):
                try:
                    self.order_store.remove(o.client_order_id)
                    did_cancel = True
                except Exception as e:
                    logger.debug(f"Failed to remove {o.client_order_id}: {e}")
            
            if did_cancel:
                canceled += 1
        
        self.stats["orders_canceled"] = self.stats.get("orders_canceled", 0) + canceled
        
        logger.info(f"cancel_all_done: trigger={reason}, canceled={canceled}")
        
        # Observability: log cancel_all completion (fallback path)
        _structured_logger.info(
            "cancel_all_done",
            canceled_count=canceled,
            trigger=reason,
            mode="fallback",
        )

    def _run_recon_if_due(self, symbols: list[str]) -> None:
        """
        Run reconciliation if interval has passed.
        
        Args:
            symbols: List of symbols to reconcile
        """
        now_ms = self._clock()
        interval_ms = self.recon_interval_s * 1000
        
        if now_ms - self._last_recon_ms >= interval_ms:
            try:
                report = recon_module.reconcile_orders_fills_positions(
                    exchange=self.exchange,
                    store=self.order_store,
                    clock=self._clock,
                    symbols=symbols,
                    fee_schedule=self.fee_schedule,
                )
                self._last_recon_report = report
                self._last_recon_ms = now_ms
                self.stats["recon_runs"] += 1
                
                logger.debug(f"Recon complete: {report.divergence_count} divergences")
                
                # Log compact JSON
                _structured_logger.info(
                    "recon_complete",
                    divergence_count=report.divergence_count,
                    orders_local_only=len(report.orders_local_only),
                    orders_remote_only=len(report.orders_remote_only),
                    position_deltas=len(report.position_deltas),
                )
            except Exception as e:
                logger.warning(f"Recon failed: {e}")
    
    def run_shadow(self, params: ExecutionParams) -> dict[str, Any]:
        """
        Run shadow trading simulation.
        
        Returns deterministic JSON report.
        """
        logger.info(f"Starting shadow run: {params.iterations} iterations")

        for iteration in range(params.iterations):
            # Generate synthetic quotes
            for symbol in params.symbols:
                base_price = 50000.0 if "BTC" in symbol else 3000.0
                # Add some deterministic variation
                variation = (iteration % 10) * 0.001
                mid_price = base_price * (1.0 + variation)

                quote = Quote(
                    symbol=symbol,
                    bid=mid_price * 0.9995,
                    ask=mid_price * 1.0005,
                    timestamp_ms=self._clock() + iteration * 1000,
                )

                self.on_quote(quote, params)

            # Process fills
            self.on_fill()

            # Simulate edge update (decrease over time)
            for symbol in params.symbols:
                edge_bps = 10.0 - (iteration / params.iterations) * 8.0
                self.on_edge_update(symbol, edge_bps)
            
            # P0.10: Run periodic reconciliation
            self._run_recon_if_due(params.symbols)

        # P0.10: Final recon before generating report
        self._run_recon_if_due(params.symbols)
        
        # Generate final report
        return self._generate_report(params)

    def _generate_report(self, params: ExecutionParams) -> dict[str, Any]:
        """Generate deterministic JSON report with canonical structure."""
        import time
        
        positions = self.risk_monitor.get_positions()
        
        # Calculate net position value
        net_pos_usd = {}
        total_notional = 0.0
        for symbol, qty in positions.items():
            mark_price = self.risk_monitor.get_mark_price(symbol)
            notional = abs(qty * mark_price)
            net_pos_usd[symbol] = notional
            total_notional += notional
        
        # Calculate pass/fail status
        failed_count = (
            self.stats["orders_rejected"] + 
            self.stats["risk_blocks"] + 
            self.stats["orders_blocked"]
        )
        passed_count = self.stats["orders_placed"] + self.stats["orders_filled"]
        status = "pass" if failed_count == 0 else "fail"
        
        # Calculate KPIs
        total_orders = passed_count + failed_count
        maker_fill_rate = (
            float(self.stats["orders_filled"]) / float(total_orders)
            if total_orders > 0 else 0.0
        )
        risk_ratio_p95 = (
            float(total_notional) / float(params.max_total_notional_usd)
            if params.max_total_notional_usd > 0 else 0.0
        )
        
        # Build canonical report structure
        report = {
            "timestamp_ms": int(time.time() * 1000),
            "params": {
                "network": "testnet" if self.testnet else "mainnet",
                "symbols": sorted(params.symbols),
                "iterations": params.iterations,
                "maker_only": self.maker_only,
                "idempotency_enabled": self.enable_idempotency,
                "recon_interval_s": self.recon_interval_s,
            },
            "summary": {
                "status": status,
                "passed": passed_count,
                "failed": failed_count,
                "warnings": self.stats["freeze_events"],
                "maker_fill_rate": round(maker_fill_rate, 4),
                "risk_ratio_p95": round(risk_ratio_p95, 4),
                "latency_p95_ms": 0.0,  # TODO: Add latency tracking
            },
            "execution": {
                "iterations": params.iterations,
                "symbols": sorted(params.symbols),
                "idempotency_enabled": self.enable_idempotency,
                "maker_only": self.maker_only,
                "network_enabled": self.network_enabled,
                "testnet": self.testnet,
                "recon_interval_s": self.recon_interval_s,
            },
            "orders": {
                "placed": self.stats["orders_placed"],
                "filled": self.stats["orders_filled"],
                "rejected": self.stats["orders_rejected"],
                "canceled": self.stats["orders_canceled"],
                "risk_blocks": self.stats["risk_blocks"],
                "blocked": self.stats["orders_blocked"],
            },
            "positions": {
                "by_symbol": {sym: qty for sym, qty in sorted(positions.items())},
                "net_pos_usd": {sym: usd for sym, usd in sorted(net_pos_usd.items())},
                "total_notional_usd": total_notional,
            },
            "risk": {
                "frozen": self.risk_monitor.is_frozen(),
                "freeze_events": self.stats["freeze_events"],
                "last_freeze_reason": self.risk_monitor.last_freeze_reason,
                "last_freeze_symbol": self.risk_monitor.last_freeze_symbol,
                "blocks_total": self.risk_monitor.blocks_total,
                "freezes_total": self.risk_monitor.freezes_total,
            },
            "state": {
                "recoveries": self.stats["recoveries"],
                "duplicate_operations": self.stats["duplicate_operations"],
                "recon_runs": self.stats["recon_runs"],
            },
            "runtime": {
                "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        }
        
        # P0.10: Include recon report if available
        if self._last_recon_report is not None:
            report["recon"] = self._last_recon_report.to_dict()

        return report

    def recover_from_restart(self) -> dict[str, Any]:
        """
        Recover state after restart (DurableOrderStore only).
        
        Returns:
            Recovery report with open orders count
        """
        if not self.enable_idempotency or not hasattr(self.order_store, "recover_from_snapshot"):
            logger.warning("Recovery not supported without DurableOrderStore")
            return {"recovered": False, "reason": "DurableOrderStore not enabled"}
        
        # Recover from disk snapshot
        recovered_count = self.order_store.recover_from_snapshot()
        
        # Get open orders after recovery
        open_orders = self.order_store.get_open_orders()
        
        self.stats["recoveries"] += 1
        
        report = {
            "recovered": True,
            "total_orders_recovered": recovered_count,
            "open_orders_count": len(open_orders),
            "open_orders": [
                {
                    "client_order_id": o.client_order_id,
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)),
                    "qty": o.qty,
                    "price": o.price,
                    "state": getattr(o.state, "value", str(o.state)),
                }
                for o in open_orders
            ],
        }
        
        logger.info(f"Recovery complete: {recovered_count} orders, {len(open_orders)} open")
        return report
    
    def reset(self) -> None:
        """Reset state (for testing)."""
        if hasattr(self.order_store, "reset"):
            self.order_store.reset()
        self.risk_monitor.reset()
        self.stats = {
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_rejected": 0,
            "orders_canceled": 0,
            "risk_blocks": 0,
            "freeze_events": 0,
            "recoveries": 0,
            "duplicate_operations": 0,
            "orders_blocked": 0,
            "recon_runs": 0,
        }
        self._freeze_idem_key = None
        self._last_recon_ms = 0
        self._last_recon_report = None
        metrics.MAKER_ONLY_ENABLED.set(1.0 if self.maker_only else 0.0)


def run_shadow_demo(
    symbols: list[str],
    iterations: int,
    max_inventory_usd_per_symbol: float,
    max_total_notional_usd: float,
    edge_freeze_threshold_bps: float,
    fill_rate: float = 0.7,
    reject_rate: float = 0.05,
    latency_ms: int = 100,
) -> str:
    """
    Run shadow demo and return JSON report.
    
    This is the main entry point for CLI and tests.
    """
    # Create components
    exchange = FakeExchangeClient(
        fill_rate=fill_rate,
        reject_rate=reject_rate,
        latency_ms=latency_ms,
        seed=42,
    )

    order_store = InMemoryOrderStore()

    risk_monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=max_inventory_usd_per_symbol,
        max_total_notional_usd=max_total_notional_usd,
        edge_freeze_threshold_bps=edge_freeze_threshold_bps,
    )

    loop = ExecutionLoop(
        exchange=exchange,
        order_store=order_store,
        risk_monitor=risk_monitor,
    )

    # Run simulation
    params = ExecutionParams(
        symbols=symbols,
        iterations=iterations,
        max_inventory_usd_per_symbol=max_inventory_usd_per_symbol,
        max_total_notional_usd=max_total_notional_usd,
        edge_freeze_threshold_bps=edge_freeze_threshold_bps,
    )

    report = loop.run_shadow(params)

    # Return deterministic JSON
    return json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"

