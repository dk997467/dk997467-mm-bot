#!/usr/bin/env python3
"""
E2E test for EDGE_REPORT generation and KPI Gate.

Tests the full flow:
1. Generate extended EDGE_REPORT.json
2. Run KPI Gate validation
3. Verify markers and JSON structure
"""

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

# Workspace root
ROOT_DIR = Path(__file__).resolve().parents[2]


def run_command(cmd: list, env: dict = None, cwd: Path = None):
    """Run command and capture output."""
    result = subprocess.run(
        cmd,
        env=env,
        cwd=cwd or ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
        encoding='utf-8',
        errors='replace'
    )
    return result


def test_edge_report_generation():
    """Test that edge_report.py generates valid JSON with marker."""
    # Prepare test environment
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:00:00Z"
    env["MM_VERSION"] = "test-0.1.0"
    
    # Create minimal mock EDGE_REPORT.json for input
    artifacts_dir = ROOT_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_edge_report = {
        "total": {
            "net_bps": 3.5,
            "gross_bps": 5.0,
            "fees_bps": 1.2,
            "inventory_bps": 0.3,
            "maker_share": 0.92,
            "adverse_bps_p95": 2.5,
            "slippage_bps_p95": 1.8,
            "order_age_p95_ms": 280.0,
            "ws_lag_p95_ms": 95.0,
        }
    }
    
    (artifacts_dir / "EDGE_REPORT.json").write_text(json.dumps(mock_edge_report))
    
    # Run edge_report generator
    output_path = artifacts_dir / "reports" / "EDGE_REPORT_extended.json"
    cmd = [
        sys.executable,
        '-m', 'tools.reports.edge_report',
        '--inputs', str(artifacts_dir / "EDGE_REPORT.json"),
        '--out-json', str(output_path)
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code
    assert result.returncode == 0, f"edge_report failed: {result.stderr}"
    
    # Check marker in output (PROMPT H: updated to diagnostics)
    full_output = result.stdout + '\n' + result.stderr
    assert '| edge_report | OK | FIELDS=diagnostics |' in full_output, \
        "Expected edge_report marker not found"
    
    # Check output file exists and is valid JSON
    assert output_path.exists(), "Output file not created"
    
    with open(output_path, 'r') as f:
        extended_metrics = json.load(f)
    
    # Validate structure
    assert "totals" in extended_metrics
    assert "symbols" in extended_metrics
    assert "runtime" in extended_metrics
    
    # Validate totals
    totals = extended_metrics["totals"]
    assert "net_bps" in totals
    assert "adverse_bps_p95" in totals
    assert "slippage_bps_p95" in totals
    assert "cancel_ratio" in totals
    assert "blocked_ratio" in totals
    
    # PROMPT H: Validate diagnostics fields
    assert "component_breakdown" in totals, "Missing component_breakdown (PROMPT H)"
    assert "neg_edge_drivers" in totals, "Missing neg_edge_drivers (PROMPT H)"
    assert "block_reasons" in totals, "Missing block_reasons (PROMPT H)"
    
    # Validate component_breakdown structure
    breakdown = totals["component_breakdown"]
    assert "gross_bps" in breakdown
    assert "fees_eff_bps" in breakdown
    assert "slippage_bps" in breakdown
    assert "adverse_bps" in breakdown
    assert "inventory_bps" in breakdown
    assert "net_bps" in breakdown
    
    # Validate neg_edge_drivers is a list
    assert isinstance(totals["neg_edge_drivers"], list), "neg_edge_drivers should be a list"
    
    # Validate block_reasons structure
    block_reasons = totals["block_reasons"]
    assert "min_interval" in block_reasons
    assert "concurrency" in block_reasons
    assert "risk" in block_reasons
    assert "throttle" in block_reasons
    
    # Each block_reason should have count and ratio
    for reason in ["min_interval", "concurrency", "risk", "throttle"]:
        assert "count" in block_reasons[reason], f"{reason} missing count"
        assert "ratio" in block_reasons[reason], f"{reason} missing ratio"
    assert "maker_share_pct" in totals
    
    # Check values
    assert totals["net_bps"] == 3.5
    assert totals["maker_share_pct"] == 92.0  # 0.92 * 100
    
    print("[OK] EDGE_REPORT generation test PASSED")


def test_kpi_gate_ok():
    """Test KPI Gate with OK metrics."""
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:01:00Z"
    env["MM_VERSION"] = "test-0.1.0"
    
    # Create mock EDGE_REPORT with OK metrics
    artifacts_dir = ROOT_DIR / "artifacts" / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_metrics = {
        "totals": {
            "net_bps": 3.5,  # OK (> 2.5)
            "adverse_bps_p95": 2.0,  # OK (< 4.0)
            "slippage_bps_p95": 1.5,  # OK (< 3.0)
            "cancel_ratio": 0.30,  # OK (< 0.55)
            "order_age_p95_ms": 280.0,  # OK (< 330)
            "ws_lag_p95_ms": 95.0,  # OK (< 120)
            "maker_share_pct": 92.0,  # OK (> 85)
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T10:00:00Z", "version": "test"}
    }
    
    edge_report_path = artifacts_dir / "EDGE_REPORT_test.json"
    edge_report_path.write_text(json.dumps(mock_metrics))
    
    # Run KPI Gate
    kpi_gate_path = artifacts_dir / "KPI_GATE_test.json"
    cmd = [
        sys.executable,
        '-m', 'tools.ci.validate_readiness',
        '--kpi-gate',
        '--edge-report', str(edge_report_path),
        '--out-json', str(kpi_gate_path)
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code (should be 0 for OK)
    assert result.returncode == 0, f"KPI Gate failed: {result.stderr}"
    
    # Check marker
    full_output = result.stdout + '\n' + result.stderr
    assert '| kpi_gate | OK | THRESHOLDS=APPLIED |' in full_output, \
        "Expected OK marker not found"
    
    # Check JSON output
    assert kpi_gate_path.exists(), "KPI_GATE.json not created"
    
    with open(kpi_gate_path, 'r') as f:
        kpi_result = json.load(f)
    
    assert kpi_result["verdict"] == "OK"
    assert len(kpi_result["reasons"]) == 0
    assert "runtime" in kpi_result
    
    print("[OK] KPI Gate OK test PASSED")


def test_kpi_gate_warn():
    """Test KPI Gate with WARN metrics."""
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:02:00Z"
    
    # Create mock EDGE_REPORT with WARN metrics
    artifacts_dir = ROOT_DIR / "artifacts" / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_metrics = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 5.0,  # WARN (> 4.0, < 6.0)
            "slippage_bps_p95": 4.0,  # WARN (> 3.0, < 5.0)
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 280.0,
            "ws_lag_p95_ms": 95.0,
            "maker_share_pct": 92.0,
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T10:00:00Z", "version": "test"}
    }
    
    edge_report_path = artifacts_dir / "EDGE_REPORT_warn.json"
    edge_report_path.write_text(json.dumps(mock_metrics))
    
    # Run KPI Gate
    kpi_gate_path = artifacts_dir / "KPI_GATE_warn.json"
    cmd = [
        sys.executable,
        '-m', 'tools.ci.validate_readiness',
        '--kpi-gate',
        '--edge-report', str(edge_report_path),
        '--out-json', str(kpi_gate_path)
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code (should be 0 for WARN - PROMPT G fix)
    assert result.returncode == 0, "KPI Gate should exit 0 for WARN (not a failure)"
    
    # Check marker
    full_output = result.stdout + '\n' + result.stderr
    assert '| kpi_gate | WARN |' in full_output, "Expected WARN marker not found"
    assert 'EDGE:adverse' in full_output
    assert 'EDGE:slippage' in full_output
    
    # Check JSON output
    assert kpi_gate_path.exists()
    
    with open(kpi_gate_path, 'r') as f:
        kpi_result = json.load(f)
    
    assert kpi_result["verdict"] == "WARN"
    assert "EDGE:adverse" in kpi_result["reasons"]
    assert "EDGE:slippage" in kpi_result["reasons"]
    
    print("[OK] KPI Gate WARN test PASSED")


def test_kpi_gate_fail():
    """Test KPI Gate with FAIL metrics."""
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:03:00Z"
    
    # Create mock EDGE_REPORT with FAIL metrics
    artifacts_dir = ROOT_DIR / "artifacts" / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_metrics = {
        "totals": {
            "net_bps": 2.0,  # FAIL (< 2.5)
            "adverse_bps_p95": 7.0,  # FAIL (> 6.0)
            "slippage_bps_p95": 1.5,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 280.0,
            "ws_lag_p95_ms": 95.0,
            "maker_share_pct": 80.0,  # FAIL (< 85)
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T10:00:00Z", "version": "test"}
    }
    
    edge_report_path = artifacts_dir / "EDGE_REPORT_fail.json"
    edge_report_path.write_text(json.dumps(mock_metrics))
    
    # Run KPI Gate
    kpi_gate_path = artifacts_dir / "KPI_GATE_fail.json"
    cmd = [
        sys.executable,
        '-m', 'tools.ci.validate_readiness',
        '--kpi-gate',
        '--edge-report', str(edge_report_path),
        '--out-json', str(kpi_gate_path)
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code (should be 1 for FAIL)
    assert result.returncode == 1, "KPI Gate should exit 1 for FAIL"
    
    # Check marker
    full_output = result.stdout + '\n' + result.stderr
    assert '| kpi_gate | FAIL |' in full_output, "Expected FAIL marker not found"
    assert 'EDGE:net_bps' in full_output
    assert 'EDGE:adverse' in full_output
    assert 'EDGE:maker_share' in full_output
    
    # Check JSON output
    assert kpi_gate_path.exists()
    
    with open(kpi_gate_path, 'r') as f:
        kpi_result = json.load(f)
    
    assert kpi_result["verdict"] == "FAIL"
    assert "EDGE:net_bps" in kpi_result["reasons"]
    assert "EDGE:adverse" in kpi_result["reasons"]
    assert "EDGE:maker_share" in kpi_result["reasons"]
    
    print("[OK] KPI Gate FAIL test PASSED")


def test_edge_report_negative_net_bps():
    """Test EDGE_REPORT with negative net_bps (PROMPT H)."""
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:04:00Z"
    env["MM_VERSION"] = "test-0.1.0"
    
    # Create mock EDGE_REPORT with negative net_bps
    artifacts_dir = ROOT_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_edge_report = {
        "total": {
            "net_bps": -2.5,  # Negative!
            "gross_bps": 5.0,
            "fees_bps": 2.0,
            "slippage_bps": 3.5,  # Largest contributor
            "adverse_bps": 2.5,   # Second largest
            "inventory_bps": 0.5,
            "maker_share": 0.88,
        }
    }
    
    (artifacts_dir / "EDGE_REPORT.json").write_text(json.dumps(mock_edge_report))
    
    # Run edge_report generator
    output_path = artifacts_dir / "reports" / "EDGE_REPORT_neg.json"
    cmd = [
        sys.executable,
        '-m', 'tools.reports.edge_report',
        '--inputs', str(artifacts_dir / "EDGE_REPORT.json"),
        '--out-json', str(output_path)
    ]
    
    result = run_command(cmd, env=env)
    
    assert result.returncode == 0, f"edge_report failed: {result.stderr}"
    
    # Load generated report
    with open(output_path, 'r') as f:
        extended_metrics = json.load(f)
    
    totals = extended_metrics["totals"]
    
    # Validate component_breakdown
    breakdown = totals["component_breakdown"]
    assert breakdown["net_bps"] == -2.5, "net_bps should be negative"
    assert breakdown["slippage_bps"] == 3.5
    assert breakdown["adverse_bps"] == 2.5
    
    # Validate neg_edge_drivers (should be non-empty for negative net_bps)
    neg_drivers = totals["neg_edge_drivers"]
    assert isinstance(neg_drivers, list), "neg_edge_drivers should be a list"
    assert len(neg_drivers) > 0, "neg_edge_drivers should not be empty for negative net_bps"
    assert len(neg_drivers) <= 2, "neg_edge_drivers should have max 2 elements"
    
    # Top driver should be slippage_bps (3.5)
    assert neg_drivers[0] == "slippage_bps", f"Expected slippage_bps as top driver, got {neg_drivers[0]}"
    # Second driver should be adverse_bps (2.5)
    if len(neg_drivers) > 1:
        assert neg_drivers[1] == "adverse_bps", f"Expected adverse_bps as second driver, got {neg_drivers[1]}"
    
    print("[OK] Negative net_bps test PASSED (PROMPT H)")


def test_edge_report_with_block_reasons():
    """Test EDGE_REPORT with audit data for block_reasons (PROMPT H)."""
    env = os.environ.copy()
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T10:05:00Z"
    env["MM_VERSION"] = "test-0.1.0"
    
    # Create minimal EDGE_REPORT
    artifacts_dir = ROOT_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    mock_edge_report = {
        "total": {
            "net_bps": 3.0,
            "gross_bps": 5.0,
            "fees_bps": 1.0,
            "maker_share": 0.90,
        }
    }
    
    (artifacts_dir / "EDGE_REPORT.json").write_text(json.dumps(mock_edge_report))
    
    # Create mock audit.jsonl with block reasons
    audit_jsonl = artifacts_dir / "audit.jsonl"
    audit_entries = [
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "concurrency"},
        {"action": "PLACE", "blocked_reason": "risk"},
    ]
    
    with open(audit_jsonl, 'w') as f:
        for entry in audit_entries:
            f.write(json.dumps(entry) + '\n')
    
    # Run edge_report generator with audit data
    output_path = artifacts_dir / "reports" / "EDGE_REPORT_blocked.json"
    cmd = [
        sys.executable,
        '-m', 'tools.reports.edge_report',
        '--inputs', str(artifacts_dir / "EDGE_REPORT.json"),
        '--audit', str(audit_jsonl),
        '--out-json', str(output_path)
    ]
    
    result = run_command(cmd, env=env)
    
    assert result.returncode == 0, f"edge_report failed: {result.stderr}"
    
    # Load generated report
    with open(output_path, 'r') as f:
        extended_metrics = json.load(f)
    
    totals = extended_metrics["totals"]
    
    # Validate block_reasons structure
    block_reasons = totals["block_reasons"]
    
    assert block_reasons["min_interval"]["count"] == 3, "Expected 3 min_interval blocks"
    assert block_reasons["min_interval"]["ratio"] == pytest.approx(0.6, abs=0.01), "Expected 60% min_interval"
    
    assert block_reasons["concurrency"]["count"] == 1, "Expected 1 concurrency block"
    assert block_reasons["concurrency"]["ratio"] == pytest.approx(0.2, abs=0.01), "Expected 20% concurrency"
    
    assert block_reasons["risk"]["count"] == 1, "Expected 1 risk block"
    assert block_reasons["risk"]["ratio"] == pytest.approx(0.2, abs=0.01), "Expected 20% risk"
    
    assert block_reasons["throttle"]["count"] == 0, "Expected 0 throttle blocks"
    assert block_reasons["throttle"]["ratio"] == 0.0, "Expected 0% throttle"
    
    print("[OK] Block reasons test PASSED (PROMPT H)")


if __name__ == '__main__':
    print("=" * 60)
    print("Testing EDGE_REPORT generation...")
    print("=" * 60)
    test_edge_report_generation()
    
    print("\n" + "=" * 60)
    print("Testing KPI Gate OK...")
    print("=" * 60)
    test_kpi_gate_ok()
    
    print("\n" + "=" * 60)
    print("Testing KPI Gate WARN...")
    print("=" * 60)
    test_kpi_gate_warn()
    
    print("\n" + "=" * 60)
    print("Testing KPI Gate FAIL...")
    print("=" * 60)
    test_kpi_gate_fail()
    
    print("\n" + "=" * 60)
    print("Testing negative net_bps...")
    print("=" * 60)
    test_edge_report_negative_net_bps()
    
    print("\n" + "=" * 60)
    print("Testing block reasons...")
    print("=" * 60)
    test_edge_report_with_block_reasons()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED [OK]")
    print("=" * 60)

