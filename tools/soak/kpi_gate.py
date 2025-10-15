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


def main():
    """CLI entry point for testing."""
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python -m tools.soak.kpi_gate <ITER_SUMMARY.json>")
        print("       python -m tools.soak.kpi_gate --test")
        return 1
    
    if sys.argv[1] == "--test":
        # Run self-test
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
    
    # Load ITER_SUMMARY and check KPI gate
    summary_path = sys.argv[1]
    try:
        with open(summary_path, 'r') as f:
            data = json.load(f)
        
        summary = data.get("summary", {})
        
        # Check gate
        mode = sys.argv[2] if len(sys.argv) > 2 else "hard"
        result = kpi_gate_check(summary, mode=mode)
        
        # Print summary
        print(format_kpi_summary(summary, result))
        
        if result["verdict"] == "FAIL":
            print(f"❌ KPI Gate FAILED: {result['reason']}")
            return 1
        elif result["verdict"] == "WARN":
            print(f"⚠️ KPI Gate WARNING: {result['reason']}")
            return 0  # Continue on warnings
        else:
            print(f"✅ KPI Gate PASSED")
            return 0
    
    except Exception as e:
        print(f"❌ Error reading {summary_path}: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
