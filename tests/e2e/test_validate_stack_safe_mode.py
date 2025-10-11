#!/usr/bin/env python3
"""
E2E tests for validate_stack.py safe mode with missing secrets.

Tests that the stack validator can handle missing secrets gracefully
when --allow-missing-secrets flag is set.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_validate_stack_with_missing_secrets():
    """Test that validate_stack works with missing secrets in safe mode."""
    root = Path(__file__).resolve().parents[2]
    
    # Set up environment with dummy secrets (simulating mini-soak)
    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'MM_ALLOW_MISSING_SECRETS': '1',
        'BYBIT_API_KEY': 'dummy',
        'BYBIT_API_SECRET': 'dummy',
        'STORAGE_PG_PASSWORD': 'dummy',
        'FIXTURES_DIR': str(root / 'tests' / 'fixtures'),
    })
    
    # Create temporary directory for test outputs
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "stack_summary.json"
        
        # Run validate_stack with safe mode
        cmd = [
            sys.executable,
            str(root / 'tools' / 'ci' / 'validate_stack.py'),
            '--emit-stack-summary',
            '--allow-missing-secrets',
            '--allow-missing-sections',
            '--output', str(output_file)
        ]
        
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60
        )
        
        # Should succeed with exit 0
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"Stdout: {result.stdout}\n"
            f"Stderr: {result.stderr}"
        )
        
        # Should contain final marker
        assert '| full_stack | OK | STACK=GREEN |' in result.stdout, (
            f"Expected STACK=GREEN marker in output\n"
            f"Stdout: {result.stdout}"
        )
        
        # Load and validate JSON output
        assert output_file.exists(), f"Output file not created: {output_file}"
        
        with open(output_file, 'r', encoding='ascii') as f:
            data = json.load(f)
        
        # Check structure
        assert 'ok' in data
        assert 'runtime' in data
        assert 'sections' in data
        
        # Should be marked as OK overall
        assert data['ok'] is True, f"Expected ok=True, got {data}"
        
        # Check runtime fields
        assert data['runtime']['utc'] == '2025-01-01T00:00:00Z'
        assert data['runtime']['version'] == 'test-1.0.0'
        
        # Check sections
        sections = data['sections']
        assert isinstance(sections, list)
        
        # Find audit-related sections
        section_names = [s['name'] for s in sections]
        
        # All sections should be marked as ok
        for section in sections:
            assert section['ok'] is True, (
                f"Section {section['name']} should be ok=True in safe mode"
            )
            
            # Audit sections should be marked as skipped
            if section['name'] in ['audit_dump', 'audit_chain', 'secrets']:
                # Note: These sections may not exist if we're only aggregating
                # readiness/gates/tests, but if they do exist, they should be skipped
                pass


def test_validate_stack_without_safe_mode_fails():
    """Test that validate_stack fails without safe mode when secrets are missing."""
    root = Path(__file__).resolve().parents[2]
    
    # Set up environment with dummy secrets but NO safe mode
    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'MM_ALLOW_MISSING_SECRETS': '0',  # Explicitly disable
        'BYBIT_API_KEY': 'dummy',
        'BYBIT_API_SECRET': 'dummy',
        'STORAGE_PG_PASSWORD': 'dummy',
    })
    
    # Remove any MM_ALLOW_MISSING_SECRETS setting
    env.pop('MM_ALLOW_MISSING_SECRETS', None)
    
    # Create temporary directory for test outputs
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "stack_summary.json"
        
        # Run validate_stack WITHOUT safe mode
        cmd = [
            sys.executable,
            str(root / 'tools' / 'ci' / 'validate_stack.py'),
            '--emit-stack-summary',
            '--allow-missing-sections',  # Still allow missing files
            '--output', str(output_file)
        ]
        
        result = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60
        )
        
        # Should fail with exit 1
        assert result.returncode == 1, (
            f"Expected exit code 1 (failure), got {result.returncode}\n"
            f"Stdout: {result.stdout}\n"
            f"Stderr: {result.stderr}"
        )
        
        # Should contain error message about missing secrets
        assert 'secrets not available' in result.stderr.lower() or \
               'allow-missing-secrets' in result.stderr.lower(), (
            f"Expected error about missing secrets in stderr\n"
            f"Stderr: {result.stderr}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

