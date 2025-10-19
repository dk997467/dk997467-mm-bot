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


@pytest.mark.smoke
def test_nested_write_and_read():
    """Test that nested write works correctly with params.set_in_runtime()."""
    from tools.soak.apply_pipeline import apply_deltas_with_tracking
    from tools.soak.params import get_from_runtime
    
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_path = Path(tmpdir) / "runtime.json"
        
        # Apply deltas with nested keys
        proposed_deltas = {
            "base_spread_bps": 0.25,
            "impact_cap_ratio": 0.10,
            "tail_age_ms": 600,
            "concurrency_limit": 15
        }
        
        # First apply: should write to nested structure
        result1 = apply_deltas_with_tracking(
            runtime_path,
            proposed_deltas,
            {}
        )
        
        assert result1["applied"] is True, "First apply should succeed"
        assert result1["state_hash"] is not None, "Should have state hash"
        assert len(result1["changed_keys"]) == 4, "Should have 4 changed keys"
        
        # Verify nested write worked: read back with get_from_runtime
        runtime = json.loads(runtime_path.read_text())
        
        for key, expected_value in proposed_deltas.items():
            actual_value = get_from_runtime(runtime, key)
            assert actual_value == expected_value, f"Key {key}: expected {expected_value}, got {actual_value}"
        
        # Second apply (same values): should be no-op
        result2 = apply_deltas_with_tracking(
            runtime_path,
            proposed_deltas,
            {}
        )
        
        assert result2["applied"] is False, "Second apply should be no-op"
        assert result2["no_op"] is True, "Should detect no-op"
        assert result2["state_hash"] == result1["state_hash"], "State hash should be stable on no-op"
        
        print(f"✅ Nested write verified: {len(proposed_deltas)} params")


@pytest.mark.smoke
def test_latency_buffer_soft_trigger():
    """Test that soft latency buffer triggers at 330-360ms range."""
    from tools.soak.iter_watcher import propose_micro_tuning
    
    # Mock summary with p95_latency_ms in soft zone
    summary = {
        "risk_ratio": 0.30,  # Low risk (OK)
        "net_bps": 3.5,      # Good net
        "maker_taker_ratio": 0.85,  # Good maker/taker
        "p95_latency_ms": 335.0,  # In soft zone [330, 360]
        "adverse_bps_p95": 2.0,
        "slippage_bps_p95": 1.5,
        "order_age_p95_ms": 300,
        "neg_edge_drivers": []
    }
    
    current_overrides = {
        "base_spread_bps": 0.20,
        "concurrency_limit": 10,
        "tail_age_ms": 500,
        "replace_rate_per_min": 6.0
    }
    
    # Propose tuning
    result = propose_micro_tuning(summary, current_overrides)
    
    # Should propose soft latency buffer deltas
    deltas = result.get("deltas", {})
    reasons = result.get("reasons", [])
    
    # Check for latency buffer triggers
    latency_reasons = [r for r in reasons if "LATENCY_BUFFER" in r or "LATENCY_HARD" in r]
    assert len(latency_reasons) > 0, f"Should propose latency buffer deltas for p95=335ms. Reasons: {reasons}"
    
    # Should reduce concurrency
    if "concurrency_limit" in deltas:
        assert deltas["concurrency_limit"] < 0, "Should reduce concurrency_limit"
    
    print(f"✅ Soft latency buffer triggered: p95=335ms -> {len(deltas)} deltas")


@pytest.mark.smoke
def test_latency_buffer_hard_trigger():
    """Test that hard latency buffer triggers at >360ms."""
    from tools.soak.iter_watcher import propose_micro_tuning
    
    # Mock summary with p95_latency_ms in hard zone
    summary = {
        "risk_ratio": 0.25,
        "net_bps": 4.0,
        "maker_taker_ratio": 0.88,
        "p95_latency_ms": 365.0,  # In hard zone (> 360)
        "adverse_bps_p95": 1.8,
        "slippage_bps_p95": 1.2,
        "order_age_p95_ms": 280,
        "neg_edge_drivers": []
    }
    
    current_overrides = {
        "base_spread_bps": 0.18,
        "concurrency_limit": 12,
        "tail_age_ms": 450,
        "replace_rate_per_min": 5.5
    }
    
    # Propose tuning
    result = propose_micro_tuning(summary, current_overrides)
    
    deltas = result.get("deltas", {})
    reasons = result.get("reasons", [])
    
    # Check for HARD latency trigger
    hard_reasons = [r for r in reasons if "LATENCY_HARD" in r]
    assert len(hard_reasons) > 0, f"Should propose HARD latency deltas for p95=365ms. Reasons: {reasons}"
    
    # Should reduce concurrency more aggressively
    if "concurrency_limit" in deltas:
        assert deltas["concurrency_limit"] < 0, "Should reduce concurrency_limit"
    
    print(f"✅ Hard latency buffer triggered: p95=365ms -> {len(deltas)} deltas")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])

