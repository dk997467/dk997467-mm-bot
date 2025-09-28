"""
Test per-color rollout metrics and EWMA latency.
"""
from types import SimpleNamespace


def test_rollout_metrics_and_ewma():
    from src.metrics.exporter import Metrics
    m = Metrics(SimpleNamespace())  # ctx stub
    m.set_rollout_split_pct(30)
    # Orders
    m.inc_rollout_order('blue')
    m.inc_rollout_order('green')
    # Fills with latencies
    m.inc_rollout_fill('blue', 100.0)
    m.inc_rollout_fill('blue', 300.0)  # EWMA alpha=0.3 -> ewma=0.3*300+0.7*100=160
    m.inc_rollout_fill('green', 200.0)
    # Rejects
    m.inc_rollout_reject('green')
    snap = m._get_rollout_snapshot_for_tests()
    assert snap['fills'].get('blue', 0) >= 2
    assert snap['rejects'].get('green', 0) >= 1
    assert abs(snap['latency_ewma'].get('blue', 0.0) - 160.0) < 1e-6


