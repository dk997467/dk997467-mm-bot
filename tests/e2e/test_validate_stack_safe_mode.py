#!/usr/bin/env python3
"""
Test validate_stack in safe-mode (with missing secrets).

This test verifies that FULL_STACK validation can run without secrets
and correctly marks sections as SKIPPED_NO_SECRETS.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# Find workspace root (tests/e2e -> tests -> root)
ROOT_DIR = Path(__file__).resolve().parents[2]


def test_validate_stack_safe_mode():
    """Test that validate_stack runs in safe-mode without secrets."""
    
    # Ensure no real secrets are set
    env = os.environ.copy()
    env['STORAGE_PG_PASSWORD'] = 'dummy'
    env['BYBIT_API_KEY'] = 'dummy'
    env['BYBIT_API_SECRET'] = 'dummy'
    env['MM_ALLOW_MISSING_SECRETS'] = '1'
    env['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
    env['MM_VERSION'] = 'test-0.0.0'
    
    # Set PYTHONPATH for module imports
    pythonpath_parts = [str(ROOT_DIR), str(ROOT_DIR / 'src')]
    existing = env.get('PYTHONPATH', '')
    if existing:
        pythonpath_parts.append(existing)
    env['PYTHONPATH'] = os.pathsep.join(pythonpath_parts)
    
    # Run validate_stack with safe-mode flags
    cmd = [
        sys.executable,
        '-m',
        'tools.ci.validate_stack',
        '--emit-stack-summary',
        '--allow-missing-secrets',
        '--allow-missing-sections',
    ]
    
    result = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    # Check exit code (should be 0 in safe mode)
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\nStderr: {result.stderr}"
    
    # Check stdout contains JSON
    assert result.stdout.strip(), "Expected JSON output on stdout"
    
    # Parse JSON output (first line should be JSON)
    json_line = result.stdout.strip().split('\n')[0]
    try:
        data = json.loads(json_line)
    except json.JSONDecodeError as e:
        pytest.fail(f"Failed to parse JSON: {e}\nOutput: {json_line}")
    
    # Verify structure
    assert 'sections' in data, "Expected 'sections' in JSON output"
    assert 'ok' in data, "Expected 'ok' in JSON output"
    assert 'runtime' in data, "Expected 'runtime' in JSON output"
    
    # Find tests_whitelist section
    tests_section = None
    for section in data['sections']:
        if section.get('name') == 'tests_whitelist':
            tests_section = section
            break
    
    assert tests_section is not None, "Expected 'tests_whitelist' section in output"
    assert tests_section.get('ok') is True, f"Expected tests_whitelist.ok=True, got {tests_section.get('ok')}"
    assert tests_section.get('details') == 'SKIPPED_NO_SECRETS', \
        f"Expected tests_whitelist.details='SKIPPED_NO_SECRETS', got {tests_section.get('details')}"
    
    # Check for final marker in output
    full_output = result.stdout + '\n' + result.stderr
    assert '| full_stack |' in full_output, "Expected '| full_stack |' marker in output"
    assert 'STACK=GREEN' in full_output or 'STACK=RED' in full_output, "Expected STACK=GREEN or STACK=RED in marker"
    
    print("[OK] validate_stack safe-mode test PASSED")
    print(f"  - Exit code: {result.returncode}")
    print(f"  - tests_whitelist section: {tests_section}")
    print(f"  - Marker found: {bool('| full_stack |' in full_output)}")


def test_full_stack_validate_safe_mode():
    """Test that full_stack_validate runs in safe-mode without secrets."""
    
    # Ensure no real secrets are set
    env = os.environ.copy()
    env['STORAGE_PG_PASSWORD'] = 'dummy'
    env['BYBIT_API_KEY'] = 'dummy'
    env['BYBIT_API_SECRET'] = 'dummy'
    env['MM_ALLOW_MISSING_SECRETS'] = '1'
    env['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
    env['MM_VERSION'] = 'test-0.0.0'
    env['FULL_STACK_VALIDATION_FAST'] = '1'  # Use fast mode to skip heavy tests
    
    # Set PYTHONPATH for module imports
    pythonpath_parts = [str(ROOT_DIR), str(ROOT_DIR / 'src')]
    existing = env.get('PYTHONPATH', '')
    if existing:
        pythonpath_parts.append(existing)
    env['PYTHONPATH'] = os.pathsep.join(pythonpath_parts)
    
    # Run full_stack_validate with safe-mode flags
    cmd = [
        sys.executable,
        '-m',
        'tools.ci.full_stack_validate',
        '--allow-missing-secrets',
        '--allow-missing-sections',
    ]
    
    result = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60
    )
    
    # Check exit code (should be 0 in safe mode with FAST=1)
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\nStderr: {result.stderr}"
    
    # Check for RESULT=OK in output
    full_output = result.stdout + '\n' + result.stderr
    assert 'RESULT=OK' in full_output, "Expected 'RESULT=OK' in output"
    
    # Check for final marker
    assert '| full_stack |' in full_output, "Expected '| full_stack |' marker in output"
    assert 'STACK=GREEN' in full_output, "Expected 'STACK=GREEN' in marker"
    
    print("[OK] full_stack_validate safe-mode test PASSED")
    print(f"  - Exit code: {result.returncode}")
    print(f"  - RESULT=OK found: {bool('RESULT=OK' in full_output)}")
    print(f"  - STACK=GREEN found: {bool('STACK=GREEN' in full_output)}")


if __name__ == '__main__':
    # Run tests directly
    print("=" * 60)
    print("Testing validate_stack safe-mode...")
    print("=" * 60)
    test_validate_stack_safe_mode()
    
    print("\n" + "=" * 60)
    print("Testing full_stack_validate safe-mode...")
    print("=" * 60)
    test_full_stack_validate_safe_mode()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED [OK]")
    print("=" * 60)
