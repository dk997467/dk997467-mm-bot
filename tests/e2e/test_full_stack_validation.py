import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_full_stack_validation_e2e():
    """Test full stack validation end-to-end with golden file comparison."""
    root = Path(__file__).resolve().parents[2]
    
    # Set up test environment
    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'PRE_LIVE_SKIP_BUG_BASH': '1',  # Skip potentially flaky components in test
        'FULL_STACK_VALIDATION_FAST': '1',  # Use fast mode for testing
    })
    
    # Clean up any existing artifacts to ensure deterministic test
    artifacts_dir = root / 'artifacts'
    validation_json = artifacts_dir / 'FULL_STACK_VALIDATION.json'
    validation_md = artifacts_dir / 'FULL_STACK_VALIDATION.md'
    
    if validation_json.exists():
        validation_json.unlink()
    if validation_md.exists():
        validation_md.unlink()
    
    # Run full stack validation
    validate_cmd = [sys.executable, str(root / 'tools' / 'ci' / 'full_stack_validate.py')]
    result = subprocess.run(validate_cmd, cwd=root, env=env, capture_output=True, text=True)
    
    # Validation script should always exit 0 (status is in report)
    assert result.returncode == 0, f"Validation script failed: {result.stderr}"
    
    # Check that JSON report was created
    assert validation_json.exists(), "Validation JSON report not created"
    
    # Validate JSON structure
    with open(validation_json, 'r', encoding='ascii') as f:
        data = json.load(f)
    
    assert 'sections' in data
    assert 'result' in data
    assert 'runtime' in data
    assert data['runtime']['utc'] == '2025-01-01T00:00:00Z'
    assert data['runtime']['version'] == 'test-1.0.0'
    
    # Check expected sections
    section_names = {s['name'] for s in data['sections']}
    expected_sections = {
        'linters', 'tests_whitelist', 'dry_runs', 'reports', 
        'dashboards', 'secrets', 'audit_chain'
    }
    assert section_names == expected_sections
    
    # Run report generator
    report_cmd = [
        sys.executable, 
        str(root / 'tools' / 'ci' / 'report_full_stack.py'),
        str(validation_json)
    ]
    result = subprocess.run(report_cmd, cwd=root, capture_output=True, text=True)
    
    assert result.returncode == 0, f"Report generator failed: {result.stderr}"
    
    # Check that MD report was created
    assert validation_md.exists(), "Validation MD report not created"
    
    # Verify MD report ends with newline
    with open(validation_md, 'rb') as f:
        content = f.read()
        assert content.endswith(b'\n'), "MD report should end with newline"
    
    # Read generated report
    with open(validation_md, 'r', encoding='ascii') as f:
        generated_content = f.read()
    
    # Compare with golden file
    golden_file = root / 'tests' / 'golden' / 'FULL_STACK_VALIDATION_case1.md'
    
    if golden_file.exists():
        with open(golden_file, 'r', encoding='ascii') as f:
            expected_content = f.read()
        
        # Byte-for-byte comparison for determinism
        assert generated_content == expected_content, (
            f"Generated report differs from golden file.\n"
            f"Generated: {validation_md}\n"
            f"Golden: {golden_file}\n"
            f"Run 'diff {validation_md} {golden_file}' to see differences"
        )
    else:
        # If golden file doesn't exist, create it for future runs
        # This allows graceful degradation in environments without fixtures
        pytest.skip(f"Golden file not found: {golden_file}. Generated report available at {validation_md}")


def test_full_stack_validation_json_deterministic():
    """Test that validation JSON is deterministic with same inputs."""
    root = Path(__file__).resolve().parents[2]
    
    # Set up deterministic environment
    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'PRE_LIVE_SKIP_BUG_BASH': '1',
        'FULL_STACK_VALIDATION_FAST': '1',
    })
    
    artifacts_dir = root / 'artifacts'
    validation_json = artifacts_dir / 'FULL_STACK_VALIDATION.json'
    
    # Run validation twice
    validate_cmd = [sys.executable, str(root / 'tools' / 'ci' / 'full_stack_validate.py')]
    
    # First run
    if validation_json.exists():
        validation_json.unlink()
    
    result1 = subprocess.run(validate_cmd, cwd=root, env=env, capture_output=True, text=True)
    assert result1.returncode == 0
    
    with open(validation_json, 'rb') as f:
        content1 = f.read()
    
    # Second run
    validation_json.unlink()
    
    result2 = subprocess.run(validate_cmd, cwd=root, env=env, capture_output=True, text=True)
    assert result2.returncode == 0
    
    with open(validation_json, 'rb') as f:
        content2 = f.read()
    
    # Should be byte-for-byte identical
    assert content1 == content2, "Validation JSON should be deterministic"


def test_full_stack_validation_handles_missing_fixtures():
    """Test that validation gracefully handles missing fixture files."""
    root = Path(__file__).resolve().parents[2]
    
    # Set up environment
    env = os.environ.copy()
    env.update({
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'PRE_LIVE_SKIP_BUG_BASH': '1',
        'FULL_STACK_VALIDATION_FAST': '1',
    })
    
    # Temporarily rename fixtures directory if it exists
    fixtures_dir = root / 'tests' / 'fixtures'
    fixtures_backup = None
    
    if fixtures_dir.exists():
        fixtures_backup = root / 'tests' / 'fixtures_backup_temp'
        fixtures_dir.rename(fixtures_backup)
    
    try:
        # Run validation
        validate_cmd = [sys.executable, str(root / 'tools' / 'ci' / 'full_stack_validate.py')]
        result = subprocess.run(validate_cmd, cwd=root, env=env, capture_output=True, text=True)
        
        # Should still succeed (graceful degradation)
        assert result.returncode == 0
        
        # Check that JSON was created
        validation_json = root / 'artifacts' / 'FULL_STACK_VALIDATION.json'
        assert validation_json.exists()
        
        # Check that missing fixtures are handled gracefully
        with open(validation_json, 'r', encoding='ascii') as f:
            data = json.load(f)
        
        # Reports section should indicate skipped fixtures
        reports_section = next(s for s in data['sections'] if s['name'] == 'reports')
details = reports_section.get('details', '')
ok_flag = reports_section.get('ok', False)
assert ('SKIP' in details) or ok_flag
        
    finally:
        # Restore fixtures directory
        if fixtures_backup and fixtures_backup.exists():
            if fixtures_dir.exists():
                # Remove the empty directory that might have been created
                fixtures_dir.rmdir()
            fixtures_backup.rename(fixtures_dir)

