import time
from typing import Dict, Deque, Tuple, List
from collections import deque
from src.common.invariants import assert_range
from src.audit.log import audit_event


class ReplaceThrottle:
    def __init__(self, max_concurrent: int = 2, min_interval_ms: int = 40, backoff_on_rate_limit_ms: int = 200):
        self.max_concurrent = int(max_concurrent)
        self.min_interval_ms = int(min_interval_ms)
        self.backoff_on_rate_limit_ms = int(backoff_on_rate_limit_ms)
        # invariants
        assert_range(self.max_concurrent, 1, 10000, code='E_CFG_THROTTLE')
        assert_range(self.min_interval_ms, 0, 3600000, code='E_CFG_THROTTLE')
        assert_range(self.backoff_on_rate_limit_ms, 0, 5000, code='E_CFG_THROTTLE')
        self._last_ts_ms: Dict[str, int] = {}
        self._inflight: Dict[str, int] = {}
        self._backoff_until_ms: Dict[str, int] = {}  # Track backoff periods per symbol

    def allow(self, symbol: str, now_ms: int) -> bool:
        # Check if in backoff period
        backoff_until = self._backoff_until_ms.get(symbol, 0)
        if now_ms < backoff_until:
            print(f"THROTTLE deny symbol={symbol} reason=backoff until_ms={backoff_until}")
            try:
                audit_event("REPLACE", symbol, {"allowed": 0, "reason": "backoff"})
            except Exception:
                pass
            return False
        
        last = self._last_ts_ms.get(symbol, -10**12)
        if self._inflight.get(symbol, 0) >= self.max_concurrent:
            print(f"THROTTLE deny symbol={symbol} reason=concurrency")
            try:
                audit_event("REPLACE", symbol, {"allowed": 0, "reason": "concurrency"})
            except Exception:
                pass
            return False
        if (now_ms - last) < self.min_interval_ms:
            print(f"THROTTLE deny symbol={symbol} reason=interval")
            try:
                audit_event("REPLACE", symbol, {"allowed": 0, "reason": "min_interval"})
            except Exception:
                pass
            return False
        self._last_ts_ms[symbol] = now_ms
        self._inflight[symbol] = self._inflight.get(symbol, 0) + 1
        print(f"THROTTLE allow symbol={symbol} inflight={self._inflight.get(symbol,0)}")
        try:
            audit_event("REPLACE", symbol, {"allowed": 1})
        except Exception:
            pass
        return True
    
    def trigger_backoff(self, symbol: str, now_ms: int) -> None:
        """Trigger rate-limit backoff for a symbol."""
        self._backoff_until_ms[symbol] = now_ms + self.backoff_on_rate_limit_ms
        print(f"THROTTLE backoff triggered symbol={symbol} duration_ms={self.backoff_on_rate_limit_ms}")
        try:
            audit_event("THROTTLE_BACKOFF", symbol, {"backoff_ms": self.backoff_on_rate_limit_ms})
        except Exception:
            pass

    def settle(self, symbol: str) -> None:
        c = self._inflight.get(symbol, 0)
        if c > 0:
            self._inflight[symbol] = c - 1


class TailBatchCanceller:
    def __init__(self, tail_age_ms: int = 800, max_batch: int = 10, jitter_ms: int = 0):
        self.tail_age_ms = int(tail_age_ms)
        self.max_batch = int(max_batch)
        self.jitter_ms = int(jitter_ms)

    def select(self, orders: Dict[str, Tuple[int, str]], now_ms: int) -> List[Tuple[str, str]]:
        aged = [(cl, sym, now_ms - ts) for cl, (ts, sym) in orders.items() if (now_ms - ts) >= self.tail_age_ms]
        aged.sort(key=lambda x: (-x[2], x[1], x[0]))
        batch = [(cl, sym) for cl, sym, _ in aged[: self.max_batch]]
        if batch:
            print(f"BATCH_CANCEL size={len(batch)} tail_age_ms={self.tail_age_ms}")
            try:
                # group by symbol with count
                counts: Dict[str, int] = {}
                for _, sym in batch:
                    counts[sym] = counts.get(sym, 0) + 1
                for sym, cnt in counts.items():
                    audit_event("CANCEL", sym, {"batch": int(cnt), "tail_age_ms": int(self.tail_age_ms)})
            except Exception:
                pass
        return batch


