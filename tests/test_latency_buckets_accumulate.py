from types import SimpleNamespace
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics


def _mk_metrics():
    try:
        collectors = list(REGISTRY._collector_to_names.keys())  # type: ignore[attr-defined]
        for col in collectors:
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                levels_per_side=1,
                min_time_in_book_ms=0,
                k_vola_spread=0.0,
                skew_coeff=0.0,
                imbalance_cutoff=0.0,
            ),
            limits=SimpleNamespace(max_create_per_sec=0, max_cancel_per_sec=0),
        )
    )
    return Metrics(ctx)


def test_latency_buckets_accumulate_basic():
    m = _mk_metrics()
    m.test_reset_latency()
    # Blue samples map to buckets: 0,5,10,20,50,100,200,400,800,1600,+Inf
    samples = [0.0, 1.0, 5.0, 7.5, 10.0, 15.0, 60.0, 250.0, 401.0, 1600.0, 5000.0]
    for v in samples:
        m.inc_rollout_fill('blue', v)
    snap = m._get_latency_snapshot_for_tests()
    counts_blue = snap['counts']['blue']
    assert sum(counts_blue) == len(samples)
    # Check specific buckets incremented
    # 0.0 and 1.0 and 5.0 should fall into first two buckets; 5000.0 in +Inf
    assert counts_blue[0] >= 1
    assert counts_blue[-1] >= 1
    # cumulative consistency
    cum = 0
    for c in counts_blue:
        cum += c
        assert cum <= len(samples)

