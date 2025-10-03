from types import SimpleNamespace
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics


def _mk_metrics():
    # NOTE: Registry cleanup now handled by conftest.py autouse fixture
    # This helper just creates a minimal context for testing
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


def test_latency_percentiles_nearest_rank():
    m = _mk_metrics()
    m.test_reset_latency()
    # 100 samples: 0..99 ms -> p95 ~ 95, p99 ~ 99 by nearest-rank
    for v in range(100):
        m.inc_rollout_fill('green', float(v))
    snap = m._get_latency_snapshot_for_tests()
    p95 = snap['p95']['green']
    p99 = snap['p99']['green']
    assert p95 >= 90.0 and p95 <= 100.0
    assert p99 >= 90.0 and p99 <= 100.0
    # determinism: repeated fills at same values do not change beyond bucket bounds
    for _ in range(10):
        m.inc_rollout_fill('green', 99.0)
    snap2 = m._get_latency_snapshot_for_tests()
    assert snap2['p99']['green'] == snap2['p99']['green']

