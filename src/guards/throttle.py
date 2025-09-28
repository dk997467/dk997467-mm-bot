"""
Throttle guard for request rate limiting and adaptive backoff.

Provides:
- Per-symbol and per-session rate limiting on creates/amends/cancels in sliding window
- Adaptive backoff based on error rate and WS lag
- Ring buffer implementation for O(1) operations and stable memory footprint
- Stdlib-only implementation with ASCII logs
"""

import time
from datetime import datetime, timezone
import math
from collections import defaultdict
from typing import Dict, Optional, Tuple

from src.common.config import ThrottleConfig


class _Ring:
    __slots__ = ("size","ring","base_ts","idx")
    def __init__(self, window_sec:int, now_sec:int) -> None:
        size = int(window_sec) if window_sec and window_sec > 0 else 1
        self.size = size
        self.ring = [0]*size
        self.base_ts = int(now_sec) - (size - 1)
        self.idx = size - 1
    def _advance(self, now_sec:int) -> None:
        now_sec = int(now_sec)
        cur_ts = self.base_ts + self.idx
        if now_sec <= cur_ts: return
        delta = now_sec - cur_ts
        if delta >= self.size:
            self.ring[:] = [0]*self.size
            self.base_ts = now_sec - (self.size - 1)
            self.idx = self.size - 1
            return
        for _ in range(delta):
            self.idx = (self.idx + 1) % self.size
            self.base_ts += 1
            self.ring[self.idx] = 0
    def add(self, now_sec:int, n:int=1) -> None:
        self._advance(now_sec); self.ring[self.idx] += int(n)
    def total(self, now_sec:int) -> int:
        self._advance(now_sec); return sum(self.ring)
    def to_snapshot(self) -> dict:
        return {"base_ts":int(self.base_ts),"idx":int(self.idx),"ring":list(self.ring)}
    @classmethod
    def from_snapshot(cls, window_sec:int, now_sec:int, snap:dict) -> "_Ring":
        size = int(window_sec) if window_sec and window_sec > 0 else 1
        r = cls(size, int(now_sec))
        try:
            rb = list(snap.get("ring", []))
            if len(rb) == size:
                r.ring = [int(x) for x in rb]
                r.base_ts = int(snap.get("base_ts", r.base_ts))
                r.idx = int(snap.get("idx", r.idx)) % size
                r._advance(int(now_sec))
        except Exception:
            r = cls(size, int(now_sec))
        return r


class ThrottleGuard:
    """Throttle guard with sliding window rate limits and adaptive backoff using ring buffers."""
    
    def __init__(self, cfg: ThrottleConfig):
        self.cfg = cfg
        self.window_sec = int(max(1, self.cfg.window_sec))
        
        # Per-symbol ring buffers
        self._rings: Dict[str, Dict[str, _Ring]] = {}
        
        # Backoff state
        self._current_backoff_ms = 0
        self._last_backoff_check = 0.0
        self._last_backoff_ms: Dict[str, float] = {}
        self._last_backoff_ms_max: float = 0.0
        # Snapshot meta (to restore window-level observability across restarts)
        self._snapshot_window_since_ts: float = 0.0
        self._snapshot_events_total: int = 0
        self._snapshot_last_event_ts: float = 0.0
        
    def _now_sec(self):
        return int(time.time())
    
    def _ensure_symbol(self, sym):
        if sym not in self._rings:
            now_sec = self._now_sec()
            self._rings[sym] = {
                "create": _Ring(self.window_sec, now_sec),
                "amend": _Ring(self.window_sec, now_sec),
                "cancel": _Ring(self.window_sec, now_sec)
            }
    
    def on_create(self, symbol: str, ts_ms: float) -> None:
        """Record a create event."""
        self._ensure_symbol(symbol)
        self._rings[symbol]["create"].add(int(ts_ms // 1000), 1)
    
    def on_amend(self, symbol: str, ts_ms: float) -> None:
        """Record an amend event."""
        self._ensure_symbol(symbol)
        self._rings[symbol]["amend"].add(int(ts_ms // 1000), 1)
    
    def on_cancel(self, symbol: str, ts_ms: float) -> None:
        """Record a cancel event."""
        self._ensure_symbol(symbol)
        self._rings[symbol]["cancel"].add(int(ts_ms // 1000), 1)
    
    def window_totals(self, symbol: str, ts_ms: float) -> Dict[str, int]:
        """Get current window totals for each event type."""
        self._ensure_symbol(symbol)
        now_s = int(ts_ms // 1000)
        return {
            "create": self._rings[symbol]["create"].total(now_s),
            "amend": self._rings[symbol]["amend"].total(now_s),
            "cancel": self._rings[symbol]["cancel"].total(now_s)
        }
    
    def allowed(self, kind: str, symbol: str, now: float) -> bool:
        """Check if operation is allowed within rate limits."""
        self._ensure_symbol(symbol)
        limit_per_sec = getattr(self.cfg, f'max_{kind}s_per_sec', float('inf'))
        current_count = self._rings[symbol][kind].total(int(now))
        max_count = int(limit_per_sec * self.cfg.window_sec)
        return current_count < max_count
    
    def on_event(self, kind: str, symbol: str, now: float) -> None:
        """Record an event (create/amend/cancel)."""
        self._ensure_symbol(symbol)
        self._rings[symbol][kind].add(int(now), 1)
    
    def compute_backoff_ms(self, error_rate: float, ws_lag_ms: float, now: float, symbol: Optional[str] = None) -> int:
        """Compute adaptive backoff delay based on error conditions with deterministic jitter."""
        # Check if conditions warrant backoff
        error_triggered = error_rate >= self.cfg.error_rate_trigger
        lag_triggered = ws_lag_ms >= self.cfg.ws_lag_trigger_ms
        
        if error_triggered or lag_triggered:
            # Exponential backoff: increase by factor of 2, capped at max
            if self._current_backoff_ms == 0:
                self._current_backoff_ms = self.cfg.backoff_base_ms
            else:
                self._current_backoff_ms = min(
                    self._current_backoff_ms * 2,
                    self.cfg.backoff_max_ms
                )
        else:
            # Reset backoff when conditions normalize
            self._current_backoff_ms = 0
        
        # Apply hard cap and deterministic jitter (per symbol)
        ms = float(self._current_backoff_ms)
        cap = float(getattr(self.cfg, 'backoff_cap_ms', 5000.0))
        ms = min(cap, ms)
        if symbol is None:
            symbol = "*"
        try:
            bucket = int(time.monotonic() // 5)
        except Exception:
            bucket = int(now // 5)
        ms = max(0.0, self._det_jitter(ms, symbol, bucket))
        self._last_backoff_check = now
        self._last_backoff_ms[symbol] = ms
        if ms > self._last_backoff_ms_max:
            self._last_backoff_ms_max = ms
        return int(ms)

    def _det_jitter(self, ms: float, symbol: str, now_bucket: int) -> float:
        """Deterministic jitter in range [-jitter_pct, +jitter_pct] using stdlib hash."""
        try:
            jitter_pct = float(getattr(self.cfg, 'jitter_pct', 0.10))
        except Exception:
            jitter_pct = 0.10
        seed = (hash((symbol, now_bucket)) & 0xffffffff)
        frac = (seed % 1000) / 1000.0  # [0,1)
        j = (frac * 2.0 - 1.0) * jitter_pct
        return ms * (1.0 + j)
    
    def get_window_counts(self, symbol: str, now: float) -> Dict[str, int]:
        """Get current window counts for metrics."""
        return self.window_totals(symbol, now * 1000)  # Convert to ms for window_totals

    # Aliases for clarity in exporters/rollouts
    def get_events_in_window(self, symbol: str, now: float) -> Dict[str, int]:
        return self.get_window_counts(symbol, now)

    def get_events_in_window_total(self, symbol: str, now: float) -> int:
        c = self.get_window_counts(symbol, now)
        return int(c.get('create', 0) + c.get('amend', 0) + c.get('cancel', 0))

    def get_backoff_ms_max(self) -> float:
        return float(self._last_backoff_ms_max)
    
    def get_current_backoff_ms(self, symbol: str) -> int:
        """Get current backoff delay for symbol."""
        # For simplicity, backoff is global across all symbols
        return self._current_backoff_ms
    
    def _evict_old(self, now: float) -> None:
        """Advance all ring buffers to current time (evict old entries)."""
        try:
            now_sec = int(now)
            for sym_rings in self._rings.values():
                for ring in sym_rings.values():
                    ring._advance(now_sec)
        except Exception:
            pass

    # ---- Snapshot persistence API ----
    def _compute_window_stats(self, now: Optional[float] = None) -> tuple[float, int, float]:
        """Compute (window_since_ts, events_total, last_event_ts) from current windows.

        If no events present, returns (0.0, 0, 0.0).
        """
        earliest: float = 0.0
        latest: float = 0.0
        total: int = 0
        try:
            if now is None:
                now = time.time()
            # Advance all ring buffers to current time
            self._evict_old(now)
            
            for sym_rings in self._rings.values():
                for ring in sym_rings.values():
                    count = ring.total(int(now))
                    total += count
                    if count > 0:
                        if earliest == 0.0:
                            earliest = now - self.cfg.window_sec
                        latest = now
        except Exception:
            pass
        return (earliest, int(total), latest)

    def to_snapshot(self) -> Dict[str, object]:
        """Return a deterministic snapshot of throttle window/backoff state.

        Format v2: {"version":2,"window_sec":int,"symbols":{"SYM":{"create":{"base_ts":int,"ring":[...]},...}}}
        Format v1: {"version":1,"window_since":ISO,"events_total":int,"backoff_ms_max":int,"last_event_ts":ISO}
        """
        try:
            # New v2 format with ring buffer state
            symbols_data = {}
            for symbol, rings in self._rings.items():
                symbols_data[symbol] = {
                    "create": rings["create"].to_snapshot(),
                    "amend": rings["amend"].to_snapshot(),
                    "cancel": rings["cancel"].to_snapshot()
                }
            
            return {
                "version": 2,
                "window_sec": int(self.window_sec),
                "symbols": symbols_data
            }
        except Exception:
            # Fallback to v1 format for compatibility
            try:
                # Prefer restored meta if present; otherwise compute from windows
                if self._snapshot_events_total > 0 or self._snapshot_last_event_ts > 0.0:
                    since_ts = float(self._snapshot_window_since_ts)
                    total = int(self._snapshot_events_total)
                    last_ts = float(self._snapshot_last_event_ts)
                else:
                    since_ts, total, last_ts = self._compute_window_stats()
                # ISO formatting (UTC)
                def _iso(ts: float) -> str:
                    try:
                        if ts <= 0.0:
                            return datetime.fromtimestamp(0, tz=timezone.utc).isoformat()
                        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    except Exception:
                        return datetime.fromtimestamp(0, tz=timezone.utc).isoformat()
                return {
                    "version": 1,
                    "window_since": _iso(since_ts),
                    "events_total": int(max(0, total)),
                    "backoff_ms_max": int(max(0, int(self._last_backoff_ms_max))),
                    "last_event_ts": _iso(last_ts),
                }
            except Exception:
                # Always return a valid shape
                return {
                    "version": 1,
                    "window_since": datetime.fromtimestamp(0, tz=timezone.utc).isoformat(),
                    "events_total": 0,
                    "backoff_ms_max": 0,
                    "last_event_ts": datetime.fromtimestamp(0, tz=timezone.utc).isoformat(),
                }

    def load_snapshot(self, data: Dict[str, object]) -> None:
        """Load snapshot produced by to_snapshot(). Supports v1 and v2 formats.

        v2: {"version":2,"window_sec":int,"symbols":{"SYM":{"create":{"base_ts":int,"ring":[...]},...}}}
        v1: {"version":1,"window_since":ISO,"events_total":int,"backoff_ms_max":int,"last_event_ts":ISO}
        """
        try:
            if not isinstance(data, dict):
                return
            
            version = data.get("version", 1)
            
            if version == 2:
                # Load v2 ring buffer format
                window_sec = data.get("window_sec", self.window_sec)
                if isinstance(window_sec, int) and window_sec > 0:
                    self.window_sec = window_sec
                
                symbols_data = data.get("symbols", {})
                if isinstance(symbols_data, dict):
                    now_sec = self._now_sec()
                    for symbol, kinds_data in symbols_data.items():
                        if isinstance(kinds_data, dict):
                            self._rings[symbol] = {}
                            for kind in ["create", "amend", "cancel"]:
                                if kind in kinds_data and isinstance(kinds_data[kind], dict):
                                    self._rings[symbol][kind] = _Ring.from_snapshot(
                                        self.window_sec, now_sec, kinds_data[kind]
                                    )
                                else:
                                    self._rings[symbol][kind] = _Ring(self.window_sec, now_sec)
            else:
                # Load v1 legacy format - convert old timestamp lists to rings
                # For legacy compatibility, just restore meta fields
                ws = data.get("window_since")
                lt = data.get("last_event_ts")
                total = data.get("events_total", 0)
                backmax = data.get("backoff_ms_max", 0)
                
                def _parse_iso(x: object) -> float:
                    if isinstance(x, str):
                        try:
                            return datetime.fromisoformat(x).timestamp()
                        except Exception:
                            return 0.0
                    return 0.0
                
                self._snapshot_window_since_ts = float(max(0.0, _parse_iso(ws)))
                self._snapshot_last_event_ts = float(max(0.0, _parse_iso(lt)))
                try:
                    self._snapshot_events_total = int(total) if int(total) >= 0 else 0
                except Exception:
                    self._snapshot_events_total = 0
                try:
                    b = int(backmax)
                    self._last_backoff_ms_max = float(max(0, b))
                except Exception:
                    self._last_backoff_ms_max = 0.0
        except Exception:
            # leave state unchanged on error
            pass

    def reset(self) -> None:
        """Reset throttle windows and backoff/snapshot state."""
        try:
            # Clear ring buffers
            self._rings.clear()
            # Reset backoff and meta
            self._current_backoff_ms = 0
            self._last_backoff_ms.clear()
            self._last_backoff_ms_max = 0.0
            self._snapshot_window_since_ts = 0.0
            self._snapshot_events_total = 0
            self._snapshot_last_event_ts = 0.0
        except Exception:
            pass
