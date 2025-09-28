from tests.helpers.fake_kv import FakeKV
from src.infra.leader import LeaderLock


class Cfg:
    class HA:
        lock_key = "mm:quoter:leader"
        ttl_ms = 3000
        renew_ms = 1500
    ha_failover = HA()


def test_acquire_and_renew():
    kv = FakeKV()
    cfg = Cfg()
    a = LeaderLock(kv, cfg.ha_failover.lock_key, "A", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    b = LeaderLock(kv, cfg.ha_failover.lock_key, "B", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    now = kv.time_ms()
    assert a.try_acquire(now)
    assert not b.try_acquire(now)
    # renew before TTL
    kv.tick(1000)
    assert a.renew(kv.time_ms())
    assert a.is_leader()


def test_expire_and_takeover():
    kv = FakeKV()
    cfg = Cfg()
    a = LeaderLock(kv, cfg.ha_failover.lock_key, "A", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    b = LeaderLock(kv, cfg.ha_failover.lock_key, "B", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    assert a.try_acquire(kv.time_ms())
    # let expire by not renewing
    kv.tick(cfg.ha_failover.ttl_ms + 10)
    # B takes over
    assert b.try_acquire(kv.time_ms())
    assert b.is_leader()


def test_release():
    kv = FakeKV()
    cfg = Cfg()
    a = LeaderLock(kv, cfg.ha_failover.lock_key, "A", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    b = LeaderLock(kv, cfg.ha_failover.lock_key, "B", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    assert a.try_acquire(kv.time_ms())
    a.release()
    assert b.try_acquire(kv.time_ms())


def test_renew_only_by_leader():
    kv = FakeKV()
    cfg = Cfg()
    a = LeaderLock(kv, cfg.ha_failover.lock_key, "A", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    b = LeaderLock(kv, cfg.ha_failover.lock_key, "B", ttl_ms=cfg.ha_failover.ttl_ms, renew_ms=cfg.ha_failover.renew_ms)
    assert a.try_acquire(kv.time_ms())
    # Non-leader renew returns False and doesn't extend expiry
    assert not b.renew(kv.time_ms())
    kv.tick(cfg.ha_failover.ttl_ms + 10)
    assert b.try_acquire(kv.time_ms())

