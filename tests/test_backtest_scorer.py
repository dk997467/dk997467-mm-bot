import math


def test_scorer_basic_math():
    # Two symbols, simple fills input
    fills = {
        "BTCUSDT": {
            "gross_bps": 10.0,
            "fees_bps": 2.0,
            "taker_share_pct": 25.0,
            "order_age_p95_ms": 100.0,
        },
        "ETHUSDT": {
            "gross_bps": 6.0,
            "fees_bps": 1.0,
            "taker_share_pct": 15.0,
            "order_age_p95_ms": 200.0,
        },
    }

    from tools.backtest.scorer import aggregate_scores

    total = aggregate_scores(fills)
    assert abs(total["gross_bps"] - 8.0) < 1e-12
    assert abs(total["fees_bps"] - 1.5) < 1e-12
    assert abs(total["net_bps"] - (8.0 - 1.5)) < 1e-12
    # taker_share and p95 simple average in this test
    assert abs(total["taker_share_pct"] - 20.0) < 1e-12
    assert abs(total["order_age_p95_ms"] - 150.0) < 1e-12


