#!/usr/bin/env python3
"""
Risk Monitor CLI: Demo and testing interface for RuntimeRiskMonitor.

Usage:
    python -m tools.live.risk_monitor_cli --demo --max-inv 10000 --max-total 50000 --edge-threshold 1.5
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from tools.live.risk_monitor import RuntimeRiskMonitor


def _get_current_utc_iso() -> str:
    """Get current UTC ISO timestamp (deterministic if MM_FREEZE_UTC_ISO is set)."""
    frozen = os.environ.get('MM_FREEZE_UTC_ISO')
    if frozen:
        return frozen
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_demo(
    max_inv: float,
    max_total: float,
    edge_threshold: float
) -> dict:
    """
    Run a demo scenario showing risk monitor functionality.
    
    Args:
        max_inv: Maximum inventory per symbol (USD)
        max_total: Maximum total notional (USD)
        edge_threshold: Edge freeze threshold (BPS)
    
    Returns:
        Report dictionary with status, frozen state, positions, and metrics
    """
    # Create monitor
    monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=max_inv,
        max_total_notional_usd=max_total,
        edge_freeze_threshold_bps=edge_threshold,
        get_mark_price=lambda sym: {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}.get(sym, 1.0)
    )
    
    # Scenario 1: Place order within limits (should succeed)
    check1 = monitor.check_before_order("BTCUSDT", "buy", 0.1, 50000.0)
    
    # Fill the order
    if check1:
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
    
    # Scenario 2: Place order that would exceed per-symbol limit (should block)
    check2 = monitor.check_before_order("BTCUSDT", "buy", 0.15, 50000.0)
    
    # Scenario 3: Place order on another symbol within limits
    check3 = monitor.check_before_order("ETHUSDT", "buy", 1.0, 3000.0)
    
    if check3:
        monitor.on_fill("ETHUSDT", "buy", 1.0, 3000.0)
    
    # Scenario 4: Edge degradation below threshold -> auto-freeze
    monitor.on_edge_update("BTCUSDT", 1.2)  # Below 1.5 BPS threshold
    
    # Scenario 5: Try to place order after freeze (should block)
    check4 = monitor.check_before_order("ETHUSDT", "sell", 0.5, 3000.0)
    
    # Build report
    report = {
        "frozen": monitor.is_frozen(),
        "metrics": {
            "blocks_total": monitor.blocks_total,
            "freezes_total": monitor.freezes_total,
            "last_freeze_reason": monitor.last_freeze_reason,
            "last_freeze_symbol": monitor.last_freeze_symbol
        },
        "positions": monitor.get_positions(),
        "runtime": {
            "utc": _get_current_utc_iso(),
            "version": "0.1.0"
        },
        "status": "OK"
    }
    
    return report


def main(argv=None):
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Risk Monitor CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run demo scenario
    python -m tools.live.risk_monitor_cli --demo --max-inv 10000 --max-total 50000 --edge-threshold 1.5
    
    # Run demo with frozen time (for testing)
    MM_FREEZE_UTC_ISO="2025-01-01T00:00:00Z" python -m tools.live.risk_monitor_cli --demo
"""
    )
    
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run demo scenario"
    )
    parser.add_argument(
        "--max-inv",
        type=float,
        default=10000.0,
        help="Maximum inventory per symbol (USD)"
    )
    parser.add_argument(
        "--max-total",
        type=float,
        default=50000.0,
        help="Maximum total notional (USD)"
    )
    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=1.5,
        help="Edge freeze threshold (BPS)"
    )
    
    args = parser.parse_args(argv)
    
    if not args.demo:
        parser.print_help()
        return 0
    
    # Run demo
    report = run_demo(args.max_inv, args.max_total, args.edge_threshold)
    
    # Print JSON report
    json_str = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    sys.stdout.write(json_str)
    sys.stdout.write('\n')
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

