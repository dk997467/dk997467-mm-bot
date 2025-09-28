"""
Latency Boost orderflow integration (stdlib-only).

Provides per-symbol replace throttle and tail batch-cancel helpers
for wiring into higher-level order management.
"""

from typing import Dict, Tuple, Optional, List
import time

from src.exchange.throttle import ReplaceThrottle, TailBatchCanceller


class LatencyBoostOrderFlow:
    def __init__(
        self,
        metrics: Optional[object] = None,
        replace_max_concurrent: int = 2,
        replace_min_interval_ms: int = 60,
        tail_age_ms: int = 800,
        tail_max_batch: int = 10,
        tail_jitter_ms: int = 0,
    ):
        self.metrics = metrics
        self._throttle = ReplaceThrottle(
            max_concurrent=replace_max_concurrent,
            min_interval_ms=replace_min_interval_ms,
        )
        self._canceller = TailBatchCanceller(
            tail_age_ms=tail_age_ms,
            max_batch=tail_max_batch,
            jitter_ms=tail_jitter_ms,
        )
        self._replace_count: Dict[str, int] = {}
        self._window_start_ms: int = 0

    def allow_replace(self, symbol: str, now_ms: Optional[int] = None) -> bool:
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        allowed = self._throttle.allow(symbol, ts)
        if allowed:
            # simple 60s rate window per symbol
            if self._window_start_ms == 0:
                self._window_start_ms = ts
            self._replace_count[symbol] = self._replace_count.get(symbol, 0) + 1
            window_ms = max(1, ts - self._window_start_ms)
            per_min = self._replace_count[symbol] * 60000.0 / float(window_ms)
            m = self.metrics
            try:
                if m and hasattr(m, 'on_replace_allowed'):
                    m.on_replace_allowed(symbol, per_min)
            except Exception:
                pass
        return allowed

    def settle_replace(self, symbol: str) -> None:
        self._throttle.settle(symbol)

    def select_tail_cancels(self, active_orders: Dict[str, Tuple[int, str]], now_ms: Optional[int] = None) -> List[Tuple[str, str]]:
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        sel = self._canceller.select(active_orders, ts)
        if sel:
            # per-symbol increment
            by_sym: Dict[str, int] = {}
            for _cid, sym in sel:
                by_sym[sym] = by_sym.get(sym, 0) + 1
            m = self.metrics
            for sym, _cnt in sorted(by_sym.items()):
                try:
                    if m and hasattr(m, 'on_batch_cancel'):
                        m.on_batch_cancel(sym, _cnt)
                except Exception:
                    pass
        return sel


