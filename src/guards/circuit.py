import time
from collections import deque
from typing import Deque, Tuple, Optional


class CircuitBreaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self._state: str = 'closed'
        self._opened_ts: float = 0.0
        self._half_open_remaining: int = int(getattr(cfg, 'half_open_probes', 5))
        # sliding window of (ts, ok, http_code)
        self._events: Deque[Tuple[float, bool, int]] = deque()
        self._last_tick: float = 0.0

    def state(self) -> str:
        return self._state

    def _evict(self, now: float) -> None:
        cutoff = now - float(getattr(self.cfg, 'window_sec', 60.0))
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _rates(self, now: float) -> Tuple[float, float, float]:
        self._evict(now)
        total = max(1, len(self._events))
        errors = sum(1 for _, ok, _ in self._events if not ok)
        r5xx = sum(1 for _, ok, code in self._events if (not ok) and 500 <= code < 600)
        r429 = sum(1 for _, ok, code in self._events if (not ok) and code == 429)
        return errors / total, r5xx / total, r429 / total

    def allowed(self, op: str) -> bool:
        if self._state == 'open':
            # cancel always allowed in open
            return op == 'cancel'
        if self._state == 'half_open':
            # allow limited probes for all ops
            return self._half_open_remaining > 0 or op == 'cancel'
        return True

    def on_result(self, cid: str, ok: bool, http_code: int, now: Optional[float] = None) -> None:
        ts = now or time.time()
        self._events.append((ts, ok, int(http_code)))
        self._evict(ts)
        # consume probe in half-open on attempt
        if self._state == 'half_open':
            self._half_open_remaining = max(0, self._half_open_remaining - 1)

    def tick(self, now: Optional[float] = None) -> None:
        ts = now or time.time()
        self._last_tick = ts
        err_rate, r5xx_rate, r429_rate = self._rates(ts)
        # transitions
        if self._state == 'closed':
            if (err_rate >= float(getattr(self.cfg, 'err_rate_open', 0.5)) or
                r5xx_rate >= float(getattr(self.cfg, 'http_5xx_rate_open', 0.2)) or
                r429_rate >= float(getattr(self.cfg, 'http_429_rate_open', 0.2))):
                self._state = 'open'
                self._opened_ts = ts
                self._half_open_remaining = int(getattr(self.cfg, 'half_open_probes', 5))
                return
        elif self._state == 'open':
            if ts - self._opened_ts >= float(getattr(self.cfg, 'open_duration_sec', 30.0)):
                self._state = 'half_open'
                self._half_open_remaining = int(getattr(self.cfg, 'half_open_probes', 5))
                return
        elif self._state == 'half_open':
            cooldown = float(getattr(self.cfg, 'cooldown_sec', 5.0))
            if self._half_open_remaining == 0:
                # decide: if window error rate low → close, else reopen
                if err_rate < float(getattr(self.cfg, 'err_rate_open', 0.5)) and r5xx_rate < float(getattr(self.cfg, 'http_5xx_rate_open', 0.2)) and r429_rate < float(getattr(self.cfg, 'http_429_rate_open', 0.2)):
                    self._state = 'closed'
                else:
                    self._state = 'open'
                    self._opened_ts = ts
                self._half_open_remaining = int(getattr(self.cfg, 'half_open_probes', 5))
                return


