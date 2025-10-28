#!/usr/bin/env python3
"""
Live Mode Runner: Reads KPI from Redis, applies controller FSM, writes reports and exports.

Usage:
    python -m tools.live.run_live \\
        --symbols BTCUSDT,ETHUSDT \\
        --ramp-profile A \\
        --redis-url rediss://... \\
        --env prod \\
        --exchange bybit \\
        --interval-sec 60 \\
        --dry-run
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import redis
except ImportError:
    redis = None

from tools.live.controller import LiveController, LiveState, KPIThresholds, SymbolKPI

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_ramp_profile(profile_name: str) -> Dict:
    """Load ramp profile from profiles/live_profiles.json."""
    profiles_path = Path("profiles/live_profiles.json")
    
    if not profiles_path.exists():
        logger.warning(f"Profiles file not found: {profiles_path}, using defaults")
        return {"max_order_notional": 100, "max_symbols": 1}
    
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    
    if profile_name not in profiles:
        logger.warning(f"Profile '{profile_name}' not found, using 'A'")
        profile_name = "A"
    
    return profiles[profile_name]


def fetch_kpi_from_redis(
    redis_client: Optional["redis.Redis"],
    env: str,
    exchange: str,
    symbols: List[str]
) -> List[SymbolKPI]:
    """
    Fetch latest KPI for symbols from Redis.
    
    Keys: {env}:{exchange}:shadow:summary:{symbol}
    """
    if redis_client is None:
        logger.warning("Redis client not available, returning mock data")
        return [
            SymbolKPI(symbol=sym, edge_bps=3.0, maker_taker_ratio=0.85, 
                     p95_latency_ms=300, risk_ratio=0.35)
            for sym in symbols
        ]
    
    kpis = []
    
    for sym in symbols:
        key = f"{env}:{exchange}:shadow:summary:{sym}"
        try:
            data = redis_client.hgetall(key)
            if not data:
                logger.warning(f"No data for {key}")
                continue
            
            # Decode bytes to str
            data_str = {k.decode('utf-8'): v.decode('utf-8') for k, v in data.items()}
            
            kpi = SymbolKPI(
                symbol=sym,
                edge_bps=float(data_str.get("edge_bps", 0)),
                maker_taker_ratio=float(data_str.get("maker_taker_ratio", 0)),
                p95_latency_ms=float(data_str.get("p95_latency_ms", 0)),
                risk_ratio=float(data_str.get("risk_ratio", 0)),
                anomaly_score=float(data_str.get("anomaly_score", 0)) if "anomaly_score" in data_str else None
            )
            
            kpis.append(kpi)
        except Exception as e:
            logger.error(f"Failed to fetch KPI for {sym}: {e}")
    
    return kpis


def apply_throttle_to_redis(
    redis_client: Optional["redis.Redis"],
    env: str,
    exchange: str,
    symbol: str,
    throttle: float,
    ttl: int
) -> None:
    """Write throttle factor to Redis."""
    if redis_client is None:
        logger.debug(f"Redis not available, skipping throttle write for {symbol}")
        return
    
    key = f"{env}:{exchange}:live:throttle:{symbol}"
    try:
        redis_client.set(key, str(throttle), ex=ttl)
        logger.debug(f"Throttle written: {key} = {throttle}")
    except Exception as e:
        logger.error(f"Failed to write throttle for {symbol}: {e}")


def write_live_state_to_redis(
    redis_client: Optional["redis.Redis"],
    env: str,
    exchange: str,
    state: LiveState,
    ttl: int
) -> None:
    """Write global live state to Redis."""
    if redis_client is None:
        return
    
    key = f"{env}:{exchange}:live:state"
    try:
        redis_client.set(key, state.value, ex=ttl)
        logger.info(f"Live state written: {key} = {state.value}")
    except Exception as e:
        logger.error(f"Failed to write live state: {e}")


def generate_live_summary(
    symbols: List[str],
    profile: Dict,
    controller_state: LiveState,
    throttle_factor: float,
    per_symbol_throttle: Dict[str, float],
    reasons: List[str]
) -> Dict:
    """Generate LIVE_SUMMARY.json."""
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "live_state": controller_state.value,
        "throttle_factor": throttle_factor,
        "ramp_profile": profile,
        "symbols": symbols,
        "per_symbol_throttle": per_symbol_throttle,
        "reasons": reasons,
        "meta": {
            "symbols_count": len(symbols),
            "active_count": sum(1 for t in per_symbol_throttle.values() if t > 0.8),
            "cooldown_count": sum(1 for t in per_symbol_throttle.values() if 0.3 <= t <= 0.8),
            "frozen_count": sum(1 for t in per_symbol_throttle.values() if t < 0.3)
        }
    }


def generate_live_report_md(
    summary: Dict,
    decision: "ControllerDecision"
) -> str:
    """Generate LIVE_REPORT.md."""
    lines = [
        "# Live Mode Report",
        "",
        f"**Generated:** {summary['generated_at_utc']}",
        f"**State:** {summary['live_state']}",
        f"**Global Throttle:** {summary['throttle_factor']:.2f}",
        "",
        "## Ramp Profile",
        "",
        f"- **Profile:** {summary.get('ramp_profile', {})}"

,
        "",
        "## Per-Symbol Throttle",
        "",
        "| Symbol | Throttle | Status |",
        "|--------|----------|--------|"
    ]
    
    for sym, throttle in summary["per_symbol_throttle"].items():
        if throttle > 0.8:
            status = "✅ ACTIVE"
        elif throttle >= 0.3:
            status = "🟡 COOLDOWN"
        else:
            status = "🔴 FROZEN"
        
        lines.append(f"| {sym} | {throttle:.2f} | {status} |")
    
    lines.extend([
        "",
        "## Decision Reasons",
        ""
    ])
    
    for reason in summary["reasons"]:
        lines.append(f"- {reason}")
    
    lines.extend([
        "",
        "## Summary",
        "",
        f"- **Symbols total:** {summary['meta']['symbols_count']}",
        f"- **Active:** {summary['meta']['active_count']}",
        f"- **Cooldown:** {summary['meta']['cooldown_count']}",
        f"- **Frozen:** {summary['meta']['frozen_count']}",
        ""
    ])
    
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live Mode Runner: FSM controller + Redis export"
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated symbols (e.g., BTCUSDT,ETHUSDT)"
    )
    parser.add_argument(
        "--ramp-profile",
        default="A",
        help="Ramp profile name (A, B, C) - default: A"
    )
    parser.add_argument(
        "--redis-url",
        help="Redis URL (e.g., rediss://...)"
    )
    parser.add_argument(
        "--env",
        default="dev",
        choices=["dev", "staging", "prod"],
        help="Environment (default: dev)"
    )
    parser.add_argument(
        "--exchange",
        default="bybit",
        help="Exchange name (default: bybit)"
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=60,
        help="Interval between cycles in seconds (default: 60)"
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=3600,
        help="Redis TTL in seconds (default: 3600)"
    )
    parser.add_argument(
        "--anomaly-threshold",
        type=float,
        default=2.0,
        help="Anomaly score threshold (default: 2.0)"
    )
    parser.add_argument(
        "--min-ok-windows",
        type=int,
        default=12,
        help="Min OK windows before unfreeze (default: 12)"
    )
    parser.add_argument(
        "--unfreeze-after-ok",
        type=int,
        default=24,
        help="Consecutive OK windows needed for unfreeze (hysteresis, default: 24)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: no Redis writes"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations (default: 1, 0=infinite)"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Live Mode Runner")
    logger.info("=" * 60)
    logger.info(f"Symbols: {args.symbols}")
    logger.info(f"Ramp profile: {args.ramp_profile}")
    logger.info(f"Environment: {args.env}")
    logger.info(f"Exchange: {args.exchange}")
    logger.info(f"Interval: {args.interval_sec}s")
    logger.info(f"Dry-run: {args.dry_run}")
    logger.info("")
    
    # Parse symbols
    symbols = [s.strip() for s in args.symbols.split(",")]
    
    # Load profile
    profile = load_ramp_profile(args.ramp_profile)
    logger.info(f"Profile loaded: {profile}")
    
    # Initialize Redis client
    redis_client = None
    if args.redis_url and not args.dry_run:
        if redis is None:
            logger.error("redis-py not installed, cannot connect to Redis")
            return 1
        
        try:
            redis_client = redis.from_url(args.redis_url, decode_responses=False)
            redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            if args.env == "prod":
                return 1
            logger.warning("Continuing without Redis (dev mode)")
    
    # Initialize controller
    thresholds = KPIThresholds(
        anomaly_threshold=args.anomaly_threshold,
        min_ok_windows=args.min_ok_windows,
        unfreeze_after_ok_windows=args.unfreeze_after_ok
    )
    controller = LiveController(thresholds)
    
    # Output directory
    out_dir = Path("artifacts/live/latest")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Main loop
    iteration = 0
    max_iterations = args.iterations
    
    try:
        while True:
            iteration += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"Iteration {iteration}")
            logger.info(f"{'='*60}")
            
            # Fetch KPI from Redis
            kpis = fetch_kpi_from_redis(redis_client, args.env, args.exchange, symbols)
            logger.info(f"Fetched KPI for {len(kpis)} symbols")
            
            # Controller decision
            decision = controller.decide(kpis)
            logger.info(f"Decision: state={decision.next_state}, throttle={decision.throttle_factor:.2f}")
            
            # Apply throttle to Redis
            if not args.dry_run:
                write_live_state_to_redis(redis_client, args.env, args.exchange, decision.next_state, args.ttl)
                for sym, throttle in decision.per_symbol_throttle.items():
                    apply_throttle_to_redis(redis_client, args.env, args.exchange, sym, throttle, args.ttl)
            
            # Generate summary
            summary = generate_live_summary(
                symbols, profile, decision.next_state,
                decision.throttle_factor, decision.per_symbol_throttle,
                decision.reasons
            )
            
            # Write artifacts
            summary_path = out_dir / "LIVE_SUMMARY.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            logger.info(f"Summary written to {summary_path}")
            
            report_md = generate_live_report_md(summary, decision)
            report_path = out_dir / "LIVE_REPORT.md"
            report_path.write_text(report_md, encoding="utf-8")
            logger.info(f"Report written to {report_path}")
            
            decision_path = out_dir / "LIVE_DECISION.json"
            controller.export_decision_to_file(decision, decision_path)
            
            # Check if we should stop
            if max_iterations > 0 and iteration >= max_iterations:
                logger.info(f"Reached max iterations ({max_iterations}), stopping")
                break
            
            # Sleep
            if max_iterations == 0 or iteration < max_iterations:
                logger.info(f"Sleeping for {args.interval_sec}s...")
                time.sleep(args.interval_sec)
    
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    except Exception as e:
        logger.error(f"Error in main loop: {e}", exc_info=True)
        return 1
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("Live Mode Runner: Complete")
    logger.info("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

