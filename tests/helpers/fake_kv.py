from typing import Optional, Dict, Tuple


class FakeKV:
    def __init__(self):
        self._store: Dict[str, Tuple[str, int]] = {}
        self._now: int = 0

    def time_ms(self) -> int:
        return int(self._now)

    def tick(self, delta_ms: int) -> int:
        self._now += int(delta_ms)
        self._gc()
        return self._now

    def setnx(self, key: str, val: str, px: int) -> bool:
        self._gc()
        if key in self._store:
            # if expired it's removed by _gc
            return False
        self._store[str(key)] = (str(val), self._now + int(px))
        return True

    def pexpire(self, key: str, px: int) -> bool:
        self._gc()
        if key not in self._store:
            return False
        val, _ = self._store[key]
        self._store[key] = (val, self._now + int(px))
        return True

    def get(self, key: str) -> Optional[str]:
        self._gc()
        t = self._store.get(key)
        if not t:
            return None
        val, exp = t
        if self._now >= exp:
            del self._store[key]
            return None
        return val

    def delkey(self, key: str) -> None:
        self._store.pop(key, None)

    def _gc(self) -> None:
        # remove expired
        ks = list(self._store.keys())
        for k in ks:
            v, exp = self._store.get(k, ("", 0))
            if self._now >= exp:
                self._store.pop(k, None)


