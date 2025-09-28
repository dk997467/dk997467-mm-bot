"""
VIP fee awareness helpers (stdlib-only, deterministic).
"""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FeeTier:
    level: int
    maker_bps: float
    taker_bps: float
    req_30d_usd: float


# Example BYBIT spot tiers (illustrative values)
BYBIT_SPOT_TIERS: List[FeeTier] = [
    FeeTier(level=0, maker_bps=10.0, taker_bps=20.0, req_30d_usd=0.0),
    FeeTier(level=1, maker_bps=8.0, taker_bps=18.0, req_30d_usd=500000.0),
    FeeTier(level=2, maker_bps=6.0, taker_bps=16.0, req_30d_usd=1000000.0),
]


def expected_tier(rolling_30d_usd: float) -> FeeTier:
    x = float(max(0.0, rolling_30d_usd))
    chosen = BYBIT_SPOT_TIERS[0]
    for t in BYBIT_SPOT_TIERS:
        if x >= float(t.req_30d_usd):
            chosen = t
    return chosen


def distance_to_next_tier(rolling_30d_usd: float) -> float:
    x = float(max(0.0, rolling_30d_usd))
    for idx, t in enumerate(BYBIT_SPOT_TIERS):
        if x < float(t.req_30d_usd):
            return float(t.req_30d_usd) - x
    # x >= highest threshold -> top tier reached
    return 0.0


def effective_fee_bps(maker_share: float, taker_share: float, tier: FeeTier) -> float:
    ms = max(0.0, min(1.0, float(maker_share)))
    ts = max(0.0, min(1.0, float(taker_share)))
    if ms + ts == 0:
        return 0.0
    # Normalize shares
    total = ms + ts
    ms /= total
    ts /= total
    eff = ms * float(tier.maker_bps) + ts * float(tier.taker_bps)
    return float(eff)


def effective_cost_bps(maker_share: float, taker_share: float, tier: FeeTier, rebates: bool = True) -> float:
    eff_fee = effective_fee_bps(maker_share, taker_share, tier)
    # If rebates=True and maker_bps < 0, it's rebate; cost may be negative
    # Clamp to sensible bounds [-50, 200] bps
    lo, hi = -50.0, 200.0
    return float(max(lo, min(hi, eff_fee)))


