#!/usr/bin/env python3
"""Apply tuning parameters from sweep results."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any


def _simulate(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulate tuning application.
    
    Args:
        config: Configuration dict with parameters
    
    Returns:
        Simulation result with deterministic metrics
    """
    if not config:
        return {
            "status": "OK",
            "applied": False,
            "metrics": {
                "edge_bps": 0.0,
                "latency_ms": 0.0,
                "risk": 0.0
            }
        }
    
    # Deterministic simulation based on config
    touch_dwell = config.get("touch_dwell_ms", 25)
    risk_limit = config.get("risk_limit", 0.40)
    
    # Simple linear model for demo
    edge_bps = 3.0 + (30 - touch_dwell) * 0.01
    latency_ms = 200 + touch_dwell * 2
    risk = risk_limit * 0.8
    
    return {
        "status": "OK",
        "applied": True,
        "config": config,
        "metrics": {
            "edge_bps": edge_bps,
            "latency_ms": latency_ms,
            "risk": risk
        }
    }


def main() -> int:
    """
    CLI entry point: reads PARAM_SWEEP.json and generates TUNING_REPORT.json
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Find PARAM_SWEEP.json (check current dir and artifacts/)
    sweep_path = Path("artifacts/PARAM_SWEEP.json")
    if not sweep_path.exists():
        sweep_path = Path("PARAM_SWEEP.json")
    
    if not sweep_path.exists():
        print("[ERROR] PARAM_SWEEP.json not found", flush=True)
        return 1
    
    # Load sweep results
    try:
        with open(sweep_path, 'r', encoding='utf-8') as f:
            sweep = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] Failed to load PARAM_SWEEP.json: {e}", flush=True)
        return 1
    
    # Extract top3_by_net_bps_safe (or fallback to results[0])
    top3 = sweep.get("top3_by_net_bps_safe", [])
    if not top3:
        results = sweep.get("results", [])
        if results:
            top3 = [results[0]]
    
    if not top3:
        print("[ERROR] No results in PARAM_SWEEP.json", flush=True)
        return 1
    
    # Select best candidate (first in top3)
    selected = top3[0]
    
    # Extract params and metrics
    params = selected.get("params", {})
    metrics_data = selected.get("metrics", {})
    
    # Extract all candidates (params only)
    candidates = [c.get("params", {}) for c in sweep.get("top3_by_net_bps_safe", []) if isinstance(c, dict)]
    
    # Build TUNING_REPORT.json
    report = {
        "selected": {
            "params": params
        },
        "metrics": {
            "net_bps": metrics_data.get("net_bps", 0.0),
            "order_age_p95_ms": metrics_data.get("order_age_p95_ms", 0.0),
            "replace_rate_per_min": metrics_data.get("replace_rate_per_min", 0.0),
            "fill_rate": metrics_data.get("fill_rate", 0.0)
        },
        "candidates": candidates
    }
    
    # Write to artifacts/TUNING_REPORT.json
    out_dir = Path("artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "TUNING_REPORT.json"
    
    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"[OK] TUNING_REPORT.json written to {out_path}", flush=True)
    except OSError as e:
        print(f"[ERROR] Failed to write TUNING_REPORT.json: {e}", flush=True)
        return 1
    
    # Write YAML overlay (tools/tuning/overlay_profile.yaml)
    yaml_dir = Path("tools") / "tuning"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = yaml_dir / "overlay_profile.yaml"
    
    # Simple YAML representation of selected params
    yaml_lines = ["# Auto-generated tuning overlay\n", "profile:\n"]
    for key, val in params.items():
        yaml_lines.append(f"  {key}: {val}\n")
    
    try:
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.writelines(yaml_lines)
        print(f"[OK] overlay_profile.yaml written to {yaml_path}", flush=True)
    except OSError as e:
        print(f"[ERROR] Failed to write overlay_profile.yaml: {e}", flush=True)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
