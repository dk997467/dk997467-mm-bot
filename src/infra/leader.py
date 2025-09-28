from typing import Optional


class KV:
    def setnx(self, key: str, val: str, px: int) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def pexpire(self, key: str, px: int) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def delkey(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def time_ms(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class LeaderLock:
    def __init__(self, kv: KV, key: str, holder_id: str, ttl_ms: int = 3000, renew_ms: int = 1500, metrics=None, env: str = "dev", service: str = "mm-bot"):
        self.kv = kv
        self.key = str(key)
        self.holder_id = str(holder_id)
        self.ttl_ms = int(max(1, ttl_ms))
        self.renew_ms = int(max(1, renew_ms))
        self._last_renew_ms: int = -10**12
        self._leader: bool = False
        self.metrics = metrics
        self.env = str(env)
        self.service = str(service)

    def _log(self, msg: str) -> None:
        try:
            print(f"LEADER {msg}")
        except Exception:
            pass

    def _update_state_metric(self, state: int) -> None:
        try:
            if self.metrics and hasattr(self.metrics, 'set_leader_state'):
                self.metrics.set_leader_state(env=self.env, service=self.service, instance=self.holder_id, state=float(state))
        except Exception:
            pass

    def try_acquire(self, now_ms: int) -> bool:
        ok = False
        try:
            ok = bool(self.kv.setnx(self.key, self.holder_id, px=self.ttl_ms))
        except Exception:
            ok = False
        if ok:
            self._leader = True
            self._last_renew_ms = int(now_ms)
            self._log(f"acquire key={self.key} holder={self.holder_id} ttl_ms={self.ttl_ms}")
            # election
            try:
                if self.metrics and hasattr(self.metrics, 'inc_leader_elections'):
                    self.metrics.inc_leader_elections(env=self.env, service=self.service)
            except Exception:
                pass
            self._update_state_metric(1)
            return True
        # not acquired
        self._leader = (self.kv.get(self.key) == self.holder_id)
        self._update_state_metric(1 if self._leader else 0)
        return False

    def renew(self, now_ms: int) -> bool:
        # Only renew if we are current leader and enough time has passed
        if not self.is_leader():
            return False
        if (int(now_ms) - int(self._last_renew_ms)) < self.renew_ms:
            return True
        ok = False
        try:
            # On renew, extend the lease by renew_ms, not full ttl_ms
            ok = bool(self.kv.pexpire(self.key, px=self.renew_ms))
        except Exception:
            ok = False
        if ok:
            self._last_renew_ms = int(now_ms)
            self._log(f"renew key={self.key} holder={self.holder_id} ttl_ms={self.ttl_ms}")
            self._update_state_metric(1)
            return True
        else:
            # lost leadership
            self._leader = (self.kv.get(self.key) == self.holder_id)
            if not self._leader:
                self._log(f"renew_fail key={self.key} holder={self.holder_id}")
                try:
                    if self.metrics and hasattr(self.metrics, 'inc_leader_renew_fail'):
                        self.metrics.inc_leader_renew_fail(env=self.env, service=self.service)
                except Exception:
                    pass
                self._update_state_metric(0)
            return False

    def release(self) -> None:
        try:
            if self.is_leader():
                self.kv.delkey(self.key)
                self._log(f"release key={self.key} holder={self.holder_id}")
        finally:
            self._leader = False
            self._update_state_metric(0)

    def is_leader(self) -> bool:
        try:
            if not self._leader:
                return False
            cur = self.kv.get(self.key)
            self._leader = (cur == self.holder_id)
            return bool(self._leader)
        except Exception:
            return False

    def holder(self) -> Optional[str]:
        try:
            return self.kv.get(self.key)
        except Exception:
            return None


