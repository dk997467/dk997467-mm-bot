from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_snapshot_cycle_restore():
    cfg = RuntimeGuardConfig(enabled=True, hysteresis_bad_required=2, hysteresis_good_required=1)
    g1 = RuntimeGuard(cfg)
    g1.paused = True
    g1.last_reason_mask = 7
    g1.last_change_ts = 123.456
    snap = g1.to_snapshot()
    g2 = RuntimeGuard(RuntimeGuardConfig())
    g2.load_snapshot(snap)
    assert g2.paused is True
    assert int(g2.last_reason_mask) == 7
    assert float(g2.last_change_ts) == float(snap['last_change_ts'])

