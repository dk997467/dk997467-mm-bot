"""
Main quote loop with fast-cancel and taker cap enforcement.

This module orchestrates quote generation, fast cancellation on adverse moves,
and taker fill limiting to reduce slippage and improve edge capture.

Now includes:
- Queue-aware quoting: micro-repositioning for better fills
- Inventory-skew: automatic rebalancing via spread adjustments
- Adaptive spread: dynamic spread based on vol/liq/latency/pnl
- Risk guards: SOFT/HARD protection (halt/scale on dangerous conditions)
"""
import time
from typing import Dict, Optional, Any, List, Tuple
from src.common.di import AppContext
from src.execution.taker_tracker import TakerTracker
from src.execution.order_manager import OrderManager, OrderState
from src.strategy.queue_aware import QueueAwareRepricer, Quote, estimate_queue_position
from src.risk.inventory_skew import compute_skew_bps, apply_inventory_skew, get_inventory_pct
from src.strategy.adaptive_spread import AdaptiveSpreadEstimator
from src.risk.risk_guards import RiskGuards, GuardLevel


class QuoteLoop:
    """
    Main quote loop orchestrator with fast-cancel and taker cap.
    
    Features:
    - Fast-cancel: Cancel orders when price moves >threshold from order price
    - Cooldown: Pause after volatile spikes to avoid flip-flop
    - Taker cap: Block taker fills when hourly cap exceeded
    """
    
    def __init__(self, ctx: AppContext, order_manager: OrderManager):
        """
        Initialize quote loop.
        
        Args:
            ctx: Application context with configuration
            order_manager: Order manager instance
        """
        self.ctx = ctx
        self.order_manager = order_manager
        
        # Load fast-cancel config
        fast_cancel_cfg = getattr(ctx.cfg, 'fast_cancel', None)
        if fast_cancel_cfg:
            self.fast_cancel_enabled = fast_cancel_cfg.enabled
            self.cancel_threshold_bps = fast_cancel_cfg.cancel_threshold_bps
            self.cooldown_after_spike_ms = fast_cancel_cfg.cooldown_after_spike_ms
            self.spike_threshold_bps = fast_cancel_cfg.spike_threshold_bps
        else:
            # Defaults if config missing
            self.fast_cancel_enabled = True
            self.cancel_threshold_bps = 3.0
            self.cooldown_after_spike_ms = 500
            self.spike_threshold_bps = 10.0
        
        # Load taker cap config
        taker_cap_cfg = getattr(ctx.cfg, 'taker_cap', None)
        if taker_cap_cfg:
            self.taker_cap_enabled = taker_cap_cfg.enabled
            self.taker_tracker = TakerTracker(
                max_taker_fills_per_hour=taker_cap_cfg.max_taker_fills_per_hour,
                max_taker_share_pct=taker_cap_cfg.max_taker_share_pct,
                rolling_window_sec=taker_cap_cfg.rolling_window_sec
            )
        else:
            # Defaults
            self.taker_cap_enabled = True
            self.taker_tracker = TakerTracker()
        
        # Tracking for cooldown periods
        self.cooldown_until_ms: Dict[str, int] = {}  # symbol -> cooldown expiry timestamp
        self.last_mid_price: Dict[str, float] = {}  # symbol -> last mid price
        
        # Load queue-aware config
        queue_aware_cfg = getattr(ctx.cfg, 'queue_aware', None)
        if queue_aware_cfg:
            self.queue_aware_enabled = queue_aware_cfg.enabled
            self.queue_repricer = QueueAwareRepricer(queue_aware_cfg)
        else:
            # Defaults
            self.queue_aware_enabled = False
            self.queue_repricer = None
        
        # Load inventory-skew config
        inventory_skew_cfg = getattr(ctx.cfg, 'inventory_skew', None)
        if inventory_skew_cfg:
            self.inventory_skew_enabled = inventory_skew_cfg.enabled
            self.inventory_skew_cfg = inventory_skew_cfg
        else:
            # Defaults
            self.inventory_skew_enabled = False
            self.inventory_skew_cfg = None
        
        # Load adaptive spread config
        adaptive_spread_cfg = getattr(ctx.cfg, 'adaptive_spread', None)
        if adaptive_spread_cfg:
            self.adaptive_spread_enabled = adaptive_spread_cfg.enabled
            self.adaptive_spread = AdaptiveSpreadEstimator(adaptive_spread_cfg)
        else:
            # Defaults
            self.adaptive_spread_enabled = False
            self.adaptive_spread = None
        
        # Load risk guards config
        risk_guards_cfg = getattr(ctx.cfg, 'risk_guards', None)
        if risk_guards_cfg:
            self.risk_guards_enabled = risk_guards_cfg.enabled
            self.risk_guards = RiskGuards(risk_guards_cfg)
        else:
            # Defaults
            self.risk_guards_enabled = False
            self.risk_guards = None
        
        # Metrics tracking
        self.queue_nudge_count = 0
        self.queue_nudge_total_delta_bps = 0.0
        self.inv_skew_apply_count = 0
        self.inv_skew_total_bps = 0.0
        self.guard_soft_count = 0
        self.guard_hard_count = 0
    
    def should_fast_cancel(self, order: OrderState, current_mid: float, 
                          now_ms: int) -> tuple[bool, str]:
        """
        Check if order should be fast-canceled due to adverse price move.
        
        Args:
            order: Order state
            current_mid: Current mid price
            now_ms: Current timestamp in milliseconds
        
        Returns:
            (should_cancel, reason) tuple
        """
        if not self.fast_cancel_enabled:
            return False, ""
        
        # Check if in cooldown period
        symbol = order.symbol
        if symbol in self.cooldown_until_ms:
            if now_ms < self.cooldown_until_ms[symbol]:
                return False, "in_cooldown"
        
        # Calculate price drift from order price
        order_price = order.price
        if order_price <= 0 or current_mid <= 0:
            return False, "invalid_price"
        
        # Calculate drift in bps
        price_drift_bps = abs(current_mid - order_price) / order_price * 10000.0
        
        # Check if price moved beyond threshold
        if price_drift_bps > self.cancel_threshold_bps:
            # Check if this is a volatile spike (triggers cooldown)
            if price_drift_bps > self.spike_threshold_bps:
                # Trigger cooldown
                self.cooldown_until_ms[symbol] = now_ms + self.cooldown_after_spike_ms
                return True, f"volatile_spike ({price_drift_bps:.2f}bps > {self.spike_threshold_bps}bps)"
            
            return True, f"adverse_move ({price_drift_bps:.2f}bps > {self.cancel_threshold_bps}bps)"
        
        return False, ""
    
    async def check_and_cancel_stale_orders(self, symbol: str, current_mid: float, 
                                           now_ms: int) -> List[str]:
        """
        Check active orders and cancel those with adverse price moves.
        
        Args:
            symbol: Trading symbol
            current_mid: Current mid price
            now_ms: Current timestamp in milliseconds
        
        Returns:
            List of canceled client order IDs
        """
        if not self.fast_cancel_enabled:
            return []
        
        canceled_ids = []
        
        # Get active orders for symbol
        active_orders = {
            cid: order for cid, order in self.order_manager.active_orders.items()
            if order.symbol == symbol
        }
        
        for client_order_id, order in active_orders.items():
            should_cancel, reason = self.should_fast_cancel(order, current_mid, now_ms)
            
            if should_cancel:
                try:
                    print(f"[FAST-CANCEL] {symbol} cid={client_order_id} reason={reason}")
                    await self.order_manager.cancel_order(client_order_id)
                    canceled_ids.append(client_order_id)
                except Exception as e:
                    print(f"[FAST-CANCEL ERROR] {symbol} cid={client_order_id}: {e}")
        
        return canceled_ids
    
    def can_place_taker_order(self, symbol: str = None) -> tuple[bool, str]:
        """
        Check if taker order is allowed based on hourly caps.
        
        Args:
            symbol: Trading symbol (optional, for future per-symbol limits)
        
        Returns:
            (allowed, reason) tuple
        """
        if not self.taker_cap_enabled:
            return True, ""
        
        return self.taker_tracker.can_take_liquidity(symbol=symbol)
    
    def record_fill(self, symbol: str, is_taker: bool, timestamp_ms: int = None) -> None:
        """
        Record a fill for taker cap tracking.
        
        Args:
            symbol: Trading symbol
            is_taker: True if taker fill, False if maker fill
            timestamp_ms: Fill timestamp (None = current time)
        """
        if self.taker_cap_enabled:
            self.taker_tracker.record_fill(symbol, is_taker, timestamp_ms)
    
    def get_taker_stats(self) -> dict:
        """Get current taker fill statistics."""
        if self.taker_cap_enabled:
            return self.taker_tracker.get_stats()
        return {'taker_count': 0, 'total_count': 0, 'taker_share_pct': 0.0, 'can_take': True}
    
    def update_mid_price(self, symbol: str, mid_price: float) -> None:
        """Update last known mid price for symbol."""
        self.last_mid_price[symbol] = mid_price
    
    def get_cooldown_status(self, symbol: str) -> Optional[int]:
        """
        Get remaining cooldown time for symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Remaining cooldown time in milliseconds, or None if not in cooldown
        """
        if symbol not in self.cooldown_until_ms:
            return None
        
        now_ms = int(time.time() * 1000)
        cooldown_until = self.cooldown_until_ms[symbol]
        
        if now_ms >= cooldown_until:
            # Cooldown expired, clean up
            del self.cooldown_until_ms[symbol]
            return None
        
        return cooldown_until - now_ms
    
    def apply_queue_aware_nudge(self, quote: Quote, book: Dict[str, Any],
                               fair_value: float = None) -> Optional[Quote]:
        """
        Apply queue-aware nudge to improve queue position.
        
        Args:
            quote: Original quote
            book: Order book snapshot
            fair_value: Optional fair value constraint
        
        Returns:
            Nudged quote if applicable, None otherwise
        """
        if not self.queue_aware_enabled or self.queue_repricer is None:
            return None
        
        now_ms = int(time.time() * 1000)
        
        # Check if in cooldown
        in_cooldown = self.get_cooldown_status(quote.symbol) is not None
        
        # Try to nudge
        nudged_quote = self.queue_repricer.maybe_nudge(
            quote, book, now_ms, fair_value=fair_value, in_cooldown=in_cooldown
        )
        
        if nudged_quote:
            # Calculate delta for metrics
            delta_bps = abs(nudged_quote.price - quote.price) / quote.price * 10000.0
            self.queue_nudge_count += 1
            self.queue_nudge_total_delta_bps += delta_bps
            
            # Log nudge event
            print(f"[QUEUE] {quote.symbol} {quote.side}: "
                  f"px={quote.price:.4f} → {nudged_quote.price:.4f} "
                  f"(Δ={delta_bps:.2f}bps)")
        
        return nudged_quote
    
    def apply_inventory_skew_adjustment(self, symbol: str,
                                       bid_price: float, ask_price: float,
                                       position_base: float, max_position_base: float) -> Dict[str, float]:
        """
        Apply inventory-skew adjustments to bid/ask prices.
        
        Args:
            symbol: Trading symbol
            bid_price: Original bid price
            ask_price: Original ask price
            position_base: Current position in base currency
            max_position_base: Maximum position limit
        
        Returns:
            dict with adjusted prices and metrics
        """
        if not self.inventory_skew_enabled or self.inventory_skew_cfg is None:
            return {
                'bid_price': bid_price,
                'ask_price': ask_price,
                'skew_bps': 0.0,
                'bid_adj_bps': 0.0,
                'ask_adj_bps': 0.0,
            }
        
        # Calculate inventory percentage
        inv_pct = get_inventory_pct(position_base, max_position_base)
        
        # Apply skew
        result = apply_inventory_skew(
            self.inventory_skew_cfg, inv_pct, bid_price, ask_price
        )
        
        # Track metrics
        if result['skew_bps'] != 0.0:
            self.inv_skew_apply_count += 1
            self.inv_skew_total_bps += abs(result['skew_bps'])
            
            # Log skew event
            print(f"[SKEW] {symbol}: inv={inv_pct:.1f}%, skew={result['skew_bps']:.2f}bps, "
                  f"bid_adj={result['bid_adj_bps']:.2f}bps, ask_adj={result['ask_adj_bps']:.2f}bps")
        
        return result
    
    def get_queue_metrics(self) -> Dict[str, Any]:
        """Get queue-aware metrics."""
        if self.queue_nudge_count > 0:
            avg_delta = self.queue_nudge_total_delta_bps / self.queue_nudge_count
            applied_pct = 100.0  # Simplified - would need total quote count
        else:
            avg_delta = 0.0
            applied_pct = 0.0
        
        return {
            'queue_nudges_count': self.queue_nudge_count,
            'queue_avg_delta_bps': avg_delta,
            'queue_applied_pct': applied_pct,
        }
    
    def get_inventory_skew_metrics(self) -> Dict[str, Any]:
        """Get inventory-skew metrics."""
        if self.inv_skew_apply_count > 0:
            avg_skew = self.inv_skew_total_bps / self.inv_skew_apply_count
            applied_pct = 100.0  # Simplified
        else:
            avg_skew = 0.0
            applied_pct = 0.0
        
        return {
            'inv_skew_applied_pct': applied_pct,
            'inv_skew_avg_bps': avg_skew,
            'inv_skew_apply_count': self.inv_skew_apply_count,
        }
    
    def update_market_state(
        self, 
        symbol: str,
        mid_price: float,
        orderbook: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[float] = None,
        pnl_delta: Optional[float] = None,
        inventory_pct: Optional[float] = None,
        ts_ms: Optional[int] = None
    ) -> None:
        """
        Update adaptive spread and risk guards with market state.
        
        Args:
            symbol: Trading symbol
            mid_price: Current mid price
            orderbook: Order book snapshot (optional)
            latency_ms: Recent latency sample (optional)
            pnl_delta: Recent PnL change (optional)
            inventory_pct: Current inventory % (optional)
            ts_ms: Timestamp (None = now)
        """
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        
        # Update mid price tracker
        self.update_mid_price(symbol, mid_price)
        
        # Update adaptive spread
        if self.adaptive_spread_enabled and self.adaptive_spread:
            self.adaptive_spread.update_mid(mid_price, ts_ms)
            
            if latency_ms is not None:
                self.adaptive_spread.update_latency(latency_ms)
            
            if pnl_delta is not None:
                self.adaptive_spread.update_pnl(pnl_delta)
        
        # Update risk guards
        if self.risk_guards_enabled and self.risk_guards:
            self.risk_guards.update_vol(mid_price, ts_ms)
            
            if latency_ms is not None:
                self.risk_guards.update_latency(latency_ms)
            
            if pnl_delta is not None:
                self.risk_guards.update_pnl(pnl_delta)
            
            if inventory_pct is not None:
                self.risk_guards.update_inventory_pct(inventory_pct)
    
    def assess_risk_guards(self, now_ms: Optional[int] = None) -> Tuple[GuardLevel, List[str]]:
        """
        Assess risk guards and determine protection level.
        
        Args:
            now_ms: Current timestamp (None = now)
        
        Returns:
            (guard_level, reasons) tuple
        """
        if not self.risk_guards_enabled or not self.risk_guards:
            return GuardLevel.NONE, []
        
        level, reasons = self.risk_guards.assess(now_ms)
        
        # Update counters
        if level == GuardLevel.SOFT:
            self.guard_soft_count += 1
        elif level == GuardLevel.HARD:
            self.guard_hard_count += 1
        
        return level, reasons
    
    def compute_adaptive_spread(
        self,
        base_spread_bps: float,
        orderbook: Optional[Dict[str, Any]] = None,
        now_ms: Optional[int] = None
    ) -> float:
        """
        Compute adaptive spread based on market conditions.
        
        Args:
            base_spread_bps: Base spread (fallback if disabled)
            orderbook: Order book snapshot for liquidity calculation
            now_ms: Current timestamp
        
        Returns:
            Adaptive spread in bps
        """
        if not self.adaptive_spread_enabled or not self.adaptive_spread:
            return base_spread_bps
        
        # Extract liquidity from orderbook if available
        liq_bid = 1.0
        liq_ask = 1.0
        
        if orderbook:
            # Sum volume in top N levels
            depth_levels = self.adaptive_spread.cfg.depth_levels
            
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            liq_bid = sum(
                float(level[1]) for level in bids[:depth_levels]
            ) if bids else 1.0
            
            liq_ask = sum(
                float(level[1]) for level in asks[:depth_levels]
            ) if asks else 1.0
        
        return self.adaptive_spread.compute_spread_bps(
            liquidity_bid=liq_bid,
            liquidity_ask=liq_ask,
            now_ms=now_ms
        )

