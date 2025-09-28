"""
CLI: Print one-line VIP fee status (ASCII only, deterministic keys).

Fields:
- tier_now.level, eff_now_bps (rounded 3)
- tier_next.level or "-"
- distance_usd (rounded 0)
- suggestion: "tilt ON"/"tilt OFF" based on cfg thresholds

No external deps. Best-effort: prefer artifacts/metrics.json if present,
otherwise compute from config defaults with rolling_30d_usd = 0.0.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from src.common.config import ConfigLoader
from src.common.fees import (
    BYBIT_SPOT_TIERS,
    FeeTier,
    expected_tier,
    distance_to_next_tier,
    effective_fee_bps,
)


def _artifacts_metrics_path() -> str:
    base = os.environ.get("ARTIFACTS_DIR", "artifacts")
    return os.path.join(base, "metrics.json")


def _read_fees_from_artifacts() -> Optional[dict]:
    try:
        p = _artifacts_metrics_path()
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        fees = data.get("fees")
        if not isinstance(fees, dict):
            return None
        return fees
    except Exception:
        return None


def _find_next_tier(tier_now: FeeTier) -> Optional[FeeTier]:
    try:
        idx = 0
        for i, t in enumerate(BYBIT_SPOT_TIERS):
            if int(t.level) == int(tier_now.level):
                idx = i
                break
        return BYBIT_SPOT_TIERS[idx + 1] if idx + 1 < len(BYBIT_SPOT_TIERS) else None
    except Exception:
        return None


def _round3(x: float) -> float:
    try:
        return float(f"{float(x):.3f}")
    except Exception:
        return 0.0


def _round0(x: float) -> int:
    try:
        return int(round(float(x)))
    except Exception:
        return 0


def main() -> None:
    # Load config
    loader = ConfigLoader()
    try:
        cfg = loader.load()
    except Exception:
        cfg = None

    # Defaults
    maker_share = 0.8
    taker_share = 0.2
    dist_thr = 25000.0
    min_impr = 0.2
    if cfg is not None:
        try:
            dist_thr = float(getattr(getattr(cfg, "fees", object()), "bybit").distance_usd_threshold)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            min_impr = float(getattr(getattr(cfg, "fees", object()), "bybit").min_improvement_bps)  # type: ignore[attr-defined]
        except Exception:
            pass

    # Try artifacts first
    fees_art = _read_fees_from_artifacts()
    if isinstance(fees_art, dict):
        try:
            tier_now_d = fees_art.get("tier_now") or {}
            tier_next_d = fees_art.get("tier_next")
            level_now = int(float(tier_now_d.get("level", 0.0)))
            eff_now = float(fees_art.get("effective_fee_bps_now", 0.0))
            dist_usd = float(fees_art.get("distance_usd", 0.0))
            if isinstance(tier_next_d, dict):
                level_next = int(float(tier_next_d.get("level", 0.0)))
            else:
                level_next = "-"
            # Suggestion based on thresholds; need eff_next if present
            eff_next = float(fees_art.get("effective_fee_bps_next", 0.0))
            improvement = eff_now - eff_next if isinstance(level_next, int) else 0.0
            suggest_on = (dist_usd <= dist_thr) and (improvement >= min_impr) and isinstance(level_next, int)
            line = (
                f"tier_now={level_now} eff_now_bps={_round3(eff_now):.3f} "
                f"tier_next={level_next if level_next == '-' else int(level_next)} "
                f"distance_usd={_round0(dist_usd)} suggestion={'tilt ON' if suggest_on else 'tilt OFF'}"
            )
            print(line)
            return
        except Exception:
            # fall back to compute below
            pass

    # Compute from functions (rolling_30d_usd unknown -> assume 0.0)
    rolling = 0.0
    tier_now = expected_tier(rolling)
    tier_next = _find_next_tier(tier_now)
    dist_usd = distance_to_next_tier(rolling)
    eff_now = effective_fee_bps(maker_share, taker_share, tier_now)
    eff_next = effective_fee_bps(maker_share, taker_share, tier_next) if tier_next else eff_now
    improvement = eff_now - eff_next if tier_next else 0.0
    suggest_on = (dist_usd <= dist_thr) and (improvement >= min_impr) and (tier_next is not None)
    line = (
        f"tier_now={int(tier_now.level)} eff_now_bps={_round3(eff_now):.3f} "
        f"tier_next={'-' if tier_next is None else int(tier_next.level)} "
        f"distance_usd={_round0(dist_usd)} suggestion={'tilt ON' if suggest_on else 'tilt OFF'}"
    )
    print(line)


if __name__ == "__main__":
    main()


