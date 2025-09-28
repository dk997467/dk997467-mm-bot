"""
Fee tier metrics writer (stdlib-only).
"""

from typing import Dict, Optional
from src.common.fees import FeeTier


class FeeTierMetricsWriter:
    def __init__(self, registry: Optional[object] = None) -> None:
        self._r = registry
        self._last_level: int = 0
        self._last_expected_bps: float = 0.0
        self._last_distance_usd: float = 0.0
        self._last_effective_now: float = 0.0

    def publish(self, *, tier: FeeTier, distance_usd: float, eff_fee_bps_now: float) -> None:
        self._last_level = int(tier.level)
        self._last_expected_bps = float(tier.maker_bps)  # expected baseline maker bps proxy
        self._last_distance_usd = float(distance_usd)
        self._last_effective_now = float(eff_fee_bps_now)
        try:
            if self._r is None:
                return
            if hasattr(self._r, 'fee_tier_level'):
                self._r.fee_tier_level.set(self._last_level)
            if hasattr(self._r, 'fee_tier_expected_bps'):
                self._r.fee_tier_expected_bps.set(float(tier.maker_bps))
            if hasattr(self._r, 'fee_tier_distance_usd'):
                self._r.fee_tier_distance_usd.set(self._last_distance_usd)
            if hasattr(self._r, 'effective_fee_bps_now'):
                self._r.effective_fee_bps_now.set(self._last_effective_now)
        except Exception:
            pass

    def snapshot(self, *, tier: FeeTier, dist_usd: float, eff_bps: float) -> Dict[str, float]:
        return {
            'level': float(int(tier.level)),
            'maker_bps': float(tier.maker_bps),
            'taker_bps': float(tier.taker_bps),
            'distance_usd': float(dist_usd),
            'effective_fee_bps_now': float(eff_bps),
        }


