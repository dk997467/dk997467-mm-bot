"""
Order management with amend-first logic and fallback to cancel+create.
"""

import asyncio
import time
import os
from types import SimpleNamespace
import hashlib
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from copy import deepcopy

from src.common.di import AppContext
from src.common.config import RuntimeGuardConfig
from src.connectors.bybit_rest import BybitRESTConnector
from src.execution.reconcile import OrderReconciler, OrderState
from src.metrics.exporter import Metrics


@dataclass
class OrderUpdateRequest:
    """Request to update an existing order."""
    client_order_id: str
    symbol: str
    new_price: Optional[float] = None
    new_qty: Optional[float] = None
    reason: str = ""


class OrderManager:
    """Enhanced order manager with amend-first logic and reconciliation."""
    
    def __init__(self, ctx: AppContext, rest_connector: BybitRESTConnector):
        """Initialize order manager with AppContext and REST connector."""
        self.ctx = ctx
        self.rest_connector = rest_connector
        # Preferred alias for REST in newer codepaths
        self.rest = rest_connector
        self.metrics: Optional[Metrics] = None
        if hasattr(ctx, 'metrics'):
            self.metrics = ctx.metrics
        
        # Reconciliation
        self.reconciler = OrderReconciler(ctx, rest_connector)
        # Effective overrides cache (autopolicy)
        self._eff: Dict[str, float] = {}
        # rollout config reference
        try:
            self._rollout = getattr(getattr(ctx, 'cfg', SimpleNamespace()), 'rollout', SimpleNamespace())
        except Exception:
            self._rollout = SimpleNamespace(traffic_split_pct=0, active="blue")
        
        # compiled overlays cache
        self._rollout_compiled: Dict[str, list] = {"blue": [], "green": []}

        # Amend configuration
        self.amend_price_threshold_bps = ctx.cfg.strategy.amend_price_threshold_bps
        self.amend_size_threshold = ctx.cfg.strategy.amend_size_threshold
        self.min_time_in_book_ms = ctx.cfg.strategy.min_time_in_book_ms
        
        # Order tracking
        self.active_orders: Dict[str, OrderState] = {}
        self.order_updates: Dict[str, OrderUpdateRequest] = {}
        
        # Anti-stale order guard configuration
        self.order_ttl_ms = ctx.cfg.strategy.order_ttl_ms
        self.price_drift_bps = ctx.cfg.strategy.price_drift_bps
        self.enable_anti_stale_guard = ctx.cfg.strategy.enable_anti_stale_guard
        
        # Initialize portfolio activity metrics to zeros for all symbols/sides
        try:
            self._init_portfolio_activity_metrics()
        except Exception:
            pass

    def _get_eff(self, key: str, default_val: float) -> float:
        try:
            ap = getattr(self.ctx, "autopolicy_overrides", {}) or {}
            return float(ap.get(key, default_val))
        except Exception:
            return float(default_val)

    def _is_shadow_enabled(self) -> bool:
        try:
            cfg_shadow = getattr(getattr(self.ctx, 'cfg', SimpleNamespace()), 'shadow', SimpleNamespace())
            if isinstance(cfg_shadow, SimpleNamespace) and hasattr(cfg_shadow, 'enabled'):
                return bool(cfg_shadow.enabled)
        except Exception:
            pass
        try:
            shadow = getattr(self.ctx, 'shadow', SimpleNamespace())
            return bool(getattr(shadow, 'enabled', False))
        except Exception:
            return False

    def _shadow_cid(self, orig_cid: Optional[str], symbol: str, side: str, price: float, size: float) -> str:
        oc = (orig_cid or "").strip()
        if oc:
            return "shadow:" + oc
        payload = f"{(symbol or '').upper()}|{(side or '').lower()}|{price:.8f}|{size:.8f}"
        h = hashlib.sha1(payload.encode('ascii','ignore')).hexdigest()[:12]
        return "shadow:h" + h

    def _fallback_cid(self, symbol: str, side: str, price: float, size: float) -> str:
        payload = f"{(symbol or '').upper()}|{(side or '').lower()}|{price:.8f}|{size:.8f}"
        h = hashlib.sha1(payload.encode('ascii','ignore')).hexdigest()[:12]
        return "fallback:h" + h

    def _is_order_stale(self, order: OrderState, current_mid_price: float) -> Tuple[bool, str, Optional[float]]:
        """
        Check if an order is stale based on TTL and price drift.
        
        Returns:
            (is_stale, reason, drift_bps)
        """
        if not self.enable_anti_stale_guard:
            return False, "", None
        
        current_time = time.time() * 1000  # Convert to milliseconds
        order_age_ms = current_time - order.created_time
        
        # Check TTL
        if order_age_ms > self.order_ttl_ms:
            return True, "ttl_expired", None
        
        # Check price drift
        if current_mid_price > 0:
            price_diff_bps = abs(order.price - current_mid_price) / current_mid_price * 10000
            if price_diff_bps > self.price_drift_bps:
                return True, "price_drift", price_diff_bps
        
        return False, "", None
    
    def _get_order_age_bucket(self, age_ms: float) -> str:
        """Get bucket label for order age metrics."""
        if age_ms <= 100:
            return "0-100ms"
        elif age_ms <= 500:
            return "100-500ms"
        elif age_ms <= 1000:
            return "500-1000ms"
        elif age_ms <= 5000:
            return "1000-5000ms"
        else:
            return "5000ms+"
    
    async def _handle_stale_order(self, order: OrderState, reason: str, drift_bps: Optional[float] = None) -> bool:
        """
        Handle a stale order by either amending or cancelling it.
        
        Returns:
            True if order was handled successfully, False otherwise
        """
        try:
            if reason == "ttl_expired":
                # For TTL expired orders, cancel them
                success = await self.cancel_order(order.client_order_id)
                if success and self.metrics:
                    self.metrics.stale_cancels_total.labels(symbol=order.symbol, reason=reason).inc()
                return success
            elif reason == "price_drift":
                # For price drift orders, try to amend first, fallback to cancel
                current_mid = await self._get_current_mid_price(order.symbol)
                if current_mid and current_mid > 0:
                    # Calculate new price based on current mid
                    side_multiplier = 1 if order.side.lower() == "buy" else -1
                    new_price = current_mid * (1 + side_multiplier * self.price_drift_bps / 10000)
                    
                    success = await self.update_order(order.client_order_id, new_price=new_price, reason="price_drift_refresh")
                    if success and self.metrics:
                        self.metrics.refresh_amends_total.labels(symbol=order.symbol, reason=reason).inc()
                    return success
                else:
                    # Fallback to cancel if can't get current mid price
                    success = await self.cancel_order(order.client_order_id)
                    if success and self.metrics:
                        self.metrics.stale_cancels_total.labels(symbol=order.symbol, reason=reason).inc()
                    return success
            
            return False
        except Exception as e:
            print(f"Error handling stale order {order.client_order_id}: {e}")
            return False
    
    async def _get_current_mid_price(self, symbol: str) -> Optional[float]:
        """Get current mid price for a symbol."""
        try:
            # Try to get from order book
            orderbook = await self.rest.get_orderbook(symbol, limit=1)
            if orderbook and 'result' in orderbook:
                bids = orderbook['result'].get('b', [])
                asks = orderbook['result'].get('a', [])
                if bids and asks:
                    bid_price = float(bids[0][0])
                    ask_price = float(asks[0][0])
                    return (bid_price + ask_price) / 2
        except Exception:
            pass
        
        # Fallback: try to get from active orders (use average of our orders)
        try:
            symbol_orders = [o for o in self.active_orders.values() if o.symbol == symbol]
            if symbol_orders:
                total_price = sum(o.price for o in symbol_orders)
                return total_price / len(symbol_orders)
        except Exception:
            pass
        
        return None
    
    async def check_and_refresh_stale_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Check all active orders for staleness and refresh/cancel as needed.
        
        Returns:
            Summary of actions taken
        """
        if not self.enable_anti_stale_guard:
            return {"enabled": False, "actions": []}
        
        summary = {
            "enabled": True,
            "symbol": symbol or "all",
            "actions": [],
            "ttl_cancels": 0,
            "drift_refreshes": 0,
            "errors": 0
        }
        
        orders_to_check = []
        if symbol:
            orders_to_check = [o for o in self.active_orders.values() if o.symbol == symbol]
        else:
            orders_to_check = list(self.active_orders.values())
        
        for order in orders_to_check:
            try:
                # Get current mid price for drift calculation
                current_mid = await self._get_current_mid_price(order.symbol)
                
                # Check if order is stale
                is_stale, reason, drift_bps = self._is_order_stale(order, current_mid or 0)
                
                if is_stale:
                    # Update age metrics
                    if self.metrics:
                        current_time = time.time() * 1000
                        order_age_ms = current_time - order.created_time
                        bucket = self._get_order_age_bucket(order_age_ms)
                        self.metrics.order_age_ms_bucket_total.labels(symbol=order.symbol, bucket=bucket).inc()
                    
                    # Handle stale order
                    success = await self._handle_stale_order(order, reason, drift_bps)
                    
                    action = {
                        "client_order_id": order.client_order_id,
                        "symbol": order.symbol,
                        "reason": reason,
                        "drift_bps": drift_bps,
                        "success": success
                    }
                    
                    if success:
                        if reason == "ttl_expired":
                            summary["ttl_cancels"] += 1
                        elif reason == "price_drift":
                            summary["drift_refreshes"] += 1
                    else:
                        summary["errors"] += 1
                    
                    summary["actions"].append(action)
                    
            except Exception as e:
                print(f"Error checking order {order.client_order_id}: {e}")
                summary["errors"] += 1
        
        return summary

    def _choose_color(self, cid: str) -> str:
        try:
            split = int(getattr(self._rollout, 'traffic_split_pct', 0))
        except Exception:
            split = 0
        # pinned CIDs always GREEN
        try:
            pins = set(getattr(self._rollout, 'pinned_cids_green', []) or [])
            if cid in pins:
                if self.metrics:
                    try:
                        self.metrics.inc_rollout_pinned_hit()
                    except Exception:
                        pass
                return "green"
        except Exception:
            pass
        try:
            salt = str(getattr(self._rollout, 'salt', ''))
            payload = f"{salt}|{cid or ''}"
            h = hashlib.sha1(payload.encode('ascii', 'ignore')).hexdigest()
            v = int(h[:8], 16) % 100
        except Exception:
            v = 0
        return "green" if v < split else "blue"

    def _compile_overlay(self, overlay: Dict[str, Any]) -> list:
        """Compile dotted-key overlay to tuple paths for fast application.
        
        Returns: [(path_tuple, value), ...] sorted by path for determinism.
        """
        if not isinstance(overlay, dict):
            return []
        compiled = []
        for key, value in overlay.items():
            try:
                path = str(key).split('.') if key is not None else []
                if path:
                    compiled.append((tuple(path), value))
            except Exception:
                continue
        return sorted(compiled, key=lambda x: x[0])
    
    def _set_at(self, base: Dict[str, Any], path_tuple: tuple, value: Any) -> Dict[str, Any]:
        """Set value at dotted path using copy-on-write - base is not mutated."""
        try:
            result = dict(base)  # shallow copy root
            cursor = result
            base_cursor = base
            
            for part in path_tuple[:-1]:
                if part not in cursor or not isinstance(cursor.get(part), dict):
                    cursor[part] = {}
                    base_cursor = None  # no longer tracking base path
                else:
                    # COW: if this nested dict is shared with base, copy it
                    if base_cursor and part in base_cursor and cursor[part] is base_cursor[part]:
                        cursor[part] = dict(cursor[part])
                    base_cursor = base_cursor.get(part) if base_cursor else None
                cursor = cursor[part]
            
            cursor[path_tuple[-1]] = value
            return result
        except Exception:
            return dict(base)
    
    def _apply_overlay(self, base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """Apply overlay using compiled paths if available, else fallback to dotted strings."""
        # Determine color by comparing overlay dict to rollout config
        color = "blue"
        try:
            green_overlay = getattr(self._rollout, 'green', {}) or {}
            if overlay is green_overlay or overlay == green_overlay:
                color = "green"
        except Exception:
            pass
        compiled = self._rollout_compiled.get(color, [])
        
        if compiled:
            # Use compiled paths
            result = base
            for path_tuple, value in compiled:
                result = self._set_at(result, path_tuple, value)
            return result
        else:
            # Fallback to original dotted string logic
            try:
                result = deepcopy(base)
            except Exception:
                result = dict(base)
            if not isinstance(overlay, dict):
                return result
            for key, value in overlay.items():
                try:
                    path = str(key).split('.') if key is not None else []
                    if not path:
                        continue
                    cursor = result
                    for part in path[:-1]:
                        if part not in cursor or not isinstance(cursor.get(part), dict):
                            cursor[part] = {}
                        cursor = cursor[part]
                    cursor[path[-1]] = value
                except Exception:
                    continue
            return result
    
    def update_rollout_config(self, rollout_config) -> None:
        """Update rollout config and compile overlays."""
        self._rollout = rollout_config
        try:
            blue_overlay = getattr(rollout_config, 'blue', {}) or {}
            green_overlay = getattr(rollout_config, 'green', {}) or {}
            
            # Compile overlays
            self._rollout_compiled["blue"] = self._compile_overlay(blue_overlay)
            self._rollout_compiled["green"] = self._compile_overlay(green_overlay)
            
            # Increment metric on first compilation
            if (self._rollout_compiled["blue"] or self._rollout_compiled["green"]) and self.metrics:
                try:
                    self.metrics.inc_rollout_overlay_compiled()
                except Exception:
                    pass
        except Exception:
            # Fallback to empty compiled overlays
            self._rollout_compiled = {"blue": [], "green": []}
    
    async def start(self):
        """Start order manager and reconciliation loop."""
        # Start reconciliation in background
        try:
            self._init_portfolio_activity_metrics()
        except Exception:
            pass
        asyncio.create_task(self.reconciler.start_reconciliation_loop())
        
        # Start anti-stale order guard loop if enabled
        if self.enable_anti_stale_guard:
            asyncio.create_task(self._anti_stale_guard_loop())
    
    async def _anti_stale_guard_loop(self):
        """Background loop for checking and refreshing stale orders."""
        while True:
            try:
                await asyncio.sleep(1.0)  # Check every second
                await self.check_and_refresh_stale_orders()
            except Exception as e:
                print(f"Anti-stale guard loop error: {e}")
                await asyncio.sleep(5.0)  # Back off on errors
    
    async def place_order(self, symbol: str, side: str, order_type: str, qty: float,
                         price: Optional[float] = None, time_in_force: str = "GTC",
                         client_order_id: Optional[str] = None, cid: Optional[str] = None) -> str:
        """Place new order with idempotent client order ID."""
        try:
            client_order_id = (client_order_id or "").strip()
            cid = (cid or "").strip()
            # Throttle guard
            throttle = getattr(self.ctx, 'throttle', None)
            if throttle:
                if not throttle.allowed('create', symbol, time.time()):
                    raise Exception("throttle_block")
            
            # Runtime guard
            guard = getattr(self.ctx, 'guard', None)
            # Effective pause: manual override always blocks; paused blocks unless dry_run
            manual = bool(getattr(getattr(self.ctx, 'cfg', None), 'runtime_guard', RuntimeGuardConfig()).manual_override_pause)
            dry_run = bool(getattr(getattr(self.ctx, 'cfg', None), 'runtime_guard', RuntimeGuardConfig()).dry_run)
            if manual or (getattr(guard, 'paused', False) and not dry_run):
                raise Exception("guard_paused")
            # Scheduler guard (per-symbol map overrides global)
            chosen_sched = None
            try:
                sched_map = getattr(self.ctx, 'schedulers', None)
                if isinstance(sched_map, dict) and symbol in sched_map:
                    chosen_sched = sched_map[symbol]
                else:
                    chosen_sched = getattr(self.ctx, 'scheduler', None)
            except Exception:
                chosen_sched = getattr(self.ctx, 'scheduler', None)

            if chosen_sched:
                allowed = (getattr(chosen_sched, 'is_trade_allowed', None) and chosen_sched.is_trade_allowed())
                if not allowed:
                    # classify cooldown vs closed
                    try:
                        if getattr(chosen_sched, 'is_open', None) and getattr(chosen_sched, 'in_cooldown_open', None):
                            if chosen_sched.is_open() and chosen_sched.in_cooldown_open():
                                raise Exception("scheduler_cooldown_block")
                    except Exception:
                        # fall through to closed
                        pass
                    raise Exception("scheduler_closed")
            # Enforce portfolio caps if targets are available
            try:
                targets = getattr(self.ctx, 'portfolio_targets', None)
                if targets and symbol in targets:
                    target = targets[symbol]
                    # Cap active levels per side (consider AutoPolicy effective cap)
                    active_per_side = self.get_active_levels(symbol, side)
                    eff_levels_cap = int(self._get_eff("levels_per_side_max_eff", int(getattr(target, 'max_levels', 0))))
                    allowed_levels = min(int(getattr(target, 'max_levels', 0)), eff_levels_cap)
                    if active_per_side >= allowed_levels:
                        raise Exception(f"Portfolio cap reached for {symbol} {side}: max_levels={allowed_levels}")
                    
                    # Scale order size to respect target_usd budget (if price known)
                    if price and qty:
                        # If side budgeting is desired, pass side; else None
                        current_active_usd = self.get_active_usd(symbol, side)
                        remaining_usd = float(target.target_usd) - current_active_usd
                        if remaining_usd <= 0:
                            raise Exception(f"Portfolio budget exhausted for {symbol}: target_usd={target.target_usd}")
                        max_affordable_qty = remaining_usd / float(price)
                        try:
                            max_affordable_qty = self.rest._round_to_lot(max_affordable_qty, symbol)  # type: ignore[attr-defined]
                        except Exception:
                            try:
                                max_affordable_qty = self.rest_connector._round_to_lot(max_affordable_qty, symbol)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        if max_affordable_qty < qty:
                            qty = max_affordable_qty
                            if qty <= 0:
                                raise Exception(f"Calculated non-positive qty due to portfolio cap for {symbol}")
            except Exception as e:
                # Surface portfolio cap errors to caller for handling
                raise

            # Circuit breaker allow
            circuit = getattr(self.ctx, 'circuit', None)
            if circuit and not circuit.allowed('create'):
                raise Exception("circuit_open")

            # Adaptive backoff (deterministic jitter & cap inside ThrottleGuard)
            if throttle:
                error_rate = getattr(self.ctx, 'rest_error_rate', 0.0)
                ws_lag = getattr(self.ctx, 'last_ws_lag_ms', 0.0)
                backoff_ms = throttle.compute_backoff_ms(error_rate, ws_lag, time.time(), symbol)
                if backoff_ms > 0:
                    await asyncio.sleep(backoff_ms / 1000.0)
                    if self.metrics:
                        try:
                            self.metrics.throttle_backoffs_total.inc()
                        except Exception:
                            pass

            # Determine rollout color based on sticky CID
            eff_cid = (client_order_id or cid or '').strip()
            if not eff_cid:
                eff_cid = self._fallback_cid(symbol, side, float(price or 0.0), float(qty or 0.0))
            color = self._choose_color(eff_cid)
            if self.metrics:
                try:
                    self.metrics.inc_rollout_order(color)
                except Exception:
                    pass
            # record order submit event if recorder enabled
            try:
                bot = getattr(self.ctx, 'bot', None)
                if bot and hasattr(bot, '_record_execution_event'):
                    bot._record_execution_event({
                        "ts": int(time.time()*1000),
                        "kind": "order",
                        "symbol": str(symbol),
                        "side": str(side),
                        "price": float(price or 0.0),
                        "qty": float(qty or 0.0),
                        "cid": str(eff_cid),
                        "color": str(color),
                    })
            except Exception:
                pass

            # Shadow mode: emulate order without REST (no mutation of active orders/snapshots)
            if self._is_shadow_enabled():
                # prefer explicit client_order_id; fallback to legacy cid
                _cid = client_order_id or cid
                scid = self._shadow_cid(_cid, symbol, side, float(price or 0.0), float(qty))
                # Record only shadow metrics via exporter aggregator
                try:
                    m = getattr(self.ctx, 'metrics', None)
                    if m:
                        diff_bps = 0.0
                        size_pct = 0.0
                        if hasattr(m, 'record_shadow_sample'):
                            m.record_shadow_sample(symbol, diff_bps, size_pct)
                        elif hasattr(m, 'shadow_record'):
                            m.shadow_record(symbol, diff_bps, size_pct)
                        else:
                            # minimal fallback for test stubs
                            try:
                                m.shadow_orders_total.labels(symbol=symbol).inc()
                            except Exception:
                                pass
                            try:
                                m.shadow_price_diff_bps_last.labels(symbol=symbol).set(diff_bps)
                            except Exception:
                                pass
                            try:
                                m.shadow_size_diff_pct_last.labels(symbol=symbol).set(size_pct)
                            except Exception:
                                pass
                            try:
                                m.shadow_price_diff_bps_avg.labels(symbol=symbol).set(diff_bps)
                            except Exception:
                                pass
                            try:
                                m.shadow_size_diff_pct_avg.labels(symbol=symbol).set(size_pct)
                            except Exception:
                                pass
                except Exception:
                    pass
                return scid

            start_ts = time.time()
            response = await self.rest_connector.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                qty=qty,
                price=price,
                time_in_force=time_in_force
            )
            
            if response.get('retCode') != 0:
                try:
                    guard = getattr(self.ctx, 'guard', None)
                    if guard:
                        guard.on_reject(client_order_id, time.time())
                    if circuit:
                        http_code = int(response.get('httpCode', 500)) if isinstance(response, dict) else 500
                        circuit.on_result(client_order_id, ok=False, http_code=http_code, now=time.time())
                    if self.metrics:
                        try:
                            self.metrics.inc_rollout_reject(color)
                            # Chaos hook: inflate green rejects metrics only
                            try:
                                chaos = getattr(getattr(self.ctx, 'cfg', SimpleNamespace()), 'chaos', SimpleNamespace())
                                if color == 'green' and getattr(chaos, 'enabled', False):
                                    inflate = float(getattr(chaos, 'reject_inflate_pct', 0.0))
                                    extra = int(inflate)
                                    if extra > 0:
                                        for _ in range(extra):
                                            self.metrics.inc_rollout_reject(color)
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
                # record reject event
                try:
                    bot = getattr(self.ctx, 'bot', None)
                    if bot and hasattr(bot, '_record_execution_event'):
                        bot._record_execution_event({
                            "ts": int(time.time()*1000),
                            "kind": "reject",
                            "symbol": str(symbol),
                            "side": str(side),
                            "price": float(price or 0.0),
                            "qty": float(qty or 0.0),
                            "cid": str(eff_cid),
                            "color": str(color),
                        })
                except Exception:
                    pass
                raise Exception(f"Failed to place order: {response.get('retMsg')}")
            else:
                try:
                    guard = getattr(self.ctx, 'guard', None)
                    if guard:
                        guard.on_send_ok(client_order_id, time.time())
                    throttle = getattr(self.ctx, 'throttle', None)
                    if throttle:
                        throttle.on_event('create', symbol, time.time())
                    if circuit:
                        circuit.on_result(client_order_id, ok=True, http_code=200, now=time.time())
                    if self.metrics:
                        try:
                            latency_ms = (time.time() - start_ts) * 1000.0
                            # Chaos hook: inflate green latency in metrics only
                            try:
                                chaos = getattr(getattr(self.ctx, 'cfg', SimpleNamespace()), 'chaos', SimpleNamespace())
                                if color == 'green' and getattr(chaos, 'enabled', False):
                                    latency_ms += max(0.0, float(getattr(chaos, 'latency_inflate_ms', 0)))
                            except Exception:
                                pass
                            self.metrics.inc_rollout_fill(color, latency_ms)
                        except Exception:
                            pass
                except Exception:
                    pass
                # record fill event (success submit)
                try:
                    bot = getattr(self.ctx, 'bot', None)
                    if bot and hasattr(bot, '_record_execution_event'):
                        bot._record_execution_event({
                            "ts": int(time.time()*1000),
                            "kind": "fill",
                            "symbol": str(symbol),
                            "side": str(side),
                            "price": float(price or 0.0),
                            "qty": float(qty or 0.0),
                            "cid": str(eff_cid),
                            "color": str(color),
                        })
                    # turnover: record notional
                    try:
                        notional = abs(float(price or 0.0) * float(qty or 0.0))
                        if self.metrics and hasattr(self.metrics, 'record_trade_notional'):
                            self.metrics.record_trade_notional(str(symbol), float(notional))
                    except Exception:
                        pass
                except Exception:
                    pass
            
            result = response.get('result', {})
            order_id = result.get('orderId')
            client_order_id = result.get('orderLinkId')
            
            # Create local order state
            order_state = OrderState(
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                price=price or 0,
                qty=qty,
                status='New',
                filled_qty=0,
                remaining_qty=qty,
                created_time=time.time(),
                last_update_time=time.time()
            )
            
            # Track locally
            self.active_orders[client_order_id] = order_state
            self.reconciler.add_local_order(order_state)
            
            # Update metrics
            if self.metrics:
                self.metrics.creates_total.labels(symbol=symbol).inc()
                self.metrics.orders_active.labels(symbol=symbol, side=side).inc()
            # Update portfolio activity metrics
            try:
                self._update_portfolio_activity_metrics(symbol)
            except Exception:
                pass
            
            # Check for stale orders after placing new order
            if self.enable_anti_stale_guard:
                try:
                    await self.check_and_refresh_stale_orders(symbol)
                except Exception as e:
                    print(f"Anti-stale check failed after placing order: {e}")
            
            return client_order_id
            
        except Exception as e:
            print(f"Error placing order: {e}")
            raise
    
    async def update_order(self, client_order_id: str, new_price: Optional[float] = None,
                          new_qty: Optional[float] = None, reason: str = "") -> bool:
        """Update existing order using amend-first logic with fallback."""
        if client_order_id not in self.active_orders:
            raise ValueError(f"Order {client_order_id} not found")
        
        order = self.active_orders[client_order_id]
        
        # Throttle guard
        throttle = getattr(self.ctx, 'throttle', None)
        if throttle:
            if not throttle.allowed('amend', order.symbol, time.time()):
                raise Exception("throttle_block")
        
        # Block amends when guard paused
        guard = getattr(self.ctx, 'guard', None)
        if getattr(guard, 'paused', False):
            raise Exception("guard_paused")
        
        # Check if order is eligible for amendment
        if not self._can_amend_order(order, new_price, new_qty):
            # Increment amend attempts metric even for ineligible orders
            if self.metrics:
                self.metrics.on_amend_attempt(order.symbol, order.side)
            return await self._replace_order_cancel_create(client_order_id, new_price, new_qty, reason)
        
        # Try to amend first
        try:
            # Increment amend attempts metric
            if self.metrics:
                self.metrics.on_amend_attempt(order.symbol, order.side)
            circuit = getattr(self.ctx, 'circuit', None)
            if circuit and not circuit.allowed('amend'):
                raise Exception("circuit_open")
            
            await self._amend_order(client_order_id, new_price, new_qty)
            return True
        except Exception as e:
            print(f"Amend failed for {client_order_id}, falling back to cancel+create: {e}")
            return await self._replace_order_cancel_create(client_order_id, new_price, new_qty, reason)
    
    def _can_amend_order(self, order: OrderState, new_price: Optional[float], 
                         new_qty: Optional[float]) -> bool:
        """Check if order can be amended."""
        # Check if order has been in book long enough
        time_in_book_ms = (time.time() - order.created_time) * 1000
        eff_min_tib = self._get_eff("min_time_in_book_ms_eff", self.min_time_in_book_ms)
        if time_in_book_ms < eff_min_tib:
            return False
        
        # Check price change threshold using rounded values
        if new_price is not None:
            rounded_new_price = self.rest_connector._round_to_tick(new_price, order.symbol)
            price_change_bps = abs(rounded_new_price - order.price) / order.price * 10000
            eff_rep_bps = self._get_eff("replace_threshold_bps_eff", self.amend_price_threshold_bps)
            if price_change_bps > eff_rep_bps:
                return False
        
        # Check quantity change threshold using rounded values
        if new_qty is not None:
            rounded_new_qty = self.rest_connector._round_to_lot(new_qty, order.symbol)
            qty_change_ratio = abs(rounded_new_qty - order.qty) / order.qty
            if qty_change_ratio > self.amend_size_threshold:
                return False
        
        return True
    
    async def _amend_order(self, client_order_id: str, new_price: Optional[float],
                          new_qty: Optional[float]) -> None:
        """Amend order using exchange API."""
        order = self.active_orders[client_order_id]
        
        response = await self.rest_connector.amend_order(
            symbol=order.symbol,
            client_order_id=client_order_id,
            price=new_price,
            qty=new_qty
        )
        
        if response.get('retCode') != 0:
            raise Exception(f"Amend failed: {response.get('retMsg')}")
        
        # Update local state with rounded values
        if new_price is not None:
            rounded_price = self.rest_connector._round_to_tick(new_price, order.symbol)
            order.price = rounded_price
        if new_qty is not None:
            rounded_qty = self.rest_connector._round_to_lot(new_qty, order.symbol)
            order.qty = rounded_qty
            order.remaining_qty = rounded_qty - order.filled_qty
        
        order.last_update_time = time.time()
        
        # Update metrics
        if self.metrics:
            self.metrics.replaces_total.labels(symbol=order.symbol).inc()
            self.metrics.on_amend_success(order.symbol, order.side)
        # Update portfolio activity metrics
        try:
            self._update_portfolio_activity_metrics(order.symbol)
        except Exception:
            pass
        # Update portfolio activity metrics
        try:
            self._update_portfolio_activity_metrics(order.symbol)
        except Exception:
            pass
    
    async def _replace_order_cancel_create(self, client_order_id: str, new_price: Optional[float],
                                         new_qty: Optional[float], reason: str) -> bool:
        """Replace order using cancel + create approach."""
        # Block replace when guard paused
        guard = getattr(self.ctx, 'guard', None)
        if getattr(guard, 'paused', False):
            raise Exception("guard_paused")
        order = self.active_orders[client_order_id]
        
        try:
            # Cancel existing order
            await self.cancel_order(client_order_id)
            
            # Wait a bit for cancellation to propagate
            await asyncio.sleep(0.1)
            
            # Create new order
            new_client_order_id = await self.place_order(
                symbol=order.symbol,
                side=order.side,
                order_type="Limit",
                qty=new_qty or order.qty,
                price=new_price or order.price
            )
            
            # Update tracking - always remove old order and add new one
            self.reconciler.remove_local_order(client_order_id)
            if client_order_id in self.active_orders:
                del self.active_orders[client_order_id]
            
            # Add new order to tracking if it has a different ID
            if new_client_order_id != client_order_id:
                # The new order is already tracked by place_order
                pass
            
            # Update metrics for replace operation
            if self.metrics:
                self.metrics.replaces_total.labels(symbol=order.symbol).inc()
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
            
            return True
            
        except Exception as e:
            print(f"Cancel+create replacement failed for {client_order_id}: {e}")
            return False
    
    async def cancel_order(self, client_order_id: str) -> bool:
        """Cancel order by client order ID."""
        if client_order_id not in self.active_orders:
            raise ValueError(f"Order {client_order_id} not found")
        
        order = self.active_orders[client_order_id]
        
        try:
            # mark start time for latency
            self._last_cancel_start_ts = time.time()
            response = await self.rest_connector.cancel_order(
                symbol=order.symbol,
                client_order_id=client_order_id
            )
            
            if response.get('retCode') != 0:
                raise Exception(f"Cancel failed: {response.get('retMsg')}")
            
            # Update local state
            order.status = 'Cancelled'
            order.last_update_time = time.time()
            # Observe cancel latency into guard if available
            try:
                start_ts = getattr(self, '_last_cancel_start_ts', None)
                if start_ts is not None:
                    elapsed_ms = (time.time() - start_ts) * 1000.0
                    guard = getattr(self.ctx, 'guard', None)
                    if guard:
                        guard.add_cancel_latency_sample(elapsed_ms, time.time())
                    self._last_cancel_start_ts = None
            except Exception:
                pass
            
            # Remove from active tracking
            del self.active_orders[client_order_id]
            self.reconciler.remove_local_order(client_order_id)
            
            # Update metrics
            if self.metrics:
                self.metrics.cancels_total.labels(symbol=order.symbol).inc()
                self.metrics.orders_active.labels(symbol=order.symbol, side=order.side).dec()
        
            # Check for stale orders after cancelling
            if self.enable_anti_stale_guard:
                try:
                    await self.check_and_refresh_stale_orders(order.symbol)
                except Exception as e:
                    print(f"Anti-stale check failed after cancelling order: {e}")
        
            # Update portfolio activity metrics
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
            
            return True
            
        except Exception as e:
            print(f"Error cancelling order {client_order_id}: {e}")
            raise
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all active orders, optionally filtered by symbol."""
        cancelled_count = 0
        
        for client_order_id in list(self.active_orders.keys()):
            order = self.active_orders[client_order_id]
            
            if symbol is None or order.symbol == symbol:
                try:
                    await self.cancel_order(client_order_id)
                    cancelled_count += 1
                except Exception as e:
                    print(f"Failed to cancel order {client_order_id}: {e}")
        
        return cancelled_count

    async def cancel_all_for_symbol(self, symbol: str) -> int:
        """Cancel all active orders for symbol, return count."""
        count = 0
        for cid, o in list(self.active_orders.items()):
            if o.symbol == symbol:
                try:
                    await self.cancel_order(cid)
                    count += 1
                except Exception:
                    pass
        if self.metrics and count > 0:
            try:
                self.metrics.guard_cancels_total.inc(count)
            except Exception:
                pass
        return count
    
    def get_order(self, client_order_id: str) -> Optional[OrderState]:
        """Get order by client order ID."""
        return self.active_orders.get(client_order_id)
    
    def get_active_orders(self, symbol: Optional[str] = None) -> Dict[str, OrderState]:
        """Get all active orders, optionally filtered by symbol."""
        if symbol is None:
            return self.active_orders.copy()
        
        return {
            cid: order for cid, order in self.active_orders.items()
            if order.symbol == symbol
        }

    def _update_portfolio_activity_metrics(self, symbol: str) -> None:
        m = getattr(self.ctx, "metrics", None)
        if not m:
            return
        try:
            usd = self.get_active_usd(symbol, None)
            m.portfolio_active_usd.labels(symbol=symbol).set(float(usd))
            for s in ("Buy", "Sell"):
                levels = self.get_active_levels(symbol, s)
                m.portfolio_active_levels.labels(symbol=symbol, side=s).set(int(levels))
        except Exception:
            pass

    def _init_portfolio_activity_metrics(self) -> None:
        m = getattr(self.ctx, 'metrics', None)
        cfg = getattr(getattr(self.ctx, 'cfg', None), 'trading', None)
        if not m or not cfg:
            return
        try:
            symbols = list(getattr(cfg, 'symbols', []) or [])
            for sym in symbols:
                m.portfolio_active_usd.labels(symbol=sym).set(0.0)
                for s in ("Buy", "Sell"):
                    m.portfolio_active_levels.labels(symbol=sym, side=s).set(0)
        except Exception:
            pass

    def _update_portfolio_activity_metrics(self, symbol: str) -> None:
        m = getattr(self.ctx, 'metrics', None)
        if not m:
            return
        try:
            usd = self.get_active_usd(symbol, None)
            m.portfolio_active_usd.labels(symbol=symbol).set(float(usd))
            for s in ("Buy", "Sell"):
                levels = self.get_active_levels(symbol, s)
                m.portfolio_active_levels.labels(symbol=symbol, side=s).set(int(levels))
        except Exception:
            pass

    def get_active_levels(self, symbol: str, side: str) -> int:
        """Get number of active levels for symbol/side (count active orders)."""
        return sum(1 for o in self.active_orders.values() if o.symbol == symbol and o.side == side)

    def get_active_usd(self, symbol: str, side: Optional[str] = None) -> float:
        """Compute total active notional for symbol (optionally per side)."""
        total = 0.0
        for o in self.active_orders.values():
            try:
                if o.symbol == symbol and o.price and o.remaining_qty \
                   and (side is None or o.side == side):
                    total += float(o.price) * float(o.remaining_qty)
            except Exception:
                continue
        return total

    async def sync_open_orders(self, symbol: Optional[str] = None) -> int:
        """Fetch open orders from REST and repopulate active_orders. Update metrics."""
        fetched = 0
        try:
            resp = await self.rest_connector.get_active_orders(symbol=symbol)
            # Expected format similar to Bybit v5
            orders = []
            try:
                orders = resp.get('result', {}).get('list', []) or []
            except Exception:
                orders = []
            for item in orders:
                try:
                    sym = str(item.get('symbol'))
                    side = str(item.get('side'))
                    cid = str(item.get('orderLinkId') or item.get('orderId'))
                    price = float(item.get('price', 0) or 0)
                    qty = float(item.get('qty', 0) or 0)
                    filled = float(item.get('cumExecQty', 0) or 0)
                    status = str(item.get('orderStatus') or 'New')
                    if not cid:
                        continue
                    state = OrderState(
                        order_id=str(item.get('orderId') or ''),
                        client_order_id=cid,
                        symbol=sym,
                        side=side,
                        price=price,
                        qty=qty,
                        status=status,
                        filled_qty=filled,
                        remaining_qty=max(0.0, qty - filled),
                        created_time=time.time(),
                        last_update_time=time.time(),
                    )
                    # Replace or add without double-incrementing counters here
                    self.active_orders[cid] = state
                    fetched += 1
                except Exception:
                    continue
            # Update orders_active gauges deterministically and portfolio activity
            try:
                counts = {}
                for o in self.active_orders.values():
                    key = (o.symbol, o.side)
                    counts[key] = counts.get(key, 0) + 1
                if self.metrics:
                    for (sym, side), cnt in counts.items():
                        try:
                            self.metrics.orders_active.labels(symbol=sym, side=side).set(int(cnt))
                        except Exception:
                            pass
                syms = {o.symbol for o in self.active_orders.values()} if not symbol else {symbol}
                for s in syms:
                    self._update_portfolio_activity_metrics(s)
            except Exception:
                pass
            return fetched
        except Exception as e:
            print(f"sync_open_orders failed: {e}")
            return fetched

    def save_orders_snapshot(self, path: str) -> bool:
        try:
            import json
            # ensure directory exists
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
            except Exception:
                pass
            tmp = path + '.tmp'
            data = []
            for cid, o in self.active_orders.items():
                data.append({
                    'client_order_id': o.client_order_id,
                    'order_id': o.order_id,
                    'symbol': o.symbol,
                    'side': o.side,
                    'price': o.price,
                    'qty': o.qty,
                    'filled_qty': o.filled_qty,
                    'remaining_qty': o.remaining_qty,
                    'status': o.status,
                    'created_time': o.created_time,
                    'last_update_time': o.last_update_time,
                })
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(sorted(data, key=lambda x: x['client_order_id']), f, sort_keys=True, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"save_orders_snapshot failed: {e}")
            return False

    def load_orders_snapshot(self, path: str) -> int:
        loaded = 0
        try:
            import json
            if not os.path.exists(path):
                return 0
            with open(path, 'r', encoding='utf-8') as f:
                arr = json.load(f) or []
            for item in arr:
                try:
                    cid = str(item.get('client_order_id'))
                    if not cid:
                        continue
                    state = OrderState(
                        order_id=str(item.get('order_id') or ''),
                        client_order_id=cid,
                        symbol=str(item.get('symbol')),
                        side=str(item.get('side')),
                        price=float(item.get('price', 0) or 0),
                        qty=float(item.get('qty', 0) or 0),
                        status=str(item.get('status') or 'New'),
                        filled_qty=float(item.get('filled_qty', 0) or 0),
                        remaining_qty=float(item.get('remaining_qty', 0) or 0),
                        created_time=float(item.get('created_time', time.time())),
                        last_update_time=float(item.get('last_update_time', time.time())),
                    )
                    self.active_orders[cid] = state
                    loaded += 1
                except Exception:
                    continue
            # Update metrics after prefill
            try:
                syms = {o.symbol for o in self.active_orders.values()}
                for s in syms:
                    self._update_portfolio_activity_metrics(s)
            except Exception:
                pass
            return loaded
        except Exception as e:
            print(f"load_orders_snapshot failed: {e}")
            return loaded
    
    def is_risk_paused(self) -> bool:
        """Check if risk management is paused."""
        return self.reconciler.is_risk_paused()
    
    def get_risk_pause_reason(self) -> str:
        """Get reason for risk management pause."""
        return self.reconciler.get_risk_pause_reason()
    
    async def handle_order_update(self, order_data: Dict[str, Any]):
        """Handle order update from WebSocket."""
        client_order_id = order_data.get('orderLinkId')
        if not client_order_id or client_order_id not in self.active_orders:
            return
        
        order = self.active_orders[client_order_id]
        
        # Update order state
        new_status = order_data.get('orderStatus')
        if new_status:
            order.status = new_status
        
        filled_qty = float(order_data.get('cumExecQty', 0))
        if filled_qty != order.filled_qty:
            order.filled_qty = filled_qty
            order.remaining_qty = order.qty - filled_qty
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
        
        order.last_update_time = time.time()
        
        # Remove filled or cancelled orders from active tracking
        if order.status in ['Filled', 'Cancelled', 'Rejected']:
            del self.active_orders[client_order_id]
            self.reconciler.remove_local_order(client_order_id)
            
            # Update metrics
            if self.metrics:
                self.metrics.orders_active.labels(symbol=order.symbol, side=order.side).dec()
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
            try:
                self._update_portfolio_activity_metrics(order.symbol)
            except Exception:
                pass
    
    async def handle_execution_update(self, execution_data: Dict[str, Any]):
        """Handle execution update from WebSocket."""
        client_order_id = execution_data.get('orderLinkId')
        if not client_order_id or client_order_id not in self.active_orders:
            return
        
        order = self.active_orders[client_order_id]
        
        # Update execution details
        exec_qty = float(execution_data.get('execQty', 0))
        exec_price = float(execution_data.get('execPrice', 0))
        
        # Markout: Schedule mid price capture at t+200ms and t+500ms
        if exec_qty > 0 and exec_price > 0 and self.metrics:
            try:
                # Get current mid price (t0)
                mid_t0 = await self._get_current_mid_price(order.symbol)
                if mid_t0:
                    # Schedule markout measurements
                    asyncio.create_task(self._schedule_markout_measurement(
                        order.symbol, order.client_order_id, exec_price, mid_t0
                    ))
            except Exception as e:
                print(f"Failed to schedule markout: {e}")
        
        # This could be used for more detailed execution tracking
        # For now, we rely on order updates for state changes
