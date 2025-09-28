"""
Portfolio allocator with manual, inverse volatility, and risk parity modes.

L1/L2 polish:
- Robust projection to capped simplex [min_weight, max_weight] with exact sum=1 (±1e-9)
- Manual mode: normalize inputs; add new/missing symbols at min_weight (not zero)
- Inverse-vol: 1/max(eps, vol); fallback to last vol or 1.0 if missing
- Risk parity: iterative equalization of w_i * vol_i with guards
- Targets: non-negative target_usd; max_levels >= 1; optional EMA smoothing of targets without drift
"""

import time
import threading
import math
from types import SimpleNamespace
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass
import os
import json as _json

from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.signals.imbalance import ob_imbalance
from src.signals.microprice import micro_tilt
from src.signals.sigma_regime import sigma_band
from src.guards.position_skew import PositionSkewGuard
from src.deploy.thresholds import get_phase_caps
from src.guards.intraday_caps import IntradayCapsGuard
from src.common.fees import expected_tier, distance_to_next_tier, effective_fee_bps, BYBIT_SPOT_TIERS
from src.audit.log import audit_event


@dataclass
class PortfolioTarget:
    """Portfolio target for a symbol."""
    target_usd: float
    max_levels: int


class PortfolioAllocator:
    """Portfolio allocator with multiple allocation modes."""
    
    def __init__(self, ctx: AppContext):
        """Initialize portfolio allocator."""
        self.ctx = ctx
        self.cfg = ctx.cfg.portfolio
        self.metrics: Optional[Metrics] = None
        if hasattr(ctx, 'metrics'):
            self.metrics = ctx.metrics
        
        # State
        self.prev_weights: Dict[str, float] = {}
        self.prev_targets_usd: Dict[str, float] = {}
        self.last_update_ts: float = 0.0
        
        # Constants
        self.eps = 1e-9  # Small epsilon to avoid division by zero
        self.max_iterations = 50
        self.tolerance = 1e-6
        self._last_vol: Dict[str, float] = {}
        # Equity HWM for drawdown-based softening
        self._hwm_equity_usd: float = 0.0
        self._hwm_lock = threading.Lock()
        # L6 cost/slippage: no state beyond metrics
        # Allocator-micro backoff state per symbol
        self._backoff_level: Dict[str, int] = {}
        self._backoff_cooldown: Dict[str, int] = {}
        self._backoff_cooldown_K = 10  # hysteresis ticks
        # Intraday caps last state for audit
        self._caps_last_breached: bool = False

    @staticmethod
    def _fmt6(x: float) -> str:
        try:
            if x != x:
                return "0.000000"
            if x == float("inf") or x == -float("inf"):
                return "0.000000"
        except Exception:
            return "0.000000"
        try:
            s = format(float(x), ".6f")
            return s
        except Exception:
            return "0.000000"
    
    def set_metrics(self, metrics: Metrics):
        """Set metrics exporter for portfolio gauges."""
        self.metrics = metrics
        try:
            self.metrics.set_allocator_hwm_equity_usd(self._hwm_equity_usd)
        except Exception:
            pass
    
    @staticmethod
    def get_default_weight_for_new_symbol(min_weight: float) -> float:
        """Return default weight for a new/missing symbol."""
        return float(min_weight)

    def _round_float(self, x: float, dp: int = 6) -> float:
        try:
            return round(float(x), dp)
        except Exception:
            return float(x)

    def _project_to_capped_simplex(self, raw: Dict[str, float], min_w: float, max_w: float) -> Dict[str, float]:
        """Project raw weights onto the simplex with box constraints [min_w, max_w].

        Uses iterative water-filling to satisfy both per-coordinate clamps and exact sum=1.
        """
        if not raw:
            return {}
        n = len(raw)
        # Handle degenerate single-symbol case: force weight=1.0 (sum invariant dominates)
        if n == 1:
            k = next(iter(raw.keys()))
            return {k: 1.0}
        # Adjust bounds for feasibility if needed
        min_b = float(min_w)
        max_b = float(max_w)
        # If sum of mins exceeds 1, relax mins uniformly
        if n * min_b > 1.0:
            min_b = 1.0 / n
        # If sum of maxes below 1, relax max up to allow feasibility
        if n * max_b < 1.0:
            max_b = 1.0  # allow some weights to absorb slack
        # Start with clamped copy
        w = {k: max(min_b, min(max_b, float(v))) for k, v in raw.items()}
        keys = list(w.keys())
        # Fast path: normalize proportionally then refine
        s = sum(max(0.0, v) for v in w.values())
        if s > 0:
            w = {k: max(min_b, min(max_b, (w[k] / s))) for k in keys}
        else:
            # Distribute equally if all zeros
            n = len(keys)
            eq = 1.0 / n
            w = {k: max(min_b, min(max_b, eq)) for k in keys}

        def _sum_w(d: Dict[str, float]) -> float:
            return sum(d.values())

        # Water-filling to adjust to sum=1 under bounds
        tol = 1e-9
        for _ in range(100):
            total = _sum_w(w)
            if abs(total - 1.0) <= tol:
                break
            if total < 1.0:
                # Distribute deficit equally among non-maxed
                free = [k for k in keys if w[k] < (max_b - tol)]
                if not free:
                    # Cannot increase further; relax to proportional add to all under max_w
                    break
                delta = (1.0 - total) / len(free)
                progressed = False
                for k in free:
                    before = w[k]
                    w[k] = min(max_b, before + delta)
                    if abs(w[k] - before) > 0:
                        progressed = True
                if not progressed:
                    break
            else:
                # Reduce surplus equally among non-minned
                free = [k for k in keys if w[k] > (min_b + tol)]
                if not free:
                    break
                delta = (total - 1.0) / len(free)
                progressed = False
                for k in free:
                    before = w[k]
                    w[k] = max(min_b, before - delta)
                    if abs(w[k] - before) > 0:
                        progressed = True
                if not progressed:
                    break
        # Final normalization (small drift fix) within bounds
        total = _sum_w(w)
        if total > 0:
            # Scale only if it doesn't break bounds too much
            scale = 1.0 / total
            w = {k: max(min_b, min(max_b, v * scale)) for k, v in w.items()}
        return w
    
    def compute_weights(self, stats: Dict[str, Dict[str, float]], mode: Optional[str] = None) -> Dict[str, float]:
        """Compute portfolio weights based on mode (override via arg)."""
        mode_to_use = (mode or self.cfg.mode or "manual").lower()
        if mode_to_use == "manual":
            return self._compute_manual_weights(stats)
        elif mode_to_use == "inverse_vol":
            return self._compute_inverse_vol_weights(stats)
        elif mode_to_use == "risk_parity":
            return self._compute_risk_parity_weights(stats)
        else:
            raise ValueError(f"Unknown allocation mode: {mode_to_use}")
    
    def _compute_manual_weights(self, stats: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Compute weights from manual configuration."""
        cfg = self.cfg
        weights = {str(sym): float(w) for sym, w in (cfg.manual_weights or {}).items()}
        # Add new/missing symbols from stats with min_weight
        for sym in (stats or {}).keys():
            if sym not in weights:
                weights[sym] = self.get_default_weight_for_new_symbol(cfg.min_weight)
        # If still empty, initialize equally at min_weight
        if not weights:
            for sym in (stats or {}).keys():
                weights[sym] = self.get_default_weight_for_new_symbol(cfg.min_weight)
        if not weights:
            return {}
        # Normalize raw
        total = sum(max(0.0, w) for w in weights.values())
        if total <= 0:
            # Fallback equal distribution at min_weight
            n = len(weights)
            eq = 1.0 / n
            weights = {k: eq for k in weights.keys()}
        else:
            weights = {k: max(0.0, v) / total for k, v in weights.items()}
        # Project to [min,max] and sum=1
        weights = self.normalize_and_clamp(weights)
        return weights
    
    def _compute_inverse_vol_weights(self, stats: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Compute weights inversely proportional to volatility."""
        weights = {}
        
        for symbol, symbol_stats in (stats or {}).items():
            vol = symbol_stats.get('vol')
            if vol is None:
                vol = symbol_stats.get('vola')
            if vol is None:
                vol = self._last_vol.get(symbol, 1.0)
            vol = float(vol) if vol is not None else 1.0
            safe_vol = max(self.eps, vol)
            weights[symbol] = 1.0 / safe_vol
            self._last_vol[symbol] = vol
        
        # Project to [min,max] and sum=1
        weights = self.normalize_and_clamp(weights)
        return weights
    
    def _compute_risk_parity_weights(self, stats: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Compute risk parity weights iteratively."""
        symbols = list((stats or {}).keys())
        if not symbols:
            return {}
        
        # Initialize equal weights
        weights = {sym: 1.0 / len(symbols) for sym in symbols}
        
        # Iterative optimization
        for iteration in range(self.max_iterations):
            # Calculate current risk contributions
            risk_contributions = {}
            for symbol in symbols:
                vol_raw = stats[symbol].get('vol')
                if vol_raw is None:
                    vol_raw = stats[symbol].get('vola')
                if vol_raw is None:
                    vol_raw = self._last_vol.get(symbol, 1.0)
                vol = max(self.eps, float(vol_raw))
                self._last_vol[symbol] = vol
                risk_contributions[symbol] = weights[symbol] * vol
            
            # Check convergence
            max_risk = max(risk_contributions.values())
            min_risk = min(risk_contributions.values())
            if max_risk > 0 and (max_risk - min_risk) / max_risk < self.tolerance:
                break
            
            # Update weights to equalize risk contributions
            target_risk = sum(risk_contributions.values()) / len(symbols)
            new_weights = {}
            for symbol in symbols:
                vol = max(self.eps, float(self._last_vol.get(symbol, 1.0)))
                new_weights[symbol] = target_risk / vol
            
            # Project to [min,max] with sum=1
            new_weights = self.normalize_and_clamp(new_weights)
            
            # Update weights
            weights = new_weights
        
        return weights

    def normalize_and_clamp(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Public helper: clamp to [min,max] and ensure exact sum=1 within tolerance."""
        return self._project_to_capped_simplex(weights, self.cfg.min_weight, self.cfg.max_weight)
    
    def _apply_weight_constraints(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Apply min/max weight constraints."""
        constrained_weights = {}
        
        for symbol, weight in weights.items():
            # Clamp to [min_weight, max_weight]
            clamped_weight = max(self.cfg.min_weight, min(weight, self.cfg.max_weight))
            constrained_weights[symbol] = clamped_weight
        
        return constrained_weights
    
    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize weights to sum to 1."""
        total_weight = sum(weights.values())
        if total_weight > 0:
            return {sym: w / total_weight for sym, w in weights.items()}
        return weights
    
    def _apply_ema_smoothing(self, new_weights: Dict[str, float]) -> Dict[str, float]:
        """Apply EMA smoothing to weights."""
        if not self.prev_weights:
            return new_weights
        
        smoothed_weights = {}
        alpha = self.cfg.ema_alpha
        
        for symbol in new_weights:
            prev_weight = self.prev_weights.get(symbol, 0.0)
            new_weight = new_weights[symbol]
            smoothed_weight = alpha * new_weight + (1 - alpha) * prev_weight
            smoothed_weights[symbol] = smoothed_weight
        
        return smoothed_weights
    
    def targets_from_weights(self, weights: Dict[str, float], *, equity_usd: Optional[float] = None,
                             budget_available_usd: Optional[float] = None) -> Dict[str, PortfolioTarget]:
        """Convert weights to portfolio targets with optional budget/PnL softening.

        Backward-compatible: older calls without kwargs behave as before (no softening, avail=budget).
        """
        targets = {}
        # --- L0: Intraday caps guard (hard block) ---
        try:
            state = getattr(self.ctx, 'state', None)
            guard: Optional[IntradayCapsGuard] = getattr(state, 'intraday_caps_guard', None) if state else None
            breached = bool(guard and guard.is_breached())
            if breached and not self._caps_last_breached:
                try:
                    audit_event("GUARD", "-", {"name": "intraday_caps", "event": "block"})
                except Exception:
                    pass
                self._caps_last_breached = True
            if breached:
                # Update metrics and return empty sizing
                if self.metrics and hasattr(self.metrics, 'update_intraday_caps'):
                    try:
                        self.metrics.update_intraday_caps(pnl=guard.cum_pnl, turnover=guard.cum_turnover, vol=guard.cum_vol, breached=True)
                    except Exception:
                        pass
                return {}
            # If previously breached and now recovered
            if (not breached) and self._caps_last_breached:
                try:
                    audit_event("GUARD", "-", {"name": "intraday_caps", "event": "resume"})
                except Exception:
                    pass
                self._caps_last_breached = False
        except Exception:
            pass
        # --- L7.1 Position skew guard (deterministic; no side effects) ---
        # Read limits from cfg if available; default to disabled (0.0)
        try:
            cfg_full = getattr(self.ctx, 'cfg', None)
            guards_cfg = getattr(cfg_full, 'guards', None)
            pos_cfg = getattr(guards_cfg, 'pos_skew', None)
            per_sym_lim = float(getattr(pos_cfg, 'per_symbol_abs_limit', 0.0)) if pos_cfg is not None else 0.0
            per_col_lim = float(getattr(pos_cfg, 'per_color_abs_limit', 0.0)) if pos_cfg is not None else 0.0
        except Exception:
            per_sym_lim = 0.0
            per_col_lim = 0.0
        # Prepare state snapshots (best-effort; default empty)
        try:
            positions_by_symbol = getattr(getattr(self.ctx, 'state', object()), 'positions_by_symbol', None)
            if positions_by_symbol is None:
                positions_by_symbol = getattr(self.ctx, 'positions_by_symbol', {}) or {}
            if not isinstance(positions_by_symbol, dict):
                positions_by_symbol = {}
        except Exception:
            positions_by_symbol = {}
        try:
            color_by_symbol = getattr(getattr(self.ctx, 'state', object()), 'color_by_symbol', None)
            if color_by_symbol is None:
                color_by_symbol = getattr(self.ctx, 'color_by_symbol', {}) or {}
            if not isinstance(color_by_symbol, dict):
                color_by_symbol = {}
        except Exception:
            color_by_symbol = {}
        # Evaluate guard deterministically
        try:
            guard = PositionSkewGuard(per_symbol_abs_limit=per_sym_lim, per_color_abs_limit=per_col_lim)
            decision = guard.evaluate(positions_by_symbol, color_by_symbol)
            freeze_symbols = set(getattr(decision, 'symbol_breach', set()) or set())
            color_breach = bool(getattr(decision, 'color_breach', False))
            bias_sign = int(getattr(decision, 'bias_sign', 0))
        except Exception:
            freeze_symbols = set()
            color_breach = False
            bias_sign = 0
        # Determine biased color (side) deterministically using current positions
        biased_color = None
        if color_breach and per_col_lim >= 0:
            # Aggregate per color totals
            totals = {}
            try:
                # Deterministic accumulation by sorted symbols
                for sym in sorted(positions_by_symbol.keys()):
                    pos = float(positions_by_symbol.get(sym, 0.0))
                    col = str(color_by_symbol.get(sym, 'blue'))
                    totals[col] = float(totals.get(col, 0.0)) + pos
            except Exception:
                totals = {}
            # Select color with largest absolute breach over limit; deterministic tie-breaker by color name
            best = None  # tuple(breach_abs, color_name, total_pos)
            for col in sorted(totals.keys()):
                total_pos = float(totals.get(col, 0.0))
                breach_abs = abs(total_pos) - float(per_col_lim)
                if breach_abs > 0:
                    cand = (breach_abs, col, total_pos)
                    if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1] < best[1]):
                        best = cand
            if best is not None:
                # Ensure bias direction reduces existing skew
                total_pos = best[2]
                if (total_pos > 0 and bias_sign <= 0) or (total_pos < 0 and bias_sign >= 0) or (total_pos == 0 and bias_sign == 0):
                    biased_color = best[1]
                else:
                    # If sign suggests opposite, still bias this color (always reduce magnitude)
                    biased_color = best[1]
        # Compute bias ratio with cap from cfg if available
        try:
            bias_cap = float(getattr(getattr(getattr(getattr(self.ctx, 'cfg', None), 'allocator', None), 'smoothing', None), 'bias_cap', 0.10) or 0.10)
        except Exception:
            bias_cap = 0.10
        # Local float clamp to avoid Decimal mixing
        def _clampf(x: float, lo: float, hi: float) -> float:
            if x < lo:
                return lo
            if x > hi:
                return hi
            return x
        bias_ratio = 0.0
        if color_breach and biased_color is not None and bias_sign != 0:
            bias_ratio = _clampf(0.05 * float(bias_sign), -float(bias_cap), float(bias_cap))
        # Compute drawdown and softening factor (fixed-point internally)
        drawdown_pct = 0.0
        if equity_usd is not None:
            try:
                eq = float(equity_usd)
                with self._hwm_lock:
                    if eq > self._hwm_equity_usd:
                        self._hwm_equity_usd = eq
                        if self.metrics:
                            try:
                                self.metrics.set_allocator_hwm_equity_usd(self._hwm_equity_usd)
                            except Exception:
                                pass
                    hwm = self._hwm_equity_usd
                if hwm > 0:
                    drawdown_pct = max(0.0, min(1.0, (hwm - eq) / hwm))
            except Exception:
                drawdown_pct = 0.0
        # Fixed-point: drawdown_bps (0..10000), soft_factor_permille (0..1000)
        try:
            drawdown_bps = int(max(0.0, min(1.0, float(drawdown_pct))) * 10000.0)
        except Exception:
            drawdown_bps = 0
        soft_cap = float(getattr(self.cfg.budget, 'drawdown_soft_cap', 0.0)) if hasattr(self.cfg, 'budget') else 0.0
        pnl_sens = float(getattr(self.cfg.budget, 'pnl_sensitivity', 0.0)) if hasattr(self.cfg, 'budget') else 0.0
        try:
            soft_cap_bps = int(max(0.0, min(1.0, float(soft_cap))) * 10000.0)
        except Exception:
            soft_cap_bps = 0
        try:
            pnl_sens_permille = int(max(0.0, min(1.0, float(pnl_sens))) * 1000.0)
        except Exception:
            pnl_sens_permille = 0
        if soft_cap_bps > 0:
            x_permille = min(1000, (drawdown_bps * 1000) // soft_cap_bps)
        else:
            # cap<=0: instantly apply max softening as soon as there is any drawdown
            x_permille = 1000 if drawdown_bps > 0 else 0
        # soft = 1 - (pnl_sens * x)
        soft_permille = 1000 - ((pnl_sens_permille * x_permille) // 1000)
        if soft_permille < 0:
            soft_permille = 0
        if soft_permille > 1000:
            soft_permille = 1000
        # Available budget
        budget_total = float(self.cfg.budget_usd)
        avail = float(budget_available_usd) if budget_available_usd is not None else budget_total
        # Update metrics
        if self.metrics:
            try:
                self.metrics.set_portfolio_budget_available_usd(avail)
                # export drawdown as float percent again
                self.metrics.set_portfolio_drawdown_pct(float(drawdown_bps) / 10000.0)
                self.metrics.set_allocator_soft_factor(float(soft_permille) / 1000.0)
            except Exception:
                pass
            # L7: Turnover-aware sizing (after L6.4)
            try:
                cfg_cost = getattr(self.cfg, 'cost', None)
                per = getattr(cfg_cost, 'per_symbol', {}) or {}
                ov = per.get(str(symbol), {}) if isinstance(per, dict) else {}
                floor_to = float(ov.get('turnover_floor', getattr(cfg_cost, 'turnover_floor', 0.0)))
                sens_to = float(ov.get('turnover_sensitivity', getattr(cfg_cost, 'turnover_sensitivity', 0.0)))
                if floor_to < 0.0:
                    floor_to = 0.0
                if floor_to > 1.0:
                    floor_to = 1.0
                if sens_to < 0.0:
                    sens_to = 0.0
                if sens_to > 1.0:
                    sens_to = 1.0
                # read turnover ewma from metrics
                turn_usd = 0.0
                if self.metrics and hasattr(self.metrics, 'get_turnover_snapshot_for_tests'):
                    try:
                        snap_to = self.metrics.get_turnover_snapshot_for_tests()  # type: ignore[attr-defined]
                        turn_usd = float((snap_to.get('usd', {}) or {}).get(str(symbol), 0.0))
                    except Exception:
                        turn_usd = 0.0
                # budget per symbol: use avail*weight as proxy, >=1.0 guard
                denom = max(1.0, float(avail) * float(weight))
                r = float(turn_usd) / float(denom)
                if r < 0.0:
                    r = 0.0
                # raw in [0,1] as 1 - r (clamp)
                raw = 1.0 - r
                if raw < 0.0:
                    raw = 0.0
                if raw > 1.0:
                    raw = 1.0
                turnover_factor = max(floor_to, 1.0 - sens_to * (1.0 - raw))
                if turnover_factor < floor_to:
                    turnover_factor = floor_to
                if turnover_factor > 1.0:
                    turnover_factor = 1.0
                t = t * turnover_factor
                if self.metrics and hasattr(self.metrics, 'allocator_turnover_factor'):
                    try:
                        self.metrics.allocator_turnover_factor.labels(symbol=str(symbol)).set(float(turnover_factor))  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
        # Deterministic iteration by symbol name
        min_guard = float(getattr(self.cfg.budget, 'budget_min_usd', 0.0)) if hasattr(self.cfg, 'budget') else 0.0
        ordered = sorted(weights.keys())
        for symbol in ordered:
            weight = float(weights[symbol])
            base = max(0.0, budget_total * weight)
            cap_by_avail = min(base, avail * weight)
            t = cap_by_avail * (float(soft_permille) / 1000.0)
            # L6.1/L6.2: cost/slippage attenuation
            try:
                cost_bps = self._estimate_cost_bps(symbol, t)
                sens = float(getattr(self.cfg.cost, 'cost_sensitivity', 0.5))
                # attenuation = 1 - sens * min(1, cost_bps/100)
                ratio = 0.0 if cost_bps <= 0 else (float(cost_bps) / 100.0)
                if ratio > 1.0:
                    ratio = 1.0
                atten = 1.0 - sens * ratio
                if atten < 0.0:
                    atten = 0.0
                if atten > 1.0:
                    atten = 1.0
                t = t * atten
                if self.metrics:
                    try:
                        self.metrics.set_allocator_cost(symbol, float(cost_bps), float(atten))
                    except Exception:
                        pass
            except Exception:
                pass
            # L6.3: fill-rate attenuation (after L6 cost attenuation, before final clamp)
            try:
                # get r from metrics snapshot; fallback 1.0
                r = 1.0
                if self.metrics and hasattr(self.metrics, 'get_cost_fillrate_snapshot_for_tests'):
                    snap_fr = self.metrics.get_cost_fillrate_snapshot_for_tests()  # type: ignore[attr-defined]
                    r = float((snap_fr.get('r', {}) or {}).get(str(symbol), 1.0))
                    if r < 0.0:
                        r = 0.0
                    if r > 1.0:
                        r = 1.0
                cfg_cost = getattr(self.cfg, 'cost', None)
                per = getattr(cfg_cost, 'per_symbol', {}) or {}
                ov = per.get(str(symbol), {}) if isinstance(per, dict) else {}
                floor = float(ov.get('fill_rate_floor', getattr(cfg_cost, 'fill_rate_floor', 0.7)))
                sens_fr = float(ov.get('fill_rate_sensitivity', getattr(cfg_cost, 'fill_rate_sensitivity', 0.5)))
                d = max(0.0, float(floor) - float(r))
                attenuation_fill = 1.0 - sens_fr * d
                if attenuation_fill < 0.0:
                    attenuation_fill = 0.0
                if attenuation_fill > 1.0:
                    attenuation_fill = 1.0
                t = t * attenuation_fill
                # publish gauge for visibility
                if self.metrics and hasattr(self.metrics, 'allocator_cost_attenuation'):
                    try:
                        # reuse cost attenuation gauge semantics is not ideal; expose via separate gauge if available
                        if hasattr(self.metrics, 'allocator_fillrate_attenuation'):
                            self.metrics.allocator_fillrate_attenuation.labels(symbol=str(symbol)).set(float(attenuation_fill))  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            # L6.4: Liquidity-aware sizing (after fill-rate)
            try:
                cfg_cost = getattr(self.cfg, 'cost', None)
                per = getattr(cfg_cost, 'per_symbol', {}) or {}
                ov = per.get(str(symbol), {}) if isinstance(per, dict) else {}
                depth_target = float(ov.get('liquidity_depth_usd_target', getattr(cfg_cost, 'liquidity_depth_usd_target', 0.0)))
                sens_liq = float(ov.get('liquidity_sensitivity', getattr(cfg_cost, 'liquidity_sensitivity', 0.0)))
                floor_liq = float(ov.get('liquidity_min_floor', getattr(cfg_cost, 'liquidity_min_floor', 0.0)))
                if floor_liq < 0.0:
                    floor_liq = 0.0
                if floor_liq > 1.0:
                    floor_liq = 1.0
                if sens_liq < 0.0:
                    sens_liq = 0.0
                if sens_liq > 1.0:
                    sens_liq = 1.0
                # Read depth snapshot; fallback 0.0
                depth_usd = 0.0
                if self.metrics and hasattr(self.metrics, 'get_liquidity_snapshot_for_tests'):
                    try:
                        snap_liq = self.metrics.get_liquidity_snapshot_for_tests()  # type: ignore[attr-defined]
                        depth_usd = float((snap_liq or {}).get(str(symbol), 0.0))
                    except Exception:
                        depth_usd = 0.0
                raw = 1.0
                if depth_target > 0.0:
                    raw = min(1.0, max(0.0, depth_usd / depth_target))
                liquidity_factor = max(floor_liq, raw)
                attenuation_liq = 1.0 - sens_liq * (1.0 - liquidity_factor)
                if attenuation_liq < floor_liq:
                    attenuation_liq = floor_liq
                if attenuation_liq > 1.0:
                    attenuation_liq = 1.0
                t = t * attenuation_liq
                if self.metrics and hasattr(self.metrics, 'allocator_liquidity_factor'):
                    try:
                        self.metrics.allocator_liquidity_factor.labels(symbol=str(symbol)).set(float(attenuation_liq))  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            # L7.1: PositionSkewGuard effects
            try:
                # Freeze symbols
                if symbol in freeze_symbols:
                    t = 0.0
                else:
                    # Apply color bias reduction on biased side only
                    if biased_color is not None and bias_ratio != 0.0:
                        sym_color = str(color_by_symbol.get(symbol, 'blue'))
                        if sym_color == biased_color:
                            # Reduce magnitude deterministically
                            t = float(t) * (1.0 - abs(float(bias_ratio)))
            except Exception:
                pass
            if t < min_guard:
                t = 0.0
            # --- ALLOCATOR_MICRO: per-tick clamp with backoff ---
            try:
                # desired in base units proxy: USD target (no price data here), use USD directly
                desired = float(t)
                current = float(self.prev_targets_usd.get(symbol, 0.0))
                delta_raw = float(desired - current)
                # --- MICRO_SIGNALS: bias with impact cap before clamp ---
                try:
                    cfg_full = getattr(self.ctx, 'cfg', SimpleNamespace())
                    sigcfg = getattr(cfg_full, 'signals', SimpleNamespace())
                    w = getattr(sigcfg, 'weights', SimpleNamespace())
                    impact_cap = float(getattr(sigcfg, 'impact_cap_ratio', 0.10))
                    if impact_cap < 0.0:
                        impact_cap = 0.0
                    if impact_cap > 1.0:
                        impact_cap = 1.0
                    # read micro inputs if available via metrics/state; fallback zeros
                    bid = float(getattr(getattr(self.ctx, 'state', SimpleNamespace()), 'last_bid', 0.0))
                    ask = float(getattr(getattr(self.ctx, 'state', SimpleNamespace()), 'last_ask', 0.0))
                    bq = float(getattr(getattr(self.ctx, 'state', SimpleNamespace()), 'last_bid_qty', 0.0))
                    aq = float(getattr(getattr(self.ctx, 'state', SimpleNamespace()), 'last_ask_qty', 0.0))
                    sigma = float(getattr(getattr(self.ctx, 'state', SimpleNamespace()), 'last_sigma', 0.0))
                    s_imb = ob_imbalance(bq, aq)
                    s_tilt = micro_tilt(bid, ask, bq, aq)
                    bands = list(getattr(sigcfg, 'sigma_bands', []))
                    regime = sigma_band(sigma, bands)
                    rbm = getattr(sigcfg, 'regime_bias_map', {}) or {}
                    s_reg = float({"-1": -1.0, "0": 0.0, "1": 1.0}.get(str(rbm.get(str(regime), rbm.get(regime, 0))), 0.0))
                    w_imb = float(getattr(w, 'imbalance', 0.0))
                    w_tilt = float(getattr(w, 'micro_tilt', 0.0))
                    w_reg = float(getattr(w, 'sigma_regime', 0.0))
                    micro_bias = w_imb * s_imb + w_tilt * s_tilt + w_reg * s_reg
                    if micro_bias < -1.0:
                        micro_bias = -1.0
                    if micro_bias > 1.0:
                        micro_bias = 1.0
                    max_bias_impact = abs(delta_raw) * impact_cap
                    bias_adjust = micro_bias * abs(delta_raw)
                    if bias_adjust < -max_bias_impact:
                        bias_adjust = -max_bias_impact
                    if bias_adjust > max_bias_impact:
                        bias_adjust = max_bias_impact
                    desired = float(desired + bias_adjust)
                    # metric: micro_bias_strength
                    if self.metrics and hasattr(self.metrics, 'set_micro_bias_strength'):
                        denom = max(1e-9, abs(delta_raw))
                        try:
                            self.metrics.set_micro_bias_strength(symbol=str(symbol), v=float(abs(bias_adjust) / denom))
                        except Exception:
                            pass
                except Exception:
                    pass
                # read smoothing params
                smooth = getattr(getattr(self.ctx, 'cfg', SimpleNamespace()), 'allocator', SimpleNamespace())
                smooth = getattr(smooth, 'smoothing', SimpleNamespace())
                max_delta_ratio = float(getattr(smooth, 'max_delta_ratio', 0.15))
                max_delta_abs_base_units = float(getattr(smooth, 'max_delta_abs_base_units', 0.0))
                steps = list(getattr(smooth, 'backoff_steps', [1.0, 0.7, 0.5]))
                if not steps:
                    steps = [1.0]
                # compute caps
                cap_rel = abs(current) * max(0.0, max_delta_ratio)
                cap_abs = max(0.0, max_delta_abs_base_units)
                cap_base = max(cap_rel, cap_abs)
                # manage backoff level by breach signal (decision)
                lvl = int(self._backoff_level.get(symbol, 0))
                if symbol in freeze_symbols or color_breach:
                    lvl = min(lvl + 1, len(steps) - 1)
                    self._backoff_cooldown[symbol] = self._backoff_cooldown_K
                else:
                    # hysteresis: reduce at most once per K ticks
                    k = int(self._backoff_cooldown.get(symbol, 0))
                    if k > 0:
                        self._backoff_cooldown[symbol] = k - 1
                    else:
                        if lvl > 0:
                            lvl -= 1
                            self._backoff_cooldown[symbol] = self._backoff_cooldown_K
                self._backoff_level[symbol] = lvl
                m = float(steps[lvl])
                cap = cap_base * m
                # clamp
                if cap <= 0.0:
                    delta_capped = 0.0
                else:
                    if delta_raw < -cap:
                        delta_capped = -cap
                    elif delta_raw > cap:
                        delta_capped = cap
                    else:
                        delta_capped = delta_raw
                nxt = current + delta_capped
                # Respect fee/bias caps already applied; clamp not to exceed desired overshoot beyond tilt
                # For determinism, do not modify desired here, only cap delta
                t = max(0.0, float(nxt))
                # metrics
                if self.metrics:
                    try:
                        self.metrics.allocator_backoff_level.labels(symbol=str(symbol)).set(float(lvl))
                        self.metrics.allocator_delta_capped_total.labels(symbol=str(symbol)).inc(abs(float(delta_capped)))
                        denom = abs(current)
                        if denom < 1.0:
                            denom = 1.0
                        self.metrics.allocator_sizing_delta_ratio.labels(symbol=str(symbol)).set(abs(float(delta_capped)) / float(denom))
                    except Exception:
                        pass
                # ASCII log line (tab-friendly) and audit on clamp/backoff change
                try:
                    f = self._fmt6
                    line = f"ALLOC_MICRO ts={int(time.time())} symbol={symbol} current={f(current)} desired={f(desired)} delta_raw={f(delta_raw)} cap={f(cap)} backoff_level={lvl} delta_capped={f(delta_capped)} next={f(nxt)}"
                    print(line)
                    # Emit audit event when clamp applied or backoff level changes
                    if delta_capped != 0.0 or lvl != int(self._backoff_level.get(symbol, lvl)):
                        audit_event("ALLOC", str(symbol), {
                            "delta_raw": float(self._round_float(delta_raw, 6)),
                            "cap": float(self._round_float(cap, 6)),
                            "delta_capped": float(self._round_float(delta_capped, 6)),
                            "backoff_level": int(lvl),
                            "next": float(self._round_float(nxt, 6)),
                        })
                except Exception:
                    pass
            except Exception:
                pass
            # max levels from weight as before
            weight_ratio = weight / self.cfg.max_weight
            max_levels = round(self.cfg.levels_per_side_max * weight_ratio)
            max_levels = max(self.cfg.levels_per_side_min,
                             min(max_levels, self.cfg.levels_per_side_max))
            targets[symbol] = PortfolioTarget(
                target_usd=self._round_float(t),
                max_levels=max_levels
            )
        
        # L7.2: Record position skew breach and export artifacts
        try:
            # Only record and export if there's a breach
            if decision.symbol_breach or decision.color_breach:
                if self.metrics and hasattr(self.metrics, 'record_position_skew_breach'):
                    self.metrics.record_position_skew_breach(decision.symbol_breach, decision.color_breach)
                
                # Export artifacts snapshot
                try:
                    from src.common.artifacts import export_registry_snapshot
                    
                    if self.metrics and hasattr(self.metrics, 'build_position_skew_artifacts_payload'):
                        payload = self.metrics.build_position_skew_artifacts_payload(positions_by_symbol, decision)
                        export_registry_snapshot("artifacts/metrics.json", {"position_skew": payload})
                except Exception:
                    pass
        except Exception:
            pass
        
        # L7.3: Gentle VIP fee-aware tilt (after pos-skew/caps, before final clamp)
        fee_tilt_applied = False
        try:
            cfg_fees = getattr(getattr(self.ctx, 'cfg', None), 'fees', None)
            bybit = getattr(cfg_fees, 'bybit', None) if cfg_fees else None
            smooth = getattr(getattr(getattr(self.ctx, 'cfg', None), 'allocator', None), 'smoothing', None)
            fee_bias_cap = float(getattr(smooth, 'fee_bias_cap', 0.05) or 0.0)
            if fee_bias_cap < 0.0:
                fee_bias_cap = 0.0
            if fee_bias_cap > 0.10:
                fee_bias_cap = 0.10
            if bybit and fee_bias_cap > 0.0:
                # Rolling 30d turnover (best-effort)
                rolling_30d_usd = 0.0
                if self.metrics and hasattr(self.metrics, 'get_turnover_total_ewma_usd'):
                    try:
                        rolling_30d_usd = float(self.metrics.get_turnover_total_ewma_usd())  # type: ignore[attr-defined]
                    except Exception:
                        rolling_30d_usd = 0.0
                tier_now = expected_tier(rolling_30d_usd)
                dist = distance_to_next_tier(rolling_30d_usd)
                # Current maker/taker share (fallback to 80/20 if not available)
                maker_share = 0.8
                taker_share = 0.2
                eff_now = float(effective_fee_bps(maker_share, taker_share, tier_now))
                # Next tier if exists
                try:
                    idx = 0
                    for i, t in enumerate(BYBIT_SPOT_TIERS):
                        if int(t.level) == int(tier_now.level):
                            idx = i
                            break
                    tier_next = BYBIT_SPOT_TIERS[idx + 1] if idx + 1 < len(BYBIT_SPOT_TIERS) else None
                except Exception:
                    tier_next = None
                if tier_next is not None:
                    eff_next = float(effective_fee_bps(maker_share, taker_share, tier_next))
                    improvement = float(eff_now - eff_next)
                    thr_dist = float(getattr(bybit, 'distance_usd_threshold', 25000.0) or 0.0)
                    thr_impr = float(getattr(bybit, 'min_improvement_bps', 0.2) or 0.0)
                    if dist <= thr_dist and improvement >= thr_impr:
                        # Small fraction of benefit, bounded by cap (up-scale)
                        tilt = min(fee_bias_cap, max(0.0, improvement) * 0.02)
                        # Cap tilt by remaining headroom to avoid later downscale
                        try:
                            avail_soft_local = float(avail) * (float(soft_permille) / 1000.0)
                        except Exception:
                            avail_soft_local = 0.0
                        total_before = sum(float(targets[s].target_usd) for s in ordered)
                        if total_before > 0.0 and avail_soft_local > 0.0:
                            headroom_ratio = (avail_soft_local / total_before) - 1.0
                            if headroom_ratio < 0.0:
                                headroom_ratio = 0.0
                            if tilt > headroom_ratio:
                                tilt = headroom_ratio
                        if tilt > 0.0:
                            # Apply global up-scale deterministically after skew/caps
                            for s in sorted(ordered):
                                cur = float(targets[s].target_usd)
                                newv = cur * (1.0 + float(tilt))
                                if cur != 0.0:
                                    max_up = cur * (1.0 + fee_bias_cap)
                                    if newv > max_up:
                                        newv = max_up
                                targets[s] = PortfolioTarget(target_usd=self._round_float(newv, 6), max_levels=targets[s].max_levels)
                            fee_tilt_applied = True
        except Exception:
            pass

        # Final deterministic clamp to ensure sum(targets) <= avail * soft
        try:
            avail_soft = float(avail) * (float(soft_permille) / 1000.0)
            total = sum(float(targets[s].target_usd) for s in ordered)
            # Clip tiny floating noise
            total = self._round_float(total, 6)
            avail_soft = self._round_float(avail_soft, 6)
            if total > avail_soft + 1e-9:
                excess = total - avail_soft
                # reduce from the last symbol backwards deterministically
                for s in reversed(ordered):
                    cur = float(targets[s].target_usd)
                    take = min(cur, excess)
                    newv = max(0.0, cur - take)
                    targets[s] = PortfolioTarget(target_usd=self._round_float(newv, 6), max_levels=targets[s].max_levels)
                    excess = self._round_float(excess - take, 6)
                    if excess <= 0:
                        break
        except Exception:
            pass
        # Re-apply min_guard after clamp to zero-out dust
        try:
            for s in ordered:
                if float(targets[s].target_usd) < min_guard:
                    targets[s] = PortfolioTarget(target_usd=0.0, max_levels=targets[s].max_levels)
        except Exception:
            pass
        return targets

    # --- L6: cost/slippage model ---
    def _estimate_cost_bps(self, symbol: str, target_usd: float) -> float:
        try:
            cfg = getattr(self.cfg, 'cost', None)
            if not cfg:
                return 0.0
            per = getattr(cfg, 'per_symbol', {}) or {}
            ov = per.get(str(symbol), {}) if isinstance(per, dict) else {}
            fee_bps = float(ov.get('fee_bps', ov.get('fee_bps_default', getattr(cfg, 'fee_bps_default', 1.0))))
            # Allow override keys exactly per plan
            if 'fee_bps' not in ov:
                fee_bps = float(getattr(cfg, 'fee_bps_default', 1.0))
            base = float(ov.get('slippage_bps_base', getattr(cfg, 'slippage_bps_base', 0.5)))
            k = float(ov.get('slippage_k_bps_per_kusd', getattr(cfg, 'slippage_k_bps_per_kusd', 0.1)))
            usd = 0.0 if target_usd is None else max(0.0, float(target_usd))
            # Dynamic inputs from shadow/metrics
            use_spread = bool(ov.get('use_shadow_spread', getattr(cfg, 'use_shadow_spread', True)))
            use_volume = bool(ov.get('use_shadow_volume', getattr(cfg, 'use_shadow_volume', True)))
            min_vol = float(ov.get('min_volume_usd', getattr(cfg, 'min_volume_usd', 1000.0)))
            cap_slippage = float(ov.get('max_slippage_bps_cap', getattr(cfg, 'max_slippage_bps_cap', 50.0)))
            # L6.2: prefer calibrated effective params if available
            if self.metrics:
                try:
                    k_eff_cal = self.metrics._get_calibrated_k_eff(symbol)  # type: ignore[attr-defined]
                except Exception:
                    k_eff_cal = None
                try:
                    cap_eff_cal = self.metrics._get_calibrated_cap_eff_bps(symbol)  # type: ignore[attr-defined]
                except Exception:
                    cap_eff_cal = None
                if k_eff_cal is not None:
                    k = float(max(0.0, k_eff_cal))
                if cap_eff_cal is not None:
                    cap_slippage = float(max(0.0, cap_eff_cal))
            spread_bps, volume_usd, valid_spread, valid_volume = self._estimate_market_inputs(symbol)
            slippage_bps = base
            if use_spread and valid_spread:
                # in markets, half-spread as lower bound for slippage
                slippage_bps = max(slippage_bps, float(spread_bps) / 2.0)
            # k growth by target size
            k_eff = float(k)
            if use_volume and (not valid_volume or float(volume_usd) < float(min_vol)):
                k_eff = float(k) * 2.0
            slippage_bps = slippage_bps + k_eff * (usd / 1000.0)
            # cap
            if slippage_bps > cap_slippage:
                slippage_bps = cap_slippage
            # Export inputs metrics if available
            if self.metrics:
                try:
                    self.metrics.set_allocator_cost_inputs(symbol, spread_bps=spread_bps, volume_usd=volume_usd, slippage_bps=slippage_bps)
                except Exception:
                    pass
            if slippage_bps < 0.0:
                slippage_bps = 0.0
            cost_bps = float(fee_bps) + float(slippage_bps)
            if cost_bps < 0.0:
                cost_bps = 0.0
            return float(cost_bps)
        except Exception:
            return 0.0

    def _estimate_market_inputs(self, symbol: str) -> tuple[float, float, bool, bool]:
        # Inputs from metrics/shadow snapshots if available, else fallback
        spread_bps = 0.0
        volume_usd = 0.0
        valid_spread = False
        valid_volume = False
        try:
            m = getattr(self, 'metrics', None)
            if not m:
                return spread_bps, volume_usd, valid_spread, valid_volume
            # Use shadow averages as proxy for spread; we don't have direct spread here, fallback to 2*avg_price_diff_bps
            # We cannot read labels back easily; rely on last snapshot hook if exists
            snap = None
            try:
                if hasattr(m, '_get_allocator_cost_snapshot_for_tests'):
                    snap = m._get_allocator_cost_snapshot_for_tests()
            except Exception:
                snap = None
            if snap and isinstance(snap, dict):
                spd = (snap.get('spread_bps', {}) or {}).get(str(symbol))
                vol = (snap.get('volume_usd', {}) or {}).get(str(symbol))
                if spd is not None:
                    spread_bps = float(max(0.0, float(spd)))
                    valid_spread = True
                if vol is not None:
                    volume_usd = float(max(0.0, float(vol)))
                    valid_volume = True
        except Exception:
            pass
        return float(spread_bps), float(volume_usd), bool(valid_spread), bool(valid_volume)

    # --- Snapshotting ---
    def to_snapshot(self) -> dict:
        try:
            with self._hwm_lock:
                v = float(max(0.0, self._hwm_equity_usd))
            return {"version": 1, "hwm_equity_usd": v}
        except Exception:
            return {"version": 1, "hwm_equity_usd": 0.0}

    def load_snapshot(self, d: dict) -> None:
        try:
            if not isinstance(d, dict):
                return
            v = d.get("hwm_equity_usd", 0.0)
            try:
                v = float(v)
            except Exception:
                v = 0.0
            if v < 0:
                v = 0.0
            with self._hwm_lock:
                self._hwm_equity_usd = v
            if self.metrics:
                try:
                    self.metrics.set_allocator_hwm_equity_usd(self._hwm_equity_usd)
                except Exception:
                    pass
        except Exception:
            pass

    def get_hwm_equity_usd(self) -> float:
        with self._hwm_lock:
            return float(self._hwm_equity_usd)

    # Safe load from path with size guard
    def safe_load_snapshot(self, path: str) -> None:
        try:
            m = getattr(self.ctx, 'metrics', None)
            import time as _t
            if not path or not os.path.exists(path):
                if m:
                    m.inc_allocator_snapshot_load(ok=False, ts=_t.time())
                raise FileNotFoundError("snapshot_not_found")
            if os.path.getsize(path) > 1_048_576:
                if m:
                    m.inc_allocator_snapshot_load(ok=False, ts=_t.time())
                raise ValueError("snapshot_too_large")
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            self.load_snapshot(data)
            if m:
                m.inc_allocator_snapshot_load(ok=True, ts=_t.time())
        except Exception:
            raise
    
    def update(self, ctx: AppContext, stats: Dict[str, Dict[str, float]]) -> Dict[str, PortfolioTarget]:
        """Update portfolio allocation and return targets."""
        # Compute new weights
        new_weights = self.compute_weights(stats)
        
        # Apply EMA smoothing
        smoothed_weights = self._apply_ema_smoothing(new_weights)
        
        # Convert to targets
        targets = self.targets_from_weights(smoothed_weights)
        # Optional EMA smoothing of targets without drift
        if self.prev_targets_usd:
            alpha = self.cfg.ema_alpha
            smoothed = {}
            # Smooth only USD amounts; keep levels deterministic from weights
            for sym, tgt in targets.items():
                prev = float(self.prev_targets_usd.get(sym, tgt.target_usd))
                cur = float(tgt.target_usd)
                smoothed_usd = alpha * cur + (1.0 - alpha) * prev
                smoothed[sym] = smoothed_usd
            # Re-scale to maintain exact budget (no drift)
            total = sum(smoothed.values())
            if total > 0:
                scale = float(self.cfg.budget_usd) / total
            else:
                scale = 1.0
            for sym, tgt in targets.items():
                usd = self._round_float(max(0.0, smoothed.get(sym, tgt.target_usd) * scale))
                targets[sym] = PortfolioTarget(target_usd=usd, max_levels=tgt.max_levels)
        # Update prev targets
        self.prev_targets_usd = {sym: tgt.target_usd for sym, tgt in targets.items()}
        
        # Update state
        self.prev_weights = smoothed_weights.copy()
        self.last_update_ts = time.time()
        
        # Update metrics
        if self.metrics:
            self._update_metrics(smoothed_weights, targets)
        
        return targets
    
    def _update_metrics(self, weights: Dict[str, float], targets: Dict[str, PortfolioTarget]):
        """Update portfolio metrics."""
        for symbol, weight in weights.items():
            target = targets[symbol]
            
            # Portfolio weight
            self.metrics.portfolio_weight.labels(symbol=symbol).set(weight)
            
            # Portfolio target USD
            self.metrics.portfolio_target_usd.labels(symbol=symbol).set(target.target_usd)
            
            # Portfolio active USD (estimate from open orders)
            active_usd = self._estimate_active_usd(symbol)
            self.metrics.portfolio_active_usd.labels(symbol=symbol).set(active_usd)
        
        # Allocator last update timestamp
        self.metrics.allocator_last_update_ts.set(self.last_update_ts)
    
    def _estimate_active_usd(self, symbol: str) -> float:
        """Estimate active USD from open orders."""
        if not hasattr(self.ctx, 'order_manager') or not self.ctx.order_manager:
            return 0.0
        
        # This is a rough estimate - in practice you'd want to track actual order values
        active_orders = getattr(self.ctx.order_manager, 'active_orders', {})
        active_usd = 0.0
        
        for order_id, order_state in active_orders.items():
            if order_state.symbol == symbol:
                # Rough estimate: price * remaining_qty
                active_usd += order_state.price * order_state.remaining_qty
        
        return active_usd
    
    def get_current_weights(self) -> Dict[str, float]:
        """Get current portfolio weights."""
        return self.prev_weights.copy()
    
    def get_last_update_time(self) -> float:
        """Get last update timestamp."""
        return self.last_update_ts


def enforce_phase_caps(phase: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Return clamp values for allocator/orchestrator based on phase caps.

    metrics may include current taker_ratio estimate (optional).
    """
    caps = get_phase_caps(phase)
    allowed_share = float(caps.get("order_share_ratio", 0.0))
    allowed_capital = int(caps.get("capital_usd", 0))
    taker_ceiling = float(caps.get("taker_ceiling_ratio", 0.15))
    now = int(datetime.now(timezone.utc).timestamp())
    print(f"event=phase_caps phase={phase} allowed_share={allowed_share:.6f} allowed_capital_usd={allowed_capital} taker_ceiling={taker_ceiling:.6f} now={now}")
    return {"share": allowed_share, "capital_usd": allowed_capital, "taker_ceiling": taker_ceiling}
