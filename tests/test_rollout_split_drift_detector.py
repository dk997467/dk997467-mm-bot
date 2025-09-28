def test_rollout_split_drift_detector():
    from src.metrics.exporter import Metrics
    from types import SimpleNamespace
    m = Metrics(SimpleNamespace())
    m.set_rollout_split_pct(50)
    # simulate 9 blue, 1 green -> 10% observed
    for _ in range(9):
        m.inc_rollout_order('blue')
    m.inc_rollout_order('green')
    snap = m._get_rollout_snapshot_for_tests()
    assert snap['split'] == 50
    assert abs(float(snap['observed']) - 10.0) < 1e-6

