"""
E2E test for soak runner with mock data.

Tests that soak runner executes, creates artifacts, and returns correct exit codes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_soak_runner_pass():
    """Test soak runner with passing mock data."""
    # Clean up old artifacts
    for path in ["artifacts/reports/soak_metrics.json", 
                 "artifacts/reports/SOAK_RESULTS.md",
                 "artifacts/reports/gates_summary.json"]:
        if Path(path).exists():
            Path(path).unlink()
    
    # Run soak runner with mock data (should pass)
    result = subprocess.run(
        [
            sys.executable, "-m", "tools.soak.run",
            "--hours", "72",
            "--mock",
            "--export-json", "artifacts/reports/soak_metrics.json",
            "--export-md", "artifacts/reports/SOAK_RESULTS.md",
            "--gate-summary", "artifacts/reports/gates_summary.json"
        ],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    # Should pass (exit 0)
    assert result.returncode == 0, \
        f"Expected exit 0, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    
    # Check artifacts created
    assert Path("artifacts/reports/soak_metrics.json").exists(), "JSON metrics not created"
    assert Path("artifacts/reports/SOAK_RESULTS.md").exists(), "Markdown report not created"
    assert Path("artifacts/reports/gates_summary.json").exists(), "Gates summary not created"
    
    # Verify JSON structure
    with open("artifacts/reports/soak_metrics.json") as f:
        data = json.load(f)
        assert "runtime" in data
        assert "metrics" in data
        assert "gates" in data
        assert "verdict" in data
        assert data["verdict"] == "PASS"
    
    # Verify gates summary
    with open("artifacts/reports/gates_summary.json") as f:
        gates = json.load(f)
        assert "gates" in gates
        assert "verdict" in gates
        assert gates["verdict"] == "PASS"
    
    # Verify markdown content
    with open("artifacts/reports/SOAK_RESULTS.md") as f:
        md = f.read()
        assert "SOAK TEST RESULTS" in md
        assert "✅ PASS" in md
    
    print("✓ Soak runner (pass) test passed")


def test_soak_runner_artifacts():
    """Test that all expected artifacts are created."""
    # Artifacts should exist from previous test
    artifacts = [
        "artifacts/reports/soak_metrics.json",
        "artifacts/reports/SOAK_RESULTS.md",
        "artifacts/reports/gates_summary.json"
    ]
    
    for artifact in artifacts:
        assert Path(artifact).exists(), f"Artifact not found: {artifact}"
        assert Path(artifact).stat().st_size > 0, f"Artifact is empty: {artifact}"
    
    print("✓ Soak artifacts test passed")


if __name__ == "__main__":
    test_soak_runner_pass()
    test_soak_runner_artifacts()
    print("\n✓ All soak runner E2E tests passed")

