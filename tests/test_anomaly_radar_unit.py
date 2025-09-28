import json
from tools.soak.anomaly_radar import _median, _mad, detect_anomalies


def test_median_mad_basic():
    xs = [1.0, 2.0, 3.0, 4.0, 100.0]
    med = _median(xs)
    mad = _mad(xs)
    assert med == 3.0
    # deviations: [2,1,0,1,97] => median=1.0
    assert abs(mad - 1.0) < 1e-12


def test_detect_anomalies_kpis():
    buckets = [
        {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
        {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.1},
        {'bucket': '00:30', 'net_bps': -1.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.2},
        {'bucket': '00:45', 'net_bps': 3.1, 'order_age_p95_ms': 295.0, 'taker_share_pct': 12.3},
        {'bucket': '01:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 30.0},
    ]
    anoms = detect_anomalies(buckets, 3.0)
    kinds = [a['kind'] for a in anoms]
    # Expect EDGE at 00:30 (very low net), TAKER at 01:00 (very high taker)
    assert 'EDGE' in kinds and 'TAKER' in kinds


