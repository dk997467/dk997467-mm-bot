"""
Unit tests for secrets scanner.

Tests:
- Allowlist functionality (masks, test paths)
- Deterministic behavior
- Exit codes (normal vs strict mode)
"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

# Import scanner functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.ci.scan_secrets import (
    _load_custom_allowlist,
    _is_whitelisted,
    _scan_file,
    main
)


def test_allowlist_loading(tmp_path):
    """Test allowlist.txt loading."""
    allowlist_file = tmp_path / "allowlist.txt"
    allowlist_file.write_text(
        "# Comment\n"
        "****\n"
        "PLACEHOLDER\n"
        "\n"  # Empty line
        "tests/**\n"
    )
    
    with patch('tools.ci.scan_secrets.ALLOWLIST_FILE', str(allowlist_file)):
        patterns = _load_custom_allowlist()
    
    assert '****' in patterns
    assert 'PLACEHOLDER' in patterns
    assert 'tests/**' in patterns
    assert '# Comment' not in patterns  # Comments excluded
    assert '' not in patterns  # Empty lines excluded


def test_mask_allowlisting():
    """Test that masked values are allowlisted."""
    allowlist = {'****', 'PLACEHOLDER', 'DUMMY'}
    
    # Test masks
    assert _is_whitelisted('api_key: ****', '/some/file.json', allowlist) == True
    assert _is_whitelisted('secret: PLACEHOLDER', '/some/file.json', allowlist) == True
    assert _is_whitelisted('token: DUMMY', '/some/file.json', allowlist) == True
    
    # Test real secret
    assert _is_whitelisted('api_key: sk_live_12345', '/some/file.json', allowlist) == False


def test_path_allowlisting():
    """Test that path globs work."""
    allowlist = {'tests/**', 'tools/tuning/**', '*.sweep.yaml'}
    
    # Test path matching
    assert _is_whitelisted('secret: abc123', 'tests/fixtures/data.json', allowlist) == True
    assert _is_whitelisted('key: xyz', 'tools/tuning/config.py', allowlist) == True
    assert _is_whitelisted('token: 123', 'sweep/test.sweep.yaml', allowlist) == True
    
    # Test non-matching paths
    assert _is_whitelisted('secret: abc123', 'src/main.py', allowlist) == False


def test_scan_file_with_allowlist(tmp_path):
    """Test file scanning with allowlist."""
    # Create test file with mixed content
    test_file = tmp_path / "test.json"
    test_file.write_text(
        '{"api_key": "****"}\n'
        '{"secret": "sk_live_12345"}\n'
        '{"token": "PLACEHOLDER"}\n'
    )
    
    allowlist = {'****', 'PLACEHOLDER'}
    patterns = [r'sk_live_\w+', r'\*\*\*\*', r'PLACEHOLDER']
    
    real_hits, allowlisted_hits = _scan_file(str(test_file), patterns, allowlist)
    
    # Only "sk_live_12345" should be a real hit
    assert len(real_hits) == 1
    assert 'sk_live_12345' in real_hits[0][1]
    
    # **** and PLACEHOLDER should be allowlisted
    assert len(allowlisted_hits) == 2


def test_main_exit_codes(tmp_path, monkeypatch):
    """Test main() exit codes."""
    # Create isolated test directory
    test_root = tmp_path / 'isolated_test'
    test_root.mkdir()
    
    # Setup minimal environment (isolated from real codebase)
    monkeypatch.setattr('tools.ci.scan_secrets._repo_root', str(test_root))
    monkeypatch.setattr('tools.ci.scan_secrets.TARGET_DIRS', ['test_src'])
    
    # Mock DEFAULT_PATTERNS to match our test data
    test_patterns = [r'\*\*\*\*', r'api_key', r'secret']
    monkeypatch.setattr('tools.ci.scan_secrets.DEFAULT_PATTERNS', test_patterns)
    
    # Create test file with allowlisted content
    src_dir = test_root / 'test_src'
    src_dir.mkdir()
    test_file = src_dir / 'config.json'
    test_file.write_text('{"api_key": "****"}')
    
    # Create allowlist
    allowlist_file = test_root / 'tools' / 'ci' / 'allowlist.txt'
    allowlist_file.parent.mkdir(parents=True, exist_ok=True)
    allowlist_file.write_text('****\n')
    
    monkeypatch.setattr('tools.ci.scan_secrets.ALLOWLIST_FILE', str(allowlist_file))
    
    # Test normal mode (allowlisted findings → exit 0)
    with patch('sys.argv', ['scan_secrets.py']):
        rc = main([])
        assert rc == 0, "Allowlisted findings should exit 0 in normal mode"
    
    # Test strict mode (allowlisted findings → exit 1)
    with patch('sys.argv', ['scan_secrets.py', '--strict']):
        rc = main(['--strict'])
        assert rc == 1, "Allowlisted findings should exit 1 in strict mode"


def test_main_real_secrets(tmp_path, monkeypatch):
    """Test main() with real secrets (always exit 1)."""
    # Create isolated test directory
    test_root = tmp_path / 'isolated_test'
    test_root.mkdir()
    
    # Setup (isolated from real codebase)
    monkeypatch.setattr('tools.ci.scan_secrets._repo_root', str(test_root))
    monkeypatch.setattr('tools.ci.scan_secrets.TARGET_DIRS', ['test_src'])
    
    # Mock DEFAULT_PATTERNS to match our test data
    test_patterns = [r'sk_live_\w+', r'api_key']
    monkeypatch.setattr('tools.ci.scan_secrets.DEFAULT_PATTERNS', test_patterns)
    
    # Create test file with real secret
    src_dir = test_root / 'test_src'
    src_dir.mkdir()
    test_file = src_dir / 'config.json'
    test_file.write_text('{"api_key": "sk_live_real_secret_12345"}')
    
    # Create allowlist (doesn't cover this)
    allowlist_file = test_root / 'tools' / 'ci' / 'allowlist.txt'
    allowlist_file.parent.mkdir(parents=True, exist_ok=True)
    allowlist_file.write_text('****\n')
    
    monkeypatch.setattr('tools.ci.scan_secrets.ALLOWLIST_FILE', str(allowlist_file))
    
    # Test: real secret always exits 1
    with patch('sys.argv', ['scan_secrets.py']):
        rc = main([])
        assert rc == 1, "Real secrets should always exit 1"


def test_deterministic_output(tmp_path, monkeypatch):
    """Test that output is deterministic (stable sort, ASCII-only)."""
    # Setup
    monkeypatch.setattr('tools.ci.scan_secrets._repo_root', str(tmp_path))
    monkeypatch.setattr('tools.ci.scan_secrets.TARGET_DIRS', ['src'])
    
    # Create multiple files with findings (out of order)
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    
    (src_dir / 'z_file.py').write_text('secret: ****')
    (src_dir / 'a_file.py').write_text('key: ****')
    (src_dir / 'm_file.py').write_text('token: ****')
    
    # Create allowlist
    allowlist_file = tmp_path / 'tools' / 'ci' / 'allowlist.txt'
    allowlist_file.parent.mkdir(parents=True, exist_ok=True)
    allowlist_file.write_text('****\n')
    
    monkeypatch.setattr('tools.ci.scan_secrets.ALLOWLIST_FILE', str(allowlist_file))
    
    # Run multiple times, check output is identical
    import io
    from contextlib import redirect_stdout, redirect_stderr
    
    outputs = []
    for _ in range(3):
        stdout = io.StringIO()
        stderr = io.StringIO()
        
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with patch('sys.argv', ['scan_secrets.py']):
                main([])
        
        outputs.append((stdout.getvalue(), stderr.getvalue()))
    
    # All outputs should be identical
    assert outputs[0] == outputs[1] == outputs[2], "Output should be deterministic"


def test_builtin_test_credentials():
    """Test built-in test credentials whitelist."""
    allowlist = set()  # Empty custom allowlist
    
    # Test built-in credentials
    assert _is_whitelisted('key: test_api_key_for_ci_only', '/file.py', allowlist) == True
    assert _is_whitelisted('secret: test_api_secret_for_ci_only', '/file.py', allowlist) == True
    assert _is_whitelisted('password: test_pg_password_for_ci_only', '/file.py', allowlist) == True
    
    # Real credential should not be whitelisted
    assert _is_whitelisted('key: real_api_key_12345', '/file.py', allowlist) == False
