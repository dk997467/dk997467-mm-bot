import json
from types import SimpleNamespace

import pytest

from src.metrics.exporter import Metrics


class Ctx:
    def __init__(self):
        # minimal cfg stub
        self.cfg = SimpleNamespace(
            strategy=SimpleNamespace(
                levels_per_side=1,
                min_time_in_book_ms=0,
                k_vola_spread=0.0,
                skew_coeff=0.0,
                imbalance_cutoff=0.0,
            ),
            limits=SimpleNamespace(
                max_create_per_sec=0,
                max_cancel_per_sec=0,
            ),
        )


def test_metrics_test_seed_and_snapshot():
    ctx = Ctx()
    m = Metrics(ctx)

    # Start from clean state
    m.test_reset_rollout()
    snap0 = m._get_rollout_snapshot_for_tests()
    assert snap0["fills"].get("blue", 0) == 0
    assert snap0["rejects"].get("green", 0) == 0
    assert snap0["split"] == 0
    assert snap0["observed"] == 0.0

    # Seed counters and latency
    m.test_seed_rollout_counters(
        fills_blue=100,
        fills_green=50,
        rejects_blue=1,
        rejects_green=6,
        split_expected_pct=30,
    )
    m.test_seed_rollout_latency_ms(blue_ms=20.0, green_ms=55.0)

    snap = m._get_rollout_snapshot_for_tests()
    assert snap["fills"]["blue"] == 100
    assert snap["fills"]["green"] == 50
    assert snap["rejects"]["blue"] == 1
    assert snap["rejects"]["green"] == 6
    assert snap["split"] == 30
    assert 0.0 <= snap["observed"] <= 100.0

    # Seed observed explicitly and verify
    m.test_seed_rollout_counters(
        fills_blue=100,
        fills_green=50,
        rejects_blue=1,
        rejects_green=6,
        split_expected_pct=25,
        observed_green_pct=40.0,
    )
    snap2 = m._get_rollout_snapshot_for_tests()
    assert snap2["split"] == 25
    assert snap2["observed"] == 40.0

    # Reset should clear
    m.test_reset_rollout()
    snap3 = m._get_rollout_snapshot_for_tests()
    assert snap3["fills"].get("blue", 0) == 0
    assert snap3["rejects"].get("green", 0) == 0
    assert snap3["split"] == 0
    assert snap3["observed"] == 0.0


