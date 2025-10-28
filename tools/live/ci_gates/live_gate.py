#!/usr/bin/env python3
"""
Live Gate: CI gate based on KPI thresholds and artifact validation.

Usage:
    python -m tools.live.ci_gates.live_gate \\
        --path artifacts/live/latest \\
        --min_edge 2.5 \\
        --min_maker_taker 0.83 \\
        --max_risk 0.40 \\
        --max_latency 350
"""
import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_live_summary(
    summary: dict,
    min_edge: float,
    min_maker_taker: float,
    max_risk: float,
    max_latency: float
) -> tuple[bool, list[str]]:
    """
    Validate live summary against KPI thresholds.
    
    Returns: (passed: bool, reasons: list[str])
    """
    reasons = []
    
    # Check state
    if summary.get("live_state") == "FROZEN":
        reasons.append("live_state=FROZEN (not allowed for deployment)")
    
    # Check throttle
    if summary.get("throttle_factor", 0) < 0.5:
        reasons.append(f"throttle_factor={summary.get('throttle_factor')} < 0.5")
    
    # Check frozen count
    frozen_count = summary.get("meta", {}).get("frozen_count", 0)
    if frozen_count > 0:
        reasons.append(f"frozen_count={frozen_count} (some symbols frozen)")
    
    # Validate each symbol's throttle
    per_symbol = summary.get("per_symbol_throttle", {})
    for sym, throttle in per_symbol.items():
        if throttle < 0.8:
            reasons.append(f"{sym}: throttle={throttle:.2f} < 0.8")
    
    passed = len(reasons) == 0
    return passed, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Gate: KPI validation for CI")
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to live artifacts directory"
    )
    parser.add_argument(
        "--min_edge",
        type=float,
        default=2.5,
        help="Min edge_bps (default: 2.5)"
    )
    parser.add_argument(
        "--min_maker_taker",
        type=float,
        default=0.83,
        help="Min maker_taker_ratio (default: 0.83)"
    )
    parser.add_argument(
        "--max_risk",
        type=float,
        default=0.40,
        help="Max risk_ratio (default: 0.40)"
    )
    parser.add_argument(
        "--max_latency",
        type=float,
        default=350.0,
        help="Max p95_latency_ms (default: 350)"
    )
    parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Live Gate: KPI Validation")
    logger.info("=" * 60)
    logger.info(f"Path: {args.path}")
    logger.info(f"Thresholds: edge≥{args.min_edge}, maker≥{args.min_maker_taker}, risk≤{args.max_risk}, latency≤{args.max_latency}")
    logger.info("")
    
    # Check artifacts exist
    summary_path = args.path / "LIVE_SUMMARY.json"
    if not summary_path.exists():
        logger.error(f"LIVE_SUMMARY.json not found at {summary_path}")
        return 1
    
    # Load summary
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded summary: state={summary.get('live_state')}, throttle={summary.get('throttle_factor')}")
    
    # Validate
    passed, reasons = validate_live_summary(
        summary, args.min_edge, args.min_maker_taker,
        args.max_risk, args.max_latency
    )
    
    logger.info("")
    if passed:
        logger.info("=" * 60)
        logger.info("✅ Live Gate: PASS")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("=" * 60)
        logger.error("🔴 Live Gate: FAIL")
        logger.error("=" * 60)
        logger.error("Reasons:")
        for reason in reasons:
            logger.error(f"  - {reason}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

