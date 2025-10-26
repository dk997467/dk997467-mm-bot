#!/usr/bin/env python3
"""
Generate Fake SOAK_SUMMARY.json and VIOLATIONS.json for Testing

Используется для alert self-test и локального тестирования.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def generate_crit_summary(out_dir: Path):
    """Generate CRIT-level fake summary and violations."""
    
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "windows": 24,
        "min_windows_required": 24,
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"median": 2.1, "last": 2.0, "trend": "↓", "status": "CRIT"},
                "maker_taker_ratio": {"median": 0.82, "last": 0.81, "trend": "↓", "status": "OK"},
                "p95_latency_ms": {"median": 380, "last": 420, "trend": "↑", "status": "CRIT"},
                "risk_ratio": {"median": 0.38, "last": 0.39, "trend": "≈", "status": "OK"}
            },
            "ETHUSDT": {
                "edge_bps": {"median": 2.8, "last": 2.7, "trend": "≈", "status": "OK"},
                "maker_taker_ratio": {"median": 0.73, "last": 0.71, "trend": "↓", "status": "CRIT"},
                "p95_latency_ms": {"median": 340, "last": 335, "trend": "≈", "status": "OK"},
                "risk_ratio": {"median": 0.35, "last": 0.36, "trend": "≈", "status": "OK"}
            }
        },
        "overall": {
            "crit_count": 3,
            "warn_count": 0,
            "ok_count": 5,
            "verdict": "CRIT"
        },
        "meta": {
            "commit_range": "fake-test",
            "profile": "selftest",
            "source": "generate_fake_summary"
        }
    }
    
    violations = [
        {
            "symbol": "BTCUSDT",
            "metric": "edge_bps",
            "level": "CRIT",
            "window_index": 23,
            "value": 2.0,
            "threshold": 2.5,
            "note": "edge_bps (2.0) < critical threshold (2.5)"
        },
        {
            "symbol": "BTCUSDT",
            "metric": "p95_latency_ms",
            "level": "CRIT",
            "window_index": 24,
            "value": 420.0,
            "threshold": 400.0,
            "note": "p95_latency_ms (420.0) > critical threshold (400.0)"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "maker_taker_ratio",
            "level": "CRIT",
            "window_index": 24,
            "value": 0.71,
            "threshold": 0.75,
            "note": "maker_taker_ratio (0.71) < critical threshold (0.75)"
        }
    ]
    
    # Write files
    summary_path = out_dir / "SOAK_SUMMARY.json"
    violations_path = out_dir / "VIOLATIONS.json"
    
    summary_path.write_text(json.dumps(summary, indent=2))
    violations_path.write_text(json.dumps(violations, indent=2))
    
    print(f"[INFO] Generated CRIT summary: {summary_path}")
    print(f"[INFO] Generated violations: {violations_path}")
    print(f"[INFO] Verdict: CRIT, crit_count=3, symbols=2")


def generate_warn_summary(out_dir: Path):
    """Generate WARN-level fake summary and violations."""
    
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "windows": 24,
        "min_windows_required": 24,
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"median": 2.6, "last": 2.55, "trend": "≈", "status": "WARN"},
                "maker_taker_ratio": {"median": 0.84, "last": 0.84, "trend": "≈", "status": "OK"},
                "p95_latency_ms": {"median": 340, "last": 345, "trend": "≈", "status": "OK"},
                "risk_ratio": {"median": 0.38, "last": 0.39, "trend": "≈", "status": "OK"}
            }
        },
        "overall": {
            "crit_count": 0,
            "warn_count": 1,
            "ok_count": 3,
            "verdict": "WARN"
        },
        "meta": {
            "commit_range": "fake-test",
            "profile": "selftest",
            "source": "generate_fake_summary"
        }
    }
    
    violations = [
        {
            "symbol": "BTCUSDT",
            "metric": "edge_bps",
            "level": "WARN",
            "window_index": 24,
            "value": 2.55,
            "threshold": 2.5,
            "note": "edge_bps (2.55) < warning threshold (2.5)"
        }
    ]
    
    # Write files
    summary_path = out_dir / "SOAK_SUMMARY.json"
    violations_path = out_dir / "VIOLATIONS.json"
    
    summary_path.write_text(json.dumps(summary, indent=2))
    violations_path.write_text(json.dumps(violations, indent=2))
    
    print(f"[INFO] Generated WARN summary: {summary_path}")
    print(f"[INFO] Generated violations: {violations_path}")
    print(f"[INFO] Verdict: WARN, warn_count=1, symbols=1")


def generate_ok_summary(out_dir: Path):
    """Generate OK-level fake summary (no violations)."""
    
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "windows": 24,
        "min_windows_required": 24,
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"median": 3.5, "last": 3.6, "trend": "↑", "status": "OK"},
                "maker_taker_ratio": {"median": 0.86, "last": 0.87, "trend": "≈", "status": "OK"},
                "p95_latency_ms": {"median": 280, "last": 275, "trend": "↓", "status": "OK"},
                "risk_ratio": {"median": 0.33, "last": 0.32, "trend": "↓", "status": "OK"}
            }
        },
        "overall": {
            "crit_count": 0,
            "warn_count": 0,
            "ok_count": 4,
            "verdict": "OK"
        },
        "meta": {
            "commit_range": "fake-test",
            "profile": "selftest",
            "source": "generate_fake_summary"
        }
    }
    
    violations = []
    
    # Write files
    summary_path = out_dir / "SOAK_SUMMARY.json"
    violations_path = out_dir / "VIOLATIONS.json"
    
    summary_path.write_text(json.dumps(summary, indent=2))
    violations_path.write_text(json.dumps(violations, indent=2))
    
    print(f"[INFO] Generated OK summary: {summary_path}")
    print(f"[INFO] Generated violations: {violations_path}")
    print(f"[INFO] Verdict: OK, no violations, symbols=1")


def main():
    parser = argparse.ArgumentParser(description="Generate fake SOAK_SUMMARY.json for testing")
    parser.add_argument("--crit", action="store_true", help="Generate CRIT-level summary")
    parser.add_argument("--warn", action="store_true", help="Generate WARN-level summary")
    parser.add_argument("--ok", action="store_true", help="Generate OK-level summary")
    parser.add_argument("--out", type=Path, default=Path("reports/analysis"), help="Output directory")
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    args.out.mkdir(parents=True, exist_ok=True)
    
    # Default to CRIT if no level specified
    if not (args.crit or args.warn or args.ok):
        args.crit = True
    
    if args.crit:
        generate_crit_summary(args.out)
    elif args.warn:
        generate_warn_summary(args.out)
    elif args.ok:
        generate_ok_summary(args.out)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

