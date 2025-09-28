from __future__ import annotations

from typing import Dict, Deque, Tuple, Optional
from collections import deque

from src.common.config import RuntimeGuardConfig


REASON_HIGH_CANCEL = 1
REASON_HIGH_ERRORS = 2
REASON_NEGATIVE_PNL = 4
REASON_INVENTORY = 1 << 3
REASON_LATENCY   = 1 << 4
REASON_WS_LAG    = 1 << 5
REASON_REJECTS   = 1 << 6
REASON_MANUAL    = 1 << 7


class RuntimeGuard:
    def __init__(self, cfg: RuntimeGuardConfig) -> None:
        self.cfg: RuntimeGuardConfig = cfg or RuntimeGuardConfig()
        self.paused: bool = False
        self.last_change_ts: float = 0.0
        self.breach_streak: int = 0
        self.pauses_total: int = 0
        self.last_reason_mask: int = 0
        # Sliding window and counters
        self._send_events: Deque[Tuple[float, Optional[str], bool]] = deque()
        self._seen_cids: Dict[str, float] = {}
        self._cancel_latencies: Deque[Tuple[float, float]] = deque()
        self._ws_lag_ms: float = 0.0
        self._ws_lag_ts: float = 0.0
        self._inventory_snapshot: Dict[str, float] = {}
        self._budget_usd: float = 0.0
        self._consec_bad: int = 0
        self._consec_good: int = 0

    def to_snapshot(self) -> Dict[str, float]:
        try:
            dry_run = bool(getattr(self.cfg, 'dry_run', False))
        except Exception:
            dry_run = False
        try:
            manual = bool(getattr(self.cfg, 'manual_override_pause', False))
        except Exception:
            manual = False
        effective = bool(manual or (self.paused and not dry_run))
        return {
            "paused": bool(self.paused),
            "paused_effective": 1 if effective else 0,
            "last_reason_bits": int(getattr(self, 'last_reason_mask', 0)),
            "last_change_ts": float(getattr(self, 'last_change_ts', 0.0)),
            "hysteresis_bad": int(getattr(self.cfg, 'hysteresis_bad_required', getattr(self.cfg, 'consecutive_breaches_to_pause', 2))),
            "hysteresis_good": int(getattr(self.cfg, 'hysteresis_good_required', 1)),
            "consec_bad": int(getattr(self, '_consec_bad', 0)),
            "consec_good": int(getattr(self, '_consec_good', 0)),
            "dry_run": 1 if dry_run else 0,
            "manual_override_pause": 1 if manual else 0,
        }

    def load_snapshot(self, data: Dict[str, float]) -> None:
        try:
            if isinstance(data, dict):
                if 'paused' in data:
                    self.paused = bool(data.get('paused'))
                if 'last_reason_bits' in data:
                    self.last_reason_mask = int(data.get('last_reason_bits', 0))
                if 'last_change_ts' in data:
                    self.last_change_ts = float(data.get('last_change_ts', 0.0))
                if 'consec_bad' in data:
                    self._consec_bad = int(data.get('consec_bad', 0))
                if 'consec_good' in data:
                    self._consec_good = int(data.get('consec_good', 0))
                if 'hysteresis_bad' in data:
                    try:
                        self.cfg.hysteresis_bad_required = int(data.get('hysteresis_bad'))
                    except Exception:
                        pass
                if 'hysteresis_good' in data:
                    try:
                        self.cfg.hysteresis_good_required = int(data.get('hysteresis_good'))
                    except Exception:
                        pass
                if 'dry_run' in data:
                    try:
                        self.cfg.dry_run = bool(int(data.get('dry_run', 0)))
                    except Exception:
                        self.cfg.dry_run = bool(data.get('dry_run'))
                if 'manual_override_pause' in data:
                    try:
                        self.cfg.manual_override_pause = bool(int(data.get('manual_override_pause', 0)))
                    except Exception:
                        self.cfg.manual_override_pause = bool(data.get('manual_override_pause'))
        except Exception:
            pass

    def update(self, snapshot: Dict[str, float], now: float) -> None:
        if not getattr(self.cfg, 'enabled', True):
            return
        cancel = float(snapshot.get('cancel_rate_per_sec', 0.0))
        limit = max(1e-9, float(snapshot.get('cfg_max_cancel_per_sec', 1.0)))
        cancel_pct = 100.0 * cancel / limit
        rest_err = float(snapshot.get('rest_error_rate', 0.0))
        pnl_slope = float(snapshot.get('pnl_slope_per_min', 0.0))

        reason = 0
        if cancel_pct > float(getattr(self.cfg, 'cancel_rate_pct_of_limit_max', 90.0)):
            reason |= REASON_HIGH_CANCEL
        if rest_err > float(getattr(self.cfg, 'rest_error_rate_max', 0.01)):
            reason |= REASON_HIGH_ERRORS
        if pnl_slope < float(getattr(self.cfg, 'pnl_slope_min_per_min', -0.1)):
            reason |= REASON_NEGATIVE_PNL
        # Evaluate L3.2 extras using current time
        reason |= self.evaluate(now)
        breach = (reason != 0)

        # Evict old data and update hysteresis
        self._evict(now)

        if breach:
            self._consec_bad += 1
            self._consec_good = 0
        else:
            self._consec_good += 1
            self._consec_bad = 0
        self.breach_streak = self._consec_bad if breach else self._consec_good

        cb = int(getattr(self.cfg, 'consecutive_breaches_to_pause', 2))
        hb = int(getattr(self.cfg, 'hysteresis_bad_required', cb))
        bad_req = max(1, min(hb, cb))
        good_req = max(1, int(getattr(self.cfg, 'hysteresis_good_required', 2)))

        if (not self.paused) and self._consec_bad >= bad_req:
            self.paused = True
            self.last_change_ts = now
            self.pauses_total += 1
            self.last_reason_mask = reason
            return

        recovery_sec = float(getattr(self.cfg, 'recovery_minutes', 5.0)) * 60.0
        if self.paused and self._consec_good >= good_req and (now - self.last_change_ts) >= recovery_sec and (not breach):
            self.paused = False
            self.last_change_ts = now

    # Runtime feeds
    def add_cancel_latency_sample(self, ms: float, ts: float) -> None:
        try:
            ms = float(ms)
            ts = float(ts)
        except Exception:
            return
        clip = float(getattr(self.cfg, 'max_cancel_latency_ms_p95', getattr(self.cfg, 'cancel_p95_ms_max', 60000)))
        ms = min(ms, clip)
        self._cancel_latencies.append((ts, ms))
        self._evict(ts)

    def on_send_ok(self, cid: Optional[str], ts: float) -> None:
        self._record_send_event(cid, ts, True)

    def on_reject(self, cid: Optional[str], ts: float) -> None:
        self._record_send_event(cid, ts, False)

    def set_ws_lag_ms(self, ms: float, ts: float) -> None:
        try:
            self._ws_lag_ms = float(ms)
            self._ws_lag_ts = float(ts)
        except Exception:
            self._ws_lag_ms = 0.0
            self._ws_lag_ts = float(ts) if ts is not None else 0.0

    def set_inventory_snapshot(self, symbol_to_notional: Dict[str, float], budget_usd: float) -> None:
        try:
            self._inventory_snapshot = {str(k): float(v) for k, v in (symbol_to_notional or {}).items()}
            self._budget_usd = float(budget_usd)
        except Exception:
            self._inventory_snapshot = {}
            self._budget_usd = 0.0

    # Evaluation helpers for L3.2
    def compute_p95_cancel_latency(self, now: Optional[float] = None) -> float:
        if now is not None:
            self._evict(now)
        vals = [ms for (_, ms) in self._cancel_latencies]
        if not vals:
            return 0.0
        vals.sort()
        idx = max(0, int(0.95 * (len(vals) - 1)))
        return float(vals[idx])

    def compute_reject_rate(self, now: Optional[float] = None) -> float:
        if now is not None:
            self._evict(now)
        oks = 0
        rejects = 0
        for (ts, _, ok) in self._send_events:
            if (now is not None) and (ts > now):
                continue
            if ok:
                oks += 1
            else:
                rejects += 1
        total = oks + rejects
        if total <= 0:
            return 0.0
        return float(rejects) / float(total)

    def evaluate(self, now: Optional[float] = None, symbol: Optional[str] = None) -> int:
        reason = 0
        # manual override
        try:
            if getattr(self.cfg, 'manual_override_pause', False):
                reason |= (1 << 7)  # REASON_MANUAL
        except Exception:
            pass
        # Inventory thresholds
        try:
            gross = sum(abs(v) for v in self._inventory_snapshot.values())
            net_max = max(abs(v) for v in self._inventory_snapshot.values()) if self._inventory_snapshot else 0.0
        except Exception:
            gross, net_max = 0.0, 0.0
        # Resolve thresholds with per-symbol overrides if provided
        cfg_local = self._resolve_thresholds_for_symbol(symbol)
        if cfg_local['max_position_notional_usd'] > 0.0 and net_max > cfg_local['max_position_notional_usd']:
            reason |= REASON_INVENTORY
        if cfg_local['max_gross_exposure_usd'] > 0.0 and gross > cfg_local['max_gross_exposure_usd']:
            reason |= REASON_INVENTORY
        if self._budget_usd > 0.0 and (cfg_local['max_position_pct_budget'] < 100.0):
            pct = 100.0 * (net_max / self._budget_usd)
            if pct > cfg_local['max_position_pct_budget']:
                reason |= REASON_INVENTORY
        # Latency (cancel p95)
        lim = float(cfg_local['max_cancel_latency_ms_p95'])
        if lim > 0.0 and self.compute_p95_cancel_latency(now) > lim:
            reason |= REASON_LATENCY
        # WS lag
        if cfg_local['ws_lag_ms_max'] > 0.0 and self._ws_lag_ms > cfg_local['ws_lag_ms_max']:
            reason |= REASON_WS_LAG
        # Reject rate
        if cfg_local['order_reject_rate_max'] > 0.0 and self.compute_reject_rate(now) > cfg_local['order_reject_rate_max']:
            reason |= REASON_REJECTS
        return reason

    def _resolve_thresholds_for_symbol(self, symbol: Optional[str]) -> Dict[str, float]:
        # start with globals
        out = {
            'max_position_notional_usd': float(getattr(self.cfg, 'max_position_notional_usd', 0.0)),
            'max_gross_exposure_usd': float(getattr(self.cfg, 'max_gross_exposure_usd', 0.0)),
            'max_position_pct_budget': float(getattr(self.cfg, 'max_position_pct_budget', 100.0)),
            'max_cancel_latency_ms_p95': float(getattr(self.cfg, 'max_cancel_latency_ms_p95', getattr(self.cfg, 'cancel_p95_ms_max', 60000))),
            'ws_lag_ms_max': float(getattr(self.cfg, 'ws_lag_ms_max', 0.0)),
            'order_reject_rate_max': float(getattr(self.cfg, 'order_reject_rate_max', 0.0)),
        }
        try:
            if symbol and isinstance(getattr(self.cfg, 'per_symbol', None), dict):
                ov = getattr(self.cfg, 'per_symbol', {}).get(symbol, {}) or {}
                for k in list(out.keys()):
                    if k in ov:
                        out[k] = float(ov[k])
        except Exception:
            pass
        return out

    # internals
    def _evict(self, now: float) -> None:
        win = float(getattr(self.cfg, 'window_seconds', 300))
        threshold = now - win
        # evict send events
        while self._send_events and self._send_events[0][0] < threshold:
            self._send_events.popleft()
        # rebuild seen cids to earliest occurrence
        self._seen_cids.clear()
        for ts, cid, _ok in self._send_events:
            if cid is None:
                continue
            if cid not in self._seen_cids or ts < self._seen_cids[cid]:
                self._seen_cids[cid] = ts
        # evict cancel latencies
        while self._cancel_latencies and self._cancel_latencies[0][0] < threshold:
            self._cancel_latencies.popleft()

    def _record_send_event(self, cid: Optional[str], ts: float, ok: bool) -> None:
        ts = float(ts)
        # dedup per cid in window
        if cid is not None and cid in self._seen_cids:
            # ignore retries in current window
            return
        self._send_events.append((ts, cid, ok))
        if cid is not None:
            self._seen_cids[cid] = ts


