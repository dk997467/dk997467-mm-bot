#!/usr/bin/env python3
"""
KPI Gate Helper for Soak Tests.

Centralized KPI validation with soft/hard thresholds.

Usage:
    from tools.soak.kpi_gate import kpi_gate_ok, kpi_gate_check
    
    # Simple OK/FAIL check
    if not kpi_gate_ok(metrics):
        print("KPI gate failed!")
        exit(1)
    
    # Detailed check with soft/hard thresholds
    result = kpi_gate_check(metrics, mode="hard")
    if result["verdict"] == "FAIL":
        print(result["reason"])
        exit(1)
"""

from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path


# ==============================================================================
# KPI THRESHOLDS
# ==============================================================================

# Hard thresholds (gate fails, job exits)
HARD_THRESHOLDS = {
    "risk_ratio": 0.50,  # 50% max
    "maker_taker_ratio": 0.85,  # 85% min
    "net_bps": 2.0,  # 2.0 BPS min
    "p95_latency_ms": 400,  # 400ms max
}

# Soft thresholds (warning, job continues)
SOFT_THRESHOLDS = {
    "risk_ratio": 0.40,  # 40% warning
    "maker_taker_ratio": 0.90,  # 90% target
    "net_bps": 2.7,  # 2.7 BPS target
    "p95_latency_ms": 350,  # 350ms target
}


def kpi_gate_ok(metrics: Dict[str, Any]) -> bool:
    """
    Simple boolean KPI gate check (hard thresholds).
    
    Args:
        metrics: Dict with risk_ratio, maker_taker_ratio, net_bps, p95_latency_ms
    
    Returns:
        True if all KPIs pass hard thresholds
    
    Example:
        >>> kpi_gate_ok({"risk_ratio": 0.42, "maker_taker_ratio": 0.88, "net_bps": 3.0, "p95_latency_ms": 300})
        True
        >>> kpi_gate_ok({"risk_ratio": 0.60, "maker_taker_ratio": 0.88, "net_bps": 3.0, "p95_latency_ms": 300})
        False
    """
    risk = metrics.get("risk_ratio", 1.0)
    maker_taker = metrics.get("maker_taker_ratio", 0.0)
    net = metrics.get("net_bps", 0.0)
    latency = metrics.get("p95_latency_ms", 9999)
    
    return (
        risk <= HARD_THRESHOLDS["risk_ratio"] and
        maker_taker >= HARD_THRESHOLDS["maker_taker_ratio"] and
        net >= HARD_THRESHOLDS["net_bps"] and
        latency <= HARD_THRESHOLDS["p95_latency_ms"]
    )


def kpi_gate_check(
    metrics: Dict[str, Any],
    mode: str = "soft"
) -> Dict[str, Any]:
    """
    Detailed KPI gate check with soft/hard thresholds.
    
    Args:
        metrics: Dict with KPI values
        mode: "soft" (warnings) or "hard" (strict)
    
    Returns:
        Dict with:
            - verdict: "OK" | "WARN" | "FAIL"
            - reason: str (explanation)
            - violations: list of failed checks
            - warnings: list of soft threshold violations
    
    Example:
        >>> result = kpi_gate_check({"risk_ratio": 0.45, "net_bps": 2.5}, mode="soft")
        >>> result["verdict"]
        'WARN'
        >>> result["warnings"]
        ['risk_ratio 0.450 > 0.400 (soft)']
    """
    risk = metrics.get("risk_ratio", 1.0)
    maker_taker = metrics.get("maker_taker_ratio", 0.0)
    net = metrics.get("net_bps", 0.0)
    latency = metrics.get("p95_latency_ms", 9999)
    
    violations = []
    warnings = []
    
    # Check hard thresholds (always checked)
    if risk > HARD_THRESHOLDS["risk_ratio"]:
        violations.append(f"risk_ratio {risk:.3f} > {HARD_THRESHOLDS['risk_ratio']:.3f} (hard)")
    
    if maker_taker < HARD_THRESHOLDS["maker_taker_ratio"]:
        violations.append(f"maker_taker_ratio {maker_taker:.3f} < {HARD_THRESHOLDS['maker_taker_ratio']:.3f} (hard)")
    
    if net < HARD_THRESHOLDS["net_bps"]:
        violations.append(f"net_bps {net:.2f} < {HARD_THRESHOLDS['net_bps']:.2f} (hard)")
    
    if latency > HARD_THRESHOLDS["p95_latency_ms"]:
        violations.append(f"p95_latency_ms {latency:.0f} > {HARD_THRESHOLDS['p95_latency_ms']:.0f} (hard)")
    
    # If any hard violations, return FAIL immediately
    if violations:
        return {
            "verdict": "FAIL",
            "reason": "; ".join(violations),
            "violations": violations,
            "warnings": []
        }
    
    # Check soft thresholds (mode=soft only)
    if mode == "soft":
        if risk > SOFT_THRESHOLDS["risk_ratio"]:
            warnings.append(f"risk_ratio {risk:.3f} > {SOFT_THRESHOLDS['risk_ratio']:.3f} (soft)")
        
        if maker_taker < SOFT_THRESHOLDS["maker_taker_ratio"]:
            warnings.append(f"maker_taker_ratio {maker_taker:.3f} < {SOFT_THRESHOLDS['maker_taker_ratio']:.3f} (soft)")
        
        if net < SOFT_THRESHOLDS["net_bps"]:
            warnings.append(f"net_bps {net:.2f} < {SOFT_THRESHOLDS['net_bps']:.2f} (soft)")
        
        if latency > SOFT_THRESHOLDS["p95_latency_ms"]:
            warnings.append(f"p95_latency_ms {latency:.0f} > {SOFT_THRESHOLDS['p95_latency_ms']:.0f} (soft)")
    
    # Determine verdict
    if warnings:
        return {
            "verdict": "WARN",
            "reason": "; ".join(warnings),
            "violations": [],
            "warnings": warnings
        }
    
    return {
        "verdict": "OK",
        "reason": "All KPIs within thresholds",
        "violations": [],
        "warnings": []
    }


def format_kpi_summary(metrics: Dict[str, Any], result: Dict[str, Any]) -> str:
    """
    Format KPI gate result as one-line summary.
    
    Returns:
        Formatted string like: "| kpi_gate | status=OK | net=3.2 risk=35.0% latency=280ms |"
    """
    risk = metrics.get("risk_ratio", 1.0)
    net = metrics.get("net_bps", 0.0)
    latency = metrics.get("p95_latency_ms", 0)
    maker_taker = metrics.get("maker_taker_ratio", 0.0)
    
    return (
        f"| kpi_gate | status={result['verdict']} | "
        f"net={net:.1f} risk={risk*100:.1f}% "
        f"maker_taker={maker_taker:.2f} latency={latency:.0f}ms |"
    )


def eval_weekly(rollup: Dict[str, Any]) -> tuple[bool, str]:
    """
    Evaluate WEEKLY_ROLLUP.json KPIs.
    
    Args:
        rollup: Parsed WEEKLY_ROLLUP.json
    
    Returns:
        (pass: bool, reason: str)
    """
    net_bps = rollup.get("edge_net_bps", {}).get("median", 0.0)
    p95_ms = rollup.get("order_age_p95_ms", {}).get("median", 9999.0)
    taker = rollup.get("taker_share_pct", {}).get("median", 100.0)  # %
    trend = bool(rollup.get("regress_guard", {}).get("trend_ok", False))
    
    maker_ratio = (100.0 - float(taker)) / 100.0
    
    ok = (net_bps >= 2.7 and p95_ms <= 350.0 and maker_ratio >= 0.85 and trend)
    
    if ok:
        return True, ""
    else:
        return False, f"bad_kpi(net_bps={net_bps}, p95_ms={p95_ms}, maker_ratio={maker_ratio:.2f}, trend_ok={trend})"


def eval_iter(summary: Dict[str, Any]) -> tuple[bool, str]:
    """
    Evaluate ITER_SUMMARY.json KPIs.
    
    Args:
        summary: Parsed ITER_SUMMARY.json["summary"]
    
    Returns:
        (pass: bool, reason: str)
    """
    risk = summary.get("risk_ratio", 1.0)
    mkr = summary.get("maker_taker_ratio", 0.0)
    nbps = summary.get("net_bps", 0.0)
    p95 = summary.get("p95_latency_ms", 9999.0)
    
    ok = (risk <= 0.42 and mkr >= 0.85 and nbps >= 2.7 and p95 <= 350.0)
    
    if ok:
        return True, ""
    else:
        return False, f"bad_kpi(risk={risk:.2f}, mkr={mkr:.2f}, net_bps={nbps}, p95={p95})"


def main():
    """
    CLI entry point with auto-detect mode.
    
    Usage:
        python -m tools.soak.kpi_gate                     # Auto-detect
        python -m tools.soak.kpi_gate <path>              # Positional path
        python -m tools.soak.kpi_gate --weekly <path>     # Weekly rollup
        python -m tools.soak.kpi_gate --iter <path>       # Iteration summary
        python -m tools.soak.kpi_gate --test              # Self-test
    
    Exit codes:
        0 = PASS
        1 = FAIL or error
    """
    import sys
    import json
    from pathlib import Path
    
    # Parse arguments
    mode = None  # "weekly", "iter", "test", or auto-detect
    target_path = None
    
    if len(sys.argv) == 1:
        # Auto-detect mode
        mode = "auto"
    elif sys.argv[1] == "--test":
        mode = "test"
    elif sys.argv[1] == "--weekly":
        mode = "weekly"
        target_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    elif sys.argv[1] == "--iter":
        mode = "iter"
        target_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    else:
        # Positional path
        mode = "auto"
        target_path = Path(sys.argv[1])
    
    # Handle --test mode
    if mode == "test":
        test_metrics = {
            "risk_ratio": 0.35,
            "maker_taker_ratio": 0.92,
            "net_bps": 3.2,
            "p95_latency_ms": 280
        }
        
        result = kpi_gate_check(test_metrics, mode="soft")
        print(format_kpi_summary(test_metrics, result))
        print(f"Result: {result}")
        
        return 0 if result["verdict"] != "FAIL" else 1
    
    # Auto-detect file if not specified
    if mode == "auto" and target_path is None:
        # Try WEEKLY_ROLLUP.json first
        weekly_path = Path("artifacts") / "WEEKLY_ROLLUP.json"
        if weekly_path.exists():
            target_path = weekly_path
            mode = "weekly"
        else:
            # Try latest ITER_SUMMARY_*.json
            iter_dir = Path("artifacts") / "soak" / "latest"
            if iter_dir.exists():
                iter_files = sorted(
                    iter_dir.glob("ITER_SUMMARY_*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if iter_files:
                    target_path = iter_files[0]
                    mode = "iter"
    
    # If still no file found, print usage and exit
    if target_path is None or not target_path.exists():
        print("Usage: python -m tools.soak.kpi_gate [<path>|--weekly <path>|--iter <path>|--test]")
        print("No KPI file found for auto-detect mode")
        return 1
    
    # Auto-detect mode based on filename if not explicitly set
    if mode == "auto":
        if "WEEKLY_ROLLUP" in target_path.name:
            mode = "weekly"
        elif "ITER_SUMMARY" in target_path.name:
            mode = "iter"
        else:
            # Default to iter mode
            mode = "iter"
    
    # Load and evaluate
    try:
        with open(target_path, 'r') as f:
            data = json.load(f)
        
        # Extract metrics for KPI_GATE.json
        metrics_dict = {}
        
        if mode == "weekly":
            ok, reason = eval_weekly(data)
            result_mode = "weekly"
            # Extract weekly metrics
            metrics_dict = {
                "edge_net_bps_median": data.get("edge_net_bps", {}).get("median", 0.0),
                "order_age_p95_ms_median": data.get("order_age_p95_ms", {}).get("median", 0.0),
                "taker_share_pct_median": data.get("taker_share_pct", {}).get("median", 0.0),
                "maker_ratio": 1.0 - (data.get("taker_share_pct", {}).get("median", 0.0) / 100.0),
                "trend_ok": bool(data.get("regress_guard", {}).get("trend_ok", False)),
            }
        else:  # iter
            summary = data.get("summary", data)  # Support both wrapped and unwrapped
            ok, reason = eval_iter(summary)
            result_mode = "iter"
            # Extract iter metrics
            metrics_dict = {
                "risk_ratio": summary.get("risk_ratio", 1.0),
                "maker_taker_ratio": summary.get("maker_taker_ratio", 0.0),
                "net_bps": summary.get("net_bps", 0.0),
                "p95_latency_ms": summary.get("p95_latency_ms", 0.0),
            }
        
        # Write KPI_GATE.json artifact
        from tools.common import jsonx
        
        verdict = "PASS" if ok else "FAIL"
        
        kpi_gate_output = {
            "mode": result_mode,
            "ok": bool(ok),
            "exit_code": 0 if ok else 1,
            "verdict": verdict,
            "reason": reason or "",
            "source_path": str(target_path),
            "metrics": metrics_dict,
            "ts_iso": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        
        out_dir = Path("artifacts")
        out_dir.mkdir(parents=True, exist_ok=True)
        jsonx.write_json(out_dir / "KPI_GATE.json", kpi_gate_output)
        
        # Print result
        if ok:
            print(f"KPI_GATE: PASS {result_mode}")
            return 0
        else:
            print(f"KPI_GATE: FAIL {result_mode} {reason}")
            return 1
    
    except Exception as e:
        print(f"KPI_GATE: FAIL error reading {target_path}: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
