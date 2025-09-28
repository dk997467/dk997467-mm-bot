from typing import Any, Dict


def _finite(x: Any) -> float:
    try:
        import math
        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def idem_key_place(symbol: str, side: str, price: float, size: float, client_id: str) -> str:
    return f"pl:{symbol}:{side}:{_finite(price):.6f}:{_finite(size):.6f}:{client_id}"


def idem_key_replace(client_id: str, new_price: float, new_size: float) -> str:
    return f"rp:{client_id}:{_finite(new_price):.6f}:{_finite(new_size):.6f}"


def idem_key_cancel(client_id: str) -> str:
    return f"cl:{client_id}"


class IdemFilter:
    def __init__(self, ttl_ms: int = 5000, clock=None, metrics=None, env: str = "dev", service: str = "mm-bot"):
        self.ttl_ms = int(max(1, ttl_ms))
        self.clock = clock
        self.metrics = metrics
        self.env = str(env)
        self.service = str(service)
        self._map: Dict[str, int] = {}

    def _now_ms(self) -> int:
        if self.clock and hasattr(self.clock, 'time_ms'):
            return int(self.clock.time_ms())
        import time
        return int(time.time() * 1000)

    def seen(self, key: str, now_ms: int) -> bool:
        self._gc(now_ms)
        v = self._map.get(key)
        hit = v is not None and now_ms < v
        if hit and self.metrics and hasattr(self.metrics, 'inc_order_idem_hit'):
            # op inferred by prefix
            op = 'place' if key.startswith('pl:') else 'replace' if key.startswith('rp:') else 'cancel'
            try:
                self.metrics.inc_order_idem_hit(env=self.env, service=self.service, op=op)
            except Exception:
                pass
        return hit

    def touch(self, key: str, now_ms: int) -> None:
        self._gc(now_ms)
        self._map[str(key)] = int(now_ms + self.ttl_ms)

    def _gc(self, now_ms: int) -> None:
        ks = list(self._map.keys())
        for k in ks:
            if now_ms >= int(self._map.get(k, 0)):
                self._map.pop(k, None)


