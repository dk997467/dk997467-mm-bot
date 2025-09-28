from typing import Any

from .leader import LeaderLock, KV


class QuoterRunner:
    def __init__(self, kv: KV, instance_id: str, cfg: Any, clock: Any, metrics: Any):
        self.instance_id = str(instance_id)
        self.kv = kv
        self.cfg = cfg
        self.clock = clock
        self.metrics = metrics
        self.lock = LeaderLock(kv, cfg.ha_failover.lock_key, self.instance_id, ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms, metrics=metrics)

    def tick(self, now_ms: int) -> str:
        if not self.lock.is_leader():
            # Try acquire
            self.lock.try_acquire(now_ms)
        else:
            # Renew
            ok = self.lock.renew(now_ms)
            if not ok:
                # Lost leadership
                pass
        return "leader" if self.lock.is_leader() else "follower"


