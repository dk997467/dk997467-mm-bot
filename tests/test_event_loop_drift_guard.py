from tests.e2e._utils import make_metrics_ctx


def test_event_loop_drift_max_updates():
    m = make_metrics_ctx()
    m.reset_perf_for_tests()
    m.set_event_loop_drift(50.0)
    m.set_event_loop_drift(120.0)
    m.set_event_loop_drift(80.0)
    snap = m._get_perf_snapshot_for_tests()
    assert snap.get('event_loop_drift_ms') == 120.0


