"""
Unit tests for VIP fee model (src/common/fees.py).
"""

import math
import pytest

from src.common.fees import FeeTier, BYBIT_SPOT_TIERS, expected_tier, distance_to_next_tier, effective_fee_bps, effective_cost_bps


def _r6(x: float) -> float:
    return round(float(x), 6)


def test_expected_tier_monotonic():
    tiers = BYBIT_SPOT_TIERS
    # Ensure tiers sorted by req_30d_usd and levels increasing
    assert all(tiers[i].req_30d_usd <= tiers[i+1].req_30d_usd for i in range(len(tiers)-1))
    assert all(tiers[i].level <= tiers[i+1].level for i in range(len(tiers)-1))

    # Monotonic selection as rolling_30d_usd increases
    vals = [0.0, tiers[1].req_30d_usd - 1.0, tiers[1].req_30d_usd, tiers[-1].req_30d_usd, tiers[-1].req_30d_usd + 1.0]
    levels = [expected_tier(v).level for v in vals]
    assert levels == sorted(levels)


def test_distance_to_next_tier_edges():
    tiers = BYBIT_SPOT_TIERS
    # Just below tier1 threshold
    x = tiers[1].req_30d_usd - 100.0
    assert _r6(distance_to_next_tier(x)) == _r6(100.0)
    # At exact threshold -> distance to next tier (tier2)
    y = tiers[1].req_30d_usd
    dist = distance_to_next_tier(y)
    assert dist >= 0.0


def test_effective_fee_and_cost_bps():
    maker_share = 0.8
    taker_share = 0.2
    for tier in BYBIT_SPOT_TIERS[:3]:  # VIP0..VIP2
        eff_fee = effective_fee_bps(maker_share, taker_share, tier)
        eff_cost = effective_cost_bps(maker_share, taker_share, tier, rebates=True)
        # Deterministic rounding and sensible bounds
        assert _r6(eff_fee) >= -100.0 and _r6(eff_fee) <= 100.0
        assert _r6(eff_cost) >= -100.0 and _r6(eff_cost) <= 100.0

