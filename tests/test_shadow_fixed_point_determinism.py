# Fixed-point shadow averages determinism tests
from types import SimpleNamespace


def test_shadow_fixed_point_determinism():
    from src.metrics.exporter import Metrics
    from src.common.di import AppContext

    # Create metrics with dummy context
    ctx = SimpleNamespace(cfg=SimpleNamespace())
    m = Metrics(ctx)

    # Feed a series of samples, including fractional parts
    samples = [
        (1.9, 0.94),   # -> bps_i=1, permille=9
        (2.2, 0.05),   # -> bps_i=2, permille=0
        (-3.7, -0.14), # -> bps_i=-3, permille=-1
        (0.0, 0.0),
        (10.99, 1.99), # -> bps_i=10, permille=19
    ]
    for p, s in samples:
        m.record_shadow_sample("BTCUSDT", p, s)

    # Capture snapshot 1
    snap1 = m.get_shadow_stats()
    last_price = m.shadow_price_diff_bps_last.labels(symbol="BTCUSDT")._value.get()  # type: ignore[attr-defined]
    last_size = m.shadow_size_diff_pct_last.labels(symbol="BTCUSDT")._value.get()  # type: ignore[attr-defined]
    avg_price = m.shadow_price_diff_bps_avg.labels(symbol="BTCUSDT")._value.get()  # type: ignore[attr-defined]
    avg_size = m.shadow_size_diff_pct_avg.labels(symbol="BTCUSDT")._value.get()  # type: ignore[attr-defined]

    # Reset internal fixed-point accumulators and replay on the same instance (determinism)
    m._shadow_sum_price_bps_i.clear()
    m._shadow_sum_size_permille_i.clear()
    m._shadow_count.clear()
    for p, s in samples:
        m.record_shadow_sample("BTCUSDT", p, s)
    snap2 = m.get_shadow_stats()

    # Deterministic snapshots
    assert snap1 == snap2
    # Last values are integer-truncated and permille->pct
    assert abs(float(last_price) - 10.0) <= 1e-9
    assert abs(float(last_size) - 1.9) <= 1e-9
    # Avg uses integer division
    # Sums: price_i: 1+2-3+0+10=10; count=5 => avg=2
    # size_permille_i: 9+0-1+0+19=27; count=5 => avg_permille=5 => 0.5%
    assert abs(float(avg_price) - 2.0) <= 1e-9
    assert abs(float(avg_size) - 0.5) <= 1e-9

    # Exporter snapshot fields
    assert snap1["count"] == 5
    assert abs(snap1["avg_price_diff_bps"] - 2.0) <= 1e-9
    assert abs(snap1["avg_size_diff_pct"] - 0.5) <= 1e-9
