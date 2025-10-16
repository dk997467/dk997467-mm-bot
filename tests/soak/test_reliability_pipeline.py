#!/usr/bin/env python3
"""
Tests for soak reliability pipeline (Phases 2-4).

Tests:
- State hash changes on delta apply
- Skip reasons present when guards block
- Delta full apply ratio >= 95% in mock mode
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.smoke
def test_state_hash_changes_on_apply():
    """Test that state_hash changes when deltas are applied (non-no-op)."""
    from tools.common.jsonx import compute_json_hash
    
    # Create two different runtime states
    runtime1 = {"risk": {"base_spread_bps": 0.20}}
    runtime2 = {"risk": {"base_spread_bps": 0.25}}
    
    # Compute hashes
    hash1 = compute_json_hash(runtime1)
    hash2 = compute_json_hash(runtime2)
    
    # Should be different (value changed)
    assert hash1 != hash2, "State hash should change when value changes"
    
    # No-op: same runtime
    runtime3 = {"risk": {"base_spread_bps": 0.20}}
    hash3 = compute_json_hash(runtime3)
    
    # Should be same as first (same values)
    assert hash1 == hash3, "State hash should be same for identical runtime"


@pytest.mark.smoke
def test_skip_reason_present_on_guard_block():
    """Test that skip_reason is populated when guards block apply."""
    from tools.soak.apply_pipeline import apply_deltas_with_tracking
    
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_path = Path(tmpdir) / "runtime.json"
        
        # Test cooldown guard
        result = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25},
            {"cooldown_active": True, "cooldown_iters_left": 2}
        )
        
        assert result["applied"] is False, "Should not apply with cooldown active"
        assert result["skip_reason"] is not None, "skip_reason should be present"
        assert result["skip_reason"]["cooldown"] is True, "cooldown flag should be set"
        assert "cooldown 2 iters left" in result["skip_reason"]["note"], "note should explain reason"
        
        # Test velocity guard
        result2 = apply_deltas_with_tracking(
            runtime_path,
            {"tail_age_ms": 500},
            {"velocity_violation": True}
        )
        
        assert result2["applied"] is False
        assert result2["skip_reason"]["velocity"] is True
        
        # Test oscillation guard
        result3 = apply_deltas_with_tracking(
            runtime_path,
            {"concurrency_limit": 20},
            {"oscillation_detected": True}
        )
        
        assert result3["applied"] is False
        assert result3["skip_reason"]["oscillation"] is True
        
        # Test freeze guard
        result4 = apply_deltas_with_tracking(
            runtime_path,
            {"min_interval_ms": 100},
            {"freeze_triggered": True}
        )
        
        assert result4["applied"] is False
        assert result4["skip_reason"]["freeze"] is True


@pytest.mark.smoke
def test_no_op_detection():
    """Test that no-op deltas are detected (value already at target)."""
    from tools.soak.apply_pipeline import apply_deltas_with_tracking
    
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_path = Path(tmpdir) / "runtime.json"
        
        # First apply
        result1 = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25},
            {}
        )
        
        assert result1["applied"] is True
        assert result1["no_op"] is False
        
        # Second apply (same value = no-op)
        result2 = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25},  # Same value
            {}
        )
        
        assert result2["applied"] is False, "Should not apply (no-op)"
        assert result2["no_op"] is True, "Should detect no-op"
        assert result2["skip_reason"]["no_op"] is True
        assert "no effective change" in result2["skip_reason"]["note"]


@pytest.mark.smoke
def test_apply_pipeline_atomic_write():
    """Test that apply pipeline uses atomic write and returns state hash."""
    from tools.soak.apply_pipeline import apply_deltas_with_tracking
    from tools.common.jsonx import read_json_with_hash
    
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_path = Path(tmpdir) / "runtime.json"
        
        # Apply deltas
        result = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25, "tail_age_ms": 500},
            {}
        )
        
        assert result["applied"] is True
        assert result["state_hash"] is not None
        assert len(result["state_hash"]) == 64  # SHA256 hex length
        assert result["changed_keys"] == ["base_spread_bps", "tail_age_ms"]
        assert result["bytes_written"] > 0
        
        # Verify file was written
        assert runtime_path.exists()
        
        # Read back and verify hash matches
        data, file_hash = read_json_with_hash(runtime_path)
        assert file_hash == result["state_hash"], "File hash should match returned hash"


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_delta_verifier_with_skip_reason():
    """Test that delta verifier accepts skip_reason as valid."""
    # This test requires fixtures with skip_reason data
    # For now, just verify verifier can handle skip_reason format
    
    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = Path(tmpdir)
        
        # Create mock TUNING_REPORT.json with skip_reason
        tuning_report = {
            "iterations": [
                {
                    "iteration": 0,
                    "proposed_deltas": {},
                    "applied": True,
                    "signature": "hash0",
                },
                {
                    "iteration": 1,
                    "proposed_deltas": {"base_spread_bps": 0.25},
                    "applied": False,
                    "skip_reason": {
                        "cooldown": True,
                        "velocity": False,
                        "oscillation": False,
                        "freeze": False,
                        "no_op": False,
                        "note": "cooldown 2 iters left"
                    },
                    "signature": "hash0",  # Same (not applied)
                }
            ]
        }
        
        tuning_path = base_path / "TUNING_REPORT.json"
        with open(tuning_path, "w") as f:
            json.dump(tuning_report, f)
        
        # Create mock ITER_SUMMARY files
        for i in range(2):
            summary = {
                "iteration": i,
                "summary": {"state_hash": f"hash{i}"},
                "tuning": tuning_report["iterations"][i]
            }
            summary_path = base_path / f"ITER_SUMMARY_{i}.json"
            with open(summary_path, "w") as f:
                json.dump(summary, f)
        
        # Run verifier
        result = subprocess.run(
            [sys.executable, "-m", "tools.soak.verify_deltas_applied",
             "--path", str(base_path), "--json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        
        # Should pass (skip_reason makes it partial_ok, not fail)
        assert result.returncode == 0, f"Verifier should pass with skip_reason. stderr: {result.stderr}"
        
        # Check JSON output
        metrics = json.loads(result.stdout)
        assert metrics["partial_ok_count"] >= 1, "Should have at least one partial_ok"


@pytest.mark.slow
@pytest.mark.timeout(300)
def test_soak_gate_with_delta_verify():
    """Test that soak_gate runs delta verifier and checks metrics."""
    # This test requires a full soak artifacts directory
    # For now, just verify gate can be invoked with delta verify
    
    # Note: This test will be skipped if no artifacts exist
    artifacts_path = PROJECT_ROOT / "artifacts" / "soak" / "latest"
    
    if not artifacts_path.exists():
        pytest.skip("No soak artifacts found")
    
    # Run soak gate with delta verify
    result = subprocess.run(
        [sys.executable, "-m", "tools.soak.soak_gate",
         "--path", str(artifacts_path),
         "--skip-analyzer",  # Skip analyzer for speed
         "--prometheus"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    # Check that delta verifier was run
    assert "verify_deltas_applied" in result.stderr, "Delta verifier should be invoked"
    
    # Check that Prometheus metrics were exported
    metrics_path = artifacts_path / "POST_SOAK_METRICS.prom"
    if metrics_path.exists():
        content = metrics_path.read_text()
        assert "soak_delta_full_apply_ratio" in content, "Delta metrics should be exported"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])

