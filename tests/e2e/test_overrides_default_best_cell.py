"""
E2E Test: Default Best Cell Overrides

Verifies that soak runner applies default runtime overrides from best parameter sweep cell
when no explicit overrides are provided.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_overrides_default_best_cell_applied():
    """Test that default best cell overrides are applied and saved."""
    print("\n" + "=" * 60)
    print("Testing default best cell overrides")
    print("=" * 60)
    
    # Clean up artifacts to ensure fresh state
    overrides_path = ROOT_DIR / "artifacts" / "soak" / "runtime_overrides.json"
    applied_profile_path = ROOT_DIR / "artifacts" / "soak" / "applied_profile.json"
    
    if overrides_path.exists():
        overrides_path.unlink()
    if applied_profile_path.exists():
        applied_profile_path.unlink()
    
    # Run soak with S1 profile, 1 iteration, mock mode
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    cmd = [
        sys.executable,
        "-m",
        "tools.soak.run",
        "--iterations", "1",
        "--mock"
    ]
    
    print(f"Running command: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(
        cmd,
        env=env,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    
    print(f"STDOUT:\n{result.stdout}", file=sys.stderr)
    print(f"STDERR:\n{result.stderr}", file=sys.stderr)
    print(f"Exit code: {result.returncode}", file=sys.stderr)
    
    # Should succeed
    assert result.returncode == 0, f"Soak run failed with exit code {result.returncode}"
    
    # Check for marker in output
    full_output = result.stdout + '\n' + result.stderr
    assert '| overrides | OK | source=default_best_cell |' in full_output, \
        "Expected marker '| overrides | OK | source=default_best_cell |' not found"
    
    # Check that runtime_overrides.json was created
    assert overrides_path.exists(), f"Expected {overrides_path} to be created"
    
    # Load and verify structure
    with open(overrides_path, 'r', encoding='utf-8') as f:
        overrides = json.load(f)
    
    # Expected keys from best cell
    expected_keys = {
        "min_interval_ms",
        "replace_rate_per_min",
        "base_spread_bps_delta",
        "tail_age_ms",
        "impact_cap_ratio",
        "max_delta_ratio"
    }
    
    actual_keys = set(overrides.keys())
    assert expected_keys == actual_keys, \
        f"Expected keys {expected_keys}, got {actual_keys}"
    
    # Verify expected values
    assert overrides["min_interval_ms"] == 60
    assert overrides["replace_rate_per_min"] == 300
    assert overrides["base_spread_bps_delta"] == 0.05
    assert overrides["tail_age_ms"] == 600
    assert overrides["impact_cap_ratio"] == 0.10
    assert overrides["max_delta_ratio"] == 0.15
    
    # Check that applied_profile.json was created
    assert applied_profile_path.exists(), f"Expected {applied_profile_path} to be created"
    
    # Load and verify applied profile
    with open(applied_profile_path, 'r', encoding='utf-8') as f:
        applied_profile = json.load(f)
    
    # Check structure
    assert "profile" in applied_profile
    assert "base" in applied_profile
    assert "overrides_runtime" in applied_profile
    assert "runtime_overrides_applied" in applied_profile
    assert "runtime_adjustments" in applied_profile
    assert "applied" in applied_profile
    
    # Check that runtime_overrides_applied is True
    assert applied_profile["runtime_overrides_applied"] is True, \
        "Expected runtime_overrides_applied=True"
    
    # Check that overrides_runtime matches
    assert applied_profile["overrides_runtime"] == overrides, \
        "Overrides in applied_profile should match runtime_overrides.json"
    
    print("[OK] Default best cell overrides applied correctly")
    print(f"  - runtime_overrides.json created: {overrides_path}")
    print(f"  - applied_profile.json created: {applied_profile_path}")
    print(f"  - Marker found: | overrides | OK | source=default_best_cell |")
    print(f"  - All expected keys present: {expected_keys}")
    print(f"  - runtime_overrides_applied=True")


def test_overrides_env_var_takes_precedence():
    """Test that MM_RUNTIME_OVERRIDES_JSON env var takes precedence over defaults."""
    print("\n" + "=" * 60)
    print("Testing env var precedence")
    print("=" * 60)
    
    # Clean up artifacts
    overrides_path = ROOT_DIR / "artifacts" / "soak" / "runtime_overrides.json"
    applied_profile_path = ROOT_DIR / "artifacts" / "soak" / "applied_profile.json"
    
    if overrides_path.exists():
        overrides_path.unlink()
    if applied_profile_path.exists():
        applied_profile_path.unlink()
    
    # Custom overrides via ENV
    custom_overrides = {
        "min_interval_ms": 100,
        "replace_rate_per_min": 400
    }
    
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["MM_RUNTIME_OVERRIDES_JSON"] = json.dumps(custom_overrides)
    env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{ROOT_DIR / 'src'}"
    
    cmd = [
        sys.executable,
        "-m",
        "tools.soak.run",
        "--iterations", "1",
        "--mock"
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
    assert result.returncode == 0
    
    # Check for env marker
    full_output = result.stdout + '\n' + result.stderr
    assert '| overrides | OK | source=env |' in full_output, \
        "Expected marker '| overrides | OK | source=env |' not found"
    
    # Load overrides file
    with open(overrides_path, 'r', encoding='utf-8') as f:
        overrides = json.load(f)
    
    # Should match custom env values
    assert overrides["min_interval_ms"] == 100
    assert overrides["replace_rate_per_min"] == 400
    
    print("[OK] Env var overrides applied correctly")
    print(f"  - Marker found: | overrides | OK | source=env |")
    print(f"  - Custom values preserved: {custom_overrides}")


if __name__ == '__main__':
    pytest.main([__file__, "-v", "-s"])

