"""
E2E Test: CI Safe Mode (KPI Gate + Missing Secrets)

Verifies that validation steps work in safe-mode when secrets are missing,
and KPI Gate produces correct markers and JSON output.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_validate_stack_safe_mode_no_secrets():
    """Test validate_stack in safe-mode without secrets."""
    print("\n" + "=" * 60)
    print("Testing validate_stack safe-mode (no secrets)")
    print("=" * 60)
    
    # Clean up artifacts
    artifacts_dir = ROOT_DIR / "artifacts" / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    # Create dummy files for validation
    (artifacts_dir / "readiness.json").write_text(json.dumps({"score": 100.0, "verdict": "GO"}))
    (artifacts_dir / "gates_summary.json").write_text(json.dumps({"passed": True}))
    
    env = os.environ.copy()
    env["MM_ALLOW_MISSING_SECRETS"] = "1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T12:00:00Z"
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    # Run validate_stack with --allow-missing-secrets
    cmd = [
        sys.executable,
        "-m",
        "tools.ci.validate_stack",
        "--emit-stack-summary",
        "--allow-missing-secrets",
        "--allow-missing-sections",
        "--readiness-file", str(artifacts_dir / "readiness.json"),
        "--gates-file", str(artifacts_dir / "gates_summary.json"),
        "--tests-file", str(artifacts_dir / "tests_summary.json"),  # Missing file
    ]
    
    result = subprocess.run(
        cmd,
        env=env,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(f"Exit code: {result.returncode}", file=sys.stderr)
    print(f"STDOUT:\n{result.stdout}", file=sys.stderr)
    
    # Should succeed
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Parse JSON output (first line before marker)
    output_lines = result.stdout.strip().split('\n')
    json_line = output_lines[0]  # First line is JSON
    output_json = json.loads(json_line)
    assert output_json["ok"] is True, "Overall status should be OK"
    
    # Check tests_whitelist section
    tests_section = next((s for s in output_json["sections"] if s["name"] == "tests_whitelist"), None)
    assert tests_section is not None, "tests_whitelist section not found"
    assert tests_section["ok"] is True, "tests_whitelist should be OK"
    assert tests_section["details"] == "SKIPPED_NO_SECRETS", "tests_whitelist should be SKIPPED_NO_SECRETS"
    
    # Check for marker in output
    full_output = result.stdout + '\n' + result.stderr
    assert '| full_stack |' in full_output, "Expected '| full_stack |' marker"
    assert 'STACK=GREEN' in full_output, "Expected 'STACK=GREEN' marker"
    
    print("[OK] validate_stack safe-mode test PASSED")


def test_full_stack_validate_safe_mode():
    """Test full_stack_validate in safe-mode."""
    print("\n" + "=" * 60)
    print("Testing full_stack_validate safe-mode")
    print("=" * 60)
    
    env = os.environ.copy()
    env["MM_ALLOW_MISSING_SECRETS"] = "1"
    env["FULL_STACK_VALIDATION_FAST"] = "1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T12:00:00Z"
    env["FIXTURES_DIR"] = "tests/fixtures"
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    cmd = [
        sys.executable,
        "-m",
        "tools.ci.full_stack_validate",
        "--allow-missing-secrets",
        "--allow-missing-sections",
    ]
    
    result = subprocess.run(
        cmd,
        env=env,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(f"Exit code: {result.returncode}", file=sys.stderr)
    
    # Should succeed
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    full_output = result.stdout + '\n' + result.stderr
    
    # Check for RESULT=OK
    assert "RESULT=OK" in full_output, "Expected 'RESULT=OK' in output"
    
    # Check for final marker
    assert '| full_stack |' in full_output, "Expected '| full_stack |' marker"
    assert 'STACK=GREEN' in full_output or 'STACK=RED' in full_output, "Expected STACK status"
    
    print("[OK] full_stack_validate safe-mode test PASSED")


def test_kpi_gate_with_good_metrics():
    """Test KPI Gate with good metrics (should be OK)."""
    print("\n" + "=" * 60)
    print("Testing KPI Gate with good metrics")
    print("=" * 60)
    
    # Create mock EDGE_REPORT with good metrics
    edge_report = {
        "totals": {
            "net_bps": 3.5,  # Good
            "adverse_bps_p95": 2.0,  # Good
            "slippage_bps_p95": 1.5,  # Good
            "cancel_ratio": 0.30,  # Good
            "order_age_p95_ms": 280,  # Good
            "ws_lag_p95_ms": 90,  # Good
            "maker_share_pct": 92.0  # Good
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T12:00:00Z", "version": "test"}
    }
    
    edge_report_path = ROOT_DIR / "artifacts" / "reports" / "EDGE_REPORT.json"
    edge_report_path.parent.mkdir(parents=True, exist_ok=True)
    edge_report_path.write_text(json.dumps(edge_report, indent=2))
    
    kpi_gate_path = ROOT_DIR / "artifacts" / "reports" / "KPI_GATE.json"
    if kpi_gate_path.exists():
        kpi_gate_path.unlink()
    
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    cmd = [
        sys.executable,
        "-m",
        "tools.ci.validate_readiness",
        "--kpi-gate",
        "--edge-report", str(edge_report_path),
        "--out-json", str(kpi_gate_path),
    ]
    
    result = subprocess.run(
        cmd,
        env=env,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(f"Exit code: {result.returncode}", file=sys.stderr)
    print(f"STDOUT:\n{result.stdout}", file=sys.stderr)
    
    # Should succeed
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check for OK marker
    assert "| kpi_gate | OK | THRESHOLDS=APPLIED |" in result.stdout, "Expected OK marker"
    
    # Check KPI_GATE.json was created
    assert kpi_gate_path.exists(), "KPI_GATE.json should be created"
    
    kpi_gate_data = json.loads(kpi_gate_path.read_text())
    assert kpi_gate_data["verdict"] == "OK", "Verdict should be OK"
    assert len(kpi_gate_data["reasons"]) == 0, "Should have no reasons for OK"
    
    print("[OK] KPI Gate with good metrics test PASSED")


def test_kpi_gate_with_warnings():
    """Test KPI Gate with some metrics in WARN range."""
    print("\n" + "=" * 60)
    print("Testing KPI Gate with warnings")
    print("=" * 60)
    
    # Create mock EDGE_REPORT with some warnings
    edge_report = {
        "totals": {
            "net_bps": 3.5,
            "adverse_bps_p95": 4.5,  # WARN (> 4.0)
            "slippage_bps_p95": 1.5,
            "cancel_ratio": 0.30,
            "order_age_p95_ms": 340,  # WARN (> 330)
            "ws_lag_p95_ms": 90,
            "maker_share_pct": 92.0
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T12:00:00Z", "version": "test"}
    }
    
    edge_report_path = ROOT_DIR / "artifacts" / "reports" / "EDGE_REPORT.json"
    edge_report_path.parent.mkdir(parents=True, exist_ok=True)
    edge_report_path.write_text(json.dumps(edge_report, indent=2))
    
    kpi_gate_path = ROOT_DIR / "artifacts" / "reports" / "KPI_GATE.json"
    if kpi_gate_path.exists():
        kpi_gate_path.unlink()
    
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    cmd = [
        sys.executable,
        "-m",
        "tools.ci.validate_readiness",
        "--kpi-gate",
        "--edge-report", str(edge_report_path),
        "--out-json", str(kpi_gate_path),
    ]
    
    result = subprocess.run(
        cmd,
        env=env,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(f"Exit code: {result.returncode}", file=sys.stderr)
    print(f"STDOUT:\n{result.stdout}", file=sys.stderr)
    
    # Should succeed (WARN doesn't fail)
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check for WARN marker
    assert "| kpi_gate | WARN |" in result.stdout, "Expected WARN marker"
    assert "EDGE:adverse" in result.stdout or "EDGE:order_age" in result.stdout, "Expected reason tags"
    
    # Check KPI_GATE.json
    assert kpi_gate_path.exists(), "KPI_GATE.json should be created"
    
    kpi_gate_data = json.loads(kpi_gate_path.read_text())
    assert kpi_gate_data["verdict"] == "WARN", "Verdict should be WARN"
    assert len(kpi_gate_data["reasons"]) > 0, "Should have reasons for WARN"
    
    print("[OK] KPI Gate with warnings test PASSED")


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])

