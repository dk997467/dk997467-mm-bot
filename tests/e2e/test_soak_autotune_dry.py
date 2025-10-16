#!/usr/bin/env python3
"""
E2E tests for soak auto-tuning (dry-run).

Tests multi-iteration simulation with synthetic EDGE_REPORT data.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


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


def test_soak_autotune_mock_3_iterations():
    """Test auto-tuning with 3 iterations (mock mode)."""
    print("\n" + "=" * 60)
    print("Testing soak auto-tuning with 3 iterations (mock mode)")
    print("=" * 60)
    
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T13:00:00Z"
    env["MM_VERSION"] = "test-autotune"
    
    cmd = [
        sys.executable,
        '-m', 'tools.soak.run',
        '--iterations', '3',
        '--mock',
        '--auto-tune'
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check output for markers
    full_output = result.stdout + '\n' + result.stderr
    
    # Should have iteration markers
    assert '[ITER 1/3]' in full_output
    assert '[ITER 2/3]' in full_output
    assert '[ITER 3/3]' in full_output
    
    # Should have tuning markers
    assert '| soak_iter_tune |' in full_output
    
    # Should have completion marker
    assert '[MINI-SOAK COMPLETE]' in full_output
    
    # Check that runtime_overrides.json was created
    overrides_path = ROOT_DIR / "artifacts" / "soak" / "runtime_overrides.json"
    assert overrides_path.exists(), "runtime_overrides.json not created"
    
    # Check that applied_profile.json was updated
    profile_path = ROOT_DIR / "artifacts" / "soak" / "applied_profile.json"
    assert profile_path.exists(), "applied_profile.json not created"
    
    # Parse applied_profile.json
    with open(profile_path, 'r') as f:
        applied_profile = json.load(f)
    
    # Should have runtime_adjustments
    assert "runtime_adjustments" in applied_profile
    assert "overrides_runtime" in applied_profile
    assert "applied" in applied_profile
    
    print("[OK] Soak auto-tune 3 iterations test PASSED")
    print(f"  - Exit code: {result.returncode}")
    print(f"  - Iterations: 3")
    print(f"  - runtime_overrides.json: EXISTS")
    print(f"  - applied_profile.json: EXISTS")
    print(f"  - runtime_adjustments count: {len(applied_profile.get('runtime_adjustments', []))}")


def test_soak_autotune_without_flag():
    """Test that auto-tuning is disabled without --auto-tune flag."""
    print("\n" + "=" * 60)
    print("Testing soak without --auto-tune flag")
    print("=" * 60)
    
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T13:01:00Z"
    
    cmd = [
        sys.executable,
        '-m', 'tools.soak.run',
        '--iterations', '2',
        '--mock'
        # No --auto-tune flag
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check output for markers
    full_output = result.stdout + '\n' + result.stderr
    
    # Should NOT have tuning markers
    assert '| soak_iter_tune |' not in full_output
    assert '[MINI-SOAK COMPLETE]' not in full_output  # Different mode
    
    print("[OK] Soak without auto-tune test PASSED")


def test_soak_autotune_with_profile_s1():
    """Test that S1 profile is loaded and auto-tuning works."""
    print("\n" + "=" * 60)
    print("Testing soak auto-tuning with S1 profile")
    print("=" * 60)
    
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T13:02:00Z"
    
    cmd = [
        sys.executable,
        '-m', 'tools.soak.run',
        '--iterations', '2',
        '--mock',
        '--auto-tune'
    ]
    
    result = run_command(cmd, env=env)
    
    # Check exit code
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check output for profile markers
    full_output = result.stdout + '\n' + result.stderr
    
    # Should have profile loading
    assert '[INFO] Loading profile: S1' in full_output
    assert '| profile_apply | OK | PROFILE=S1 |' in full_output
    
    # Check that applied_profile.json has correct profile
    profile_path = ROOT_DIR / "artifacts" / "soak" / "applied_profile.json"
    if profile_path.exists():
        with open(profile_path, 'r') as f:
            applied_profile = json.load(f)
        
        assert applied_profile.get("profile") == "S1"
    
    print("[OK] Soak auto-tune with S1 profile test PASSED")


def test_soak_autotune_markers_and_structure():
    """Test that all expected markers and JSON structure are present."""
    print("\n" + "=" * 60)
    print("Testing soak auto-tuning markers and JSON structure")
    print("=" * 60)
    
    env = os.environ.copy()
    env["MM_PROFILE"] = "S1"
    env["MM_FREEZE_UTC_ISO"] = "2025-10-12T13:03:00Z"
    
    cmd = [
        sys.executable,
        '-m', 'tools.soak.run',
        '--iterations', '3',
        '--mock',
        '--auto-tune'
    ]
    
    result = run_command(cmd, env=env)
    
    assert result.returncode == 0
    
    # Check applied_profile.json structure
    profile_path = ROOT_DIR / "artifacts" / "soak" / "applied_profile.json"
    assert profile_path.exists()
    
    with open(profile_path, 'r') as f:
        applied_profile = json.load(f)
    
    # Check required fields
    assert "profile" in applied_profile
    assert "base" in applied_profile
    assert "overrides_runtime" in applied_profile
    assert "runtime_adjustments" in applied_profile
    assert "applied" in applied_profile
    
    # Check runtime_adjustments structure
    if applied_profile["runtime_adjustments"]:
        adj = applied_profile["runtime_adjustments"][0]
        assert "ts" in adj
        assert "field" in adj
        assert "from" in adj
        assert "to" in adj
        assert "reason" in adj
    
    # Check runtime_overrides.json
    overrides_path = ROOT_DIR / "artifacts" / "soak" / "runtime_overrides.json"
    assert overrides_path.exists()
    
    with open(overrides_path, 'r') as f:
        overrides = json.load(f)
    
    # Should be a dict (may be empty or have fields)
    assert isinstance(overrides, dict)
    
    # If not empty, check structure
    for field, value in overrides.items():
        assert isinstance(field, str)
        assert isinstance(value, (int, float))
    
    print("[OK] Soak auto-tune markers and structure test PASSED")
    print(f"  - applied_profile fields: {list(applied_profile.keys())}")
    print(f"  - runtime_adjustments count: {len(applied_profile['runtime_adjustments'])}")
    print(f"  - overrides_runtime fields: {list(applied_profile['overrides_runtime'].keys())}")


if __name__ == '__main__':
    print("=" * 60)
    print("Running E2E Soak Auto-Tuning Tests")
    print("=" * 60)
    
    test_soak_autotune_mock_3_iterations()
    test_soak_autotune_without_flag()
    test_soak_autotune_with_profile_s1()
    test_soak_autotune_markers_and_structure()
    
    print("\n" + "=" * 60)
    print("ALL E2E TESTS PASSED [OK]")
    print("=" * 60)

