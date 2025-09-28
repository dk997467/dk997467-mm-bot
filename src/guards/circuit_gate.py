"""
F2 Circuit Gate: simple time-window error-rate circuit breaker with HALF_OPEN probes.

Stdlib-only. Metrics via provided callbacks; ASCII logs on transitions.

Enhancements:
- Deterministic state constants and mappings
- Optional thread-safety via Lock
- Injectable time function
- Idempotent transitions and unified metrics callback
- Snapshot and state name helpers
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Tuple, Optional, Dict, Any, ContextManager, List
import time
import threading
from contextlib import nullcontext


State = str  # 'OPEN' | 'TRIPPED' | 'HALF_OPEN'

# State constants and mappings (stable)
# Official enum for dashboards/alerts
STATE_OPEN: int = 0
STATE_TRIPPED: int = 1
STATE_HALF_OPEN: int = 2
STATE_TO_NAME: Dict[int, str] = {STATE_OPEN: 'OPEN', STATE_TRIPPED: 'TRIPPED', STATE_HALF_OPEN: 'HALF_OPEN'}
NAME_TO_STATE: Dict[str, int] = {'OPEN': STATE_OPEN, 'TRIPPED': STATE_TRIPPED, 'HALF_OPEN': STATE_HALF_OPEN}
# Gauge mapping for current state (low-cardinality)
STATE_TO_INT: Dict[str, int] = {'OPEN': STATE_OPEN, 'TRIPPED': STATE_TRIPPED, 'HALF_OPEN': STATE_HALF_OPEN}

__all__ = [
    'CircuitGate',
    'STATE_OPEN', 'STATE_TRIPPED', 'STATE_HALF_OPEN',
    'STATE_TO_NAME', 'NAME_TO_STATE',
]


@dataclass
class CircuitParams:
    max_err_rate: float = 0.15
    window_sec: int = 300
    min_closed_sec: int = 180
    half_open_probe: int = 5


class CircuitGate:
    def __init__(self, params: CircuitParams,
                 set_state_metric: Optional[Callable[[int], None]] = None,
                 set_err_rate_metric: Optional[Callable[[float], None]] = None,
                 inc_transition_metric: Optional[Callable[[str, str], None]] = None,
                 metrics_cb: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 time_fn: Optional[Callable[[], float]] = None,
                 thread_safe: bool = False,
                 events_maxlen: Optional[int] = None,
                 events_per_sec_hint: int = 1) -> None:
        self.params = params
        self._state: State = 'OPEN'
        # compute bounded deque maxlen (hard cap 10k)
        hint = int(events_per_sec_hint) if events_per_sec_hint and events_per_sec_hint > 0 else 1
        if events_maxlen is None:
            calc = int(self.params.window_sec * max(1, hint))
            events_maxlen = min(10000, max(1, calc))
        self._events: Deque[Tuple[float, bool]] = deque(maxlen=int(events_maxlen))  # (ts, is_error)
        self._tripped_at: float = 0.0
        self._half_open_remaining: int = 0
        self._last_transition_ts: float = 0.0
        self._set_state_metric = set_state_metric
        self._set_err_rate_metric = set_err_rate_metric
        self._inc_transition_metric = inc_transition_metric
        self._metrics_cb = metrics_cb
        self._time_fn: Callable[[], float] = time_fn or time.monotonic
        self._lock = threading.Lock() if thread_safe else None
        # anti-flood knobs
        self._anti_flood_enabled: bool = True
        self._max_events_per_sec: int = 50
        self._max_log_lines_per_sec: int = 10
        self._last_log_sec: int = -1
        self._sec_log_budget: int = self._max_log_lines_per_sec
        # flood coalesce counter (not exposed; sent via metrics_cb)
        self._flood_coalesced: int = 0
        # initialize metrics
        self._apply_metrics()

    def state(self) -> State:
        return self._state

    def _now(self) -> float:
        return float(self._time_fn())

    def _lock_cm(self) -> ContextManager[Any]:
        return self._lock if self._lock is not None else nullcontext()

    def _window_prune(self, now_ts: float) -> None:
        win = int(self.params.window_sec)
        now_sec = int(now_ts)
        cutoff_sec = now_sec - win
        dq = self._events
        # events are (ts_sec:int, ok:int, err:int)
        while dq and dq[0][0] < cutoff_sec:
            dq.popleft()

    def _err_rate(self, now_ts: float) -> float:
        self._window_prune(now_ts)
        # compute from bins sum(ok+err)
        if not self._events:
            return 0.0
        ok = 0
        err = 0
        for ts_sec, ok_c, err_c in self._events:
            # bins already pruned by window
            ok += int(ok_c)
            err += int(err_c)
        total = ok + err
        return 0.0 if total <= 0 else (err / float(total))

    def _format_transition_log(self, frm: State, to: State, err_rate: float, window_len: int, now_int: int, reason: str) -> str:
        # Strict key order:
        # event=circuit_transition state_from=<old> state_to=<new> err_rate=<%.6f> window_len=<int> now=<int> reason=<str>
        return (
            f"event=circuit_transition "
            f"state_from={frm} "
            f"state_to={to} "
            f"err_rate={err_rate:.6f} "
            f"window_len={window_len} "
            f"now={now_int} "
            f"reason={reason}"
        )

    def _emit_transition(self, frm: State, to: State, err_rate: float, reason: str) -> None:
        now = int(self._now())
        window_len = len(self._events)
        # ASCII deterministic one-line log with fixed order
        line = self._format_transition_log(frm, to, err_rate, window_len, now, reason)
        # anti-flood: limit logs per second
        ts_sec = now
        if self._last_log_sec != ts_sec:
            self._last_log_sec = ts_sec
            self._sec_log_budget = self._max_log_lines_per_sec
        if self._sec_log_budget > 0:
            print(line)
            self._sec_log_budget -= 1
        # metrics (legacy callbacks)
        if self._inc_transition_metric:
            try:
                self._inc_transition_metric(frm, to)
            except Exception:
                pass
        # unified metrics callback (counter)
        if self._metrics_cb:
            try:
                self._metrics_cb("transitions_total", {"from": frm, "to": to})
            except Exception:
                pass

    def _apply_metrics(self) -> None:
        # gauges
        if self._set_state_metric:
            try:
                self._set_state_metric(STATE_TO_INT.get(self._state, STATE_OPEN))
            except Exception:
                pass
        rate_now = self._err_rate(self._now())
        if self._set_err_rate_metric:
            try:
                self._set_err_rate_metric(rate_now)
            except Exception:
                pass
        if self._metrics_cb:
            try:
                self._metrics_cb("circuit_state", {"value": STATE_TO_INT.get(self._state, STATE_OPEN)})
                self._metrics_cb("err_rate_window", {"value": rate_now})
            except Exception:
                pass

    def state_name(self) -> str:
        return str(self._state)

    @classmethod
    def from_str(cls, name: str) -> int:
        return int(NAME_TO_STATE.get(str(name).strip().upper(), STATE_OPEN))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock_cm():
            now_ts = self._now()
            rate = self._err_rate(now_ts)
            return {
                "state": self.state_name(),
                "err_rate": float(rate),
                "window_len": int(len(self._events)),
                "last_transition_ts": int(self._last_transition_ts),
            }

    def _transition(self, new_state: State, reason: str, err_rate: float) -> None:
        if new_state == self._state:
            return
        frm = self._state
        self._state = new_state
        self._last_transition_ts = self._now()
        self._emit_transition(frm, new_state, err_rate, reason)
        self._apply_metrics()

    def record(self, is_error: bool) -> State:
        with self._lock_cm():
            now_ts = self._now()
            ts_sec = int(now_ts)
            # coalesce into per-second bin
            add_err = 1 if is_error else 0
            add_ok = 0 if is_error else 1
            if self._events and self._events[-1][0] == ts_sec:
                # update existing bin
                last_ts, ok_c, err_c = self._events[-1]
                new_ok = ok_c + add_ok
                new_err = err_c + add_err
                self._events[-1] = (last_ts, new_ok, new_err)
                # count coalesced events (beyond first in this sec)
                self._flood_coalesced += 1
                if self._metrics_cb:
                    try:
                        self._metrics_cb("flood_coalesced_total", {"add": 1})
                    except Exception:
                        pass
            else:
                # new bin for this second
                self._events.append((ts_sec, add_ok, add_err))
            self._window_prune(now_ts)

            # Update metrics (gauges)
            self._apply_metrics()
            # per-sec rate gauge
            if self._metrics_cb and self._events:
                try:
                    _ts, ok_c, err_c = self._events[-1]
                    self._metrics_cb("per_sec_event_rate", {"value": int(ok_c + err_c)})
                except Exception:
                    pass

            # Evaluate transitions
            rate = self._err_rate(now_ts)
            st = self._state

            if st == 'OPEN':
                if rate > float(self.params.max_err_rate):
                    self._tripped_at = now_ts
                    self._half_open_remaining = 0
                    self._transition('TRIPPED', reason='trip', err_rate=rate)
            elif st == 'TRIPPED':
                if (now_ts - self._tripped_at) >= float(self.params.min_closed_sec):
                    self._half_open_remaining = int(self.params.half_open_probe)
                    self._transition('HALF_OPEN', reason='probe_start', err_rate=rate)
            elif st == 'HALF_OPEN':
                # In half-open, allow limited probes. If any error -> TRIPPED. If all probes success -> OPEN.
                if is_error:
                    self._tripped_at = now_ts
                    self._half_open_remaining = 0
                    self._transition('TRIPPED', reason='probe_fail', err_rate=rate)
                else:
                    if self._half_open_remaining > 0:
                        self._half_open_remaining -= 1
                    if self._half_open_remaining <= 0:
                        self._transition('OPEN', reason='probe_success', err_rate=rate)
            return self._state

    # convenience wrappers
    def on_ok(self) -> State:
        return self.record(False)

    def on_error(self) -> State:
        return self.record(True)


