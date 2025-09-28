from pathlib import Path

from tests.helpers.fake_kv import FakeKV
from src.infra.leader import LeaderLock
from src.infra.quoter_runner import QuoterRunner


class Cfg:
    class HA:
        lock_key = "mm:quoter:leader"
        ttl_ms = 3000
        renew_ms = 1500
    ha_failover = HA()


class Clock:
    def __init__(self, kv: FakeKV):
        self.kv = kv
    def time_ms(self) -> int:
        return self.kv.time_ms()


class DummyMetrics:
    def set_leader_state(self, **kwargs):
        pass
    def inc_leader_elections(self, **kwargs):
        pass
    def inc_leader_renew_fail(self, **kwargs):
        pass


def test_ha_failover_e2e(tmp_path):
    kv = FakeKV()
    cfg = Cfg()
    clk = Clock(kv)
    m = DummyMetrics()
    a = QuoterRunner(kv, "A", cfg, clk, m)
    b = QuoterRunner(kv, "B", cfg, clk, m)

    lines = []
    def snap(t, call_a=True, call_b=True):
        ra = "leader" if a.lock.is_leader() else "follower"
        rb = "leader" if b.lock.is_leader() else "follower"
        if call_a:
            ra = a.tick(kv.time_ms())
        if call_b:
            rb = b.tick(kv.time_ms())
        lines.append(f"t={t:04d} A={ra} B={rb}\n")

    # 0: A acquires
    snap(0)
    # 500..2500: renews
    for t in (500, 1500):
        kv.tick(t - kv.time_ms())
        snap(t)
    # 2600..3200: A down (no renew); B tries takeover after TTL
    kv.tick(3000 - kv.time_ms())
    # A is down, only B ticks (takes over)
    snap(3000, call_a=False, call_b=True)
    # B should acquire
    for t in (3300, 4000):
        kv.tick(t - kv.time_ms())
        snap(t, call_a=False, call_b=True)
    # A returns but stays follower
    kv.tick(4100 - kv.time_ms())
    snap(4100, call_a=True, call_b=True)
    kv.tick(4400 - kv.time_ms())
    snap(4400, call_a=True, call_b=True)

    out = tmp_path / "ha_failover_case1.out"
    with open(out, 'w', encoding='ascii', newline='\n') as f:
        f.writelines(lines)

    root = Path(__file__).resolve().parents[2]
    golden = (root / "tests" / "golden" / "ha_failover_case1.out").read_bytes()
    got = out.read_bytes()
    assert got == golden
    # Invariant: never two leaders
    for ln in lines:
        assert not ("A=leader" in ln and "B=leader" in ln)

