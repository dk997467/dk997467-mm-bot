from tools.chaos.soak_failover import FakeKVLock


def test_fake_kv_lock_transitions():
    kv = FakeKVLock(ttl_ms=1000)
    assert kv.try_acquire('A', 0)
    assert kv.owner == 'A'
    # renew ok
    assert kv.renew('A', 500)
    # B cannot acquire before expiry
    assert not kv.try_acquire('B', 600)
    # after expiry
    assert kv.try_acquire('B', 2000)
    assert kv.owner == 'B'
    assert kv.leader_elections_total >= 2
    # renew fail counts
    assert not kv.renew('A', 2100)
    assert kv.renew_fail_total >= 1


