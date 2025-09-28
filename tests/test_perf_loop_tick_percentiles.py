import json
from src.metrics.exporter import Metrics
from tests.e2e._utils import make_metrics_ctx


def test_loop_tick_percentiles_nearest_rank():
    m = make_metrics_ctx()
    m.reset_perf_for_tests()
    # feed durations (ms) to hit several buckets deterministically
    samples = [1, 3, 4, 6, 9, 11, 15, 21, 49, 51, 99, 101, 399, 401, 1599]
    for v in samples:
        m.record_loop_tick('ramp', float(v))
    snap = m._get_perf_snapshot_for_tests()
    loops = snap.get('loops', {})
    r = loops.get('ramp', {})
    assert isinstance(r.get('last_ms'), float)
    # p95 and p99 must be from fixed bucket set and monotone
    p95 = float(r.get('p95_ms', 0.0))
    p99 = float(r.get('p99_ms', 0.0))
    assert p95 <= p99
    # ensure finite and from known bucket boundaries
    assert p95 in (0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
    assert p99 in (0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)


