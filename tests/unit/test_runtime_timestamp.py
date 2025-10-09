"""
Unit tests for centralized runtime timestamp handling.

Verifies that get_runtime_info() never returns 1970 epoch by default,
and properly respects MM_FREEZE_UTC_ISO for deterministic testing.
"""
import os
import pytest
from datetime import datetime, timezone

from src.common.runtime import get_runtime_info, get_utc_now_iso


def test_runtime_info_not_1970_by_default(monkeypatch):
    """
    CRITICAL: Verify that runtime.utc is never 1970 by default.
    
    This was the original bug - reports defaulted to 1970-01-01T00:00:00Z
    when MM_FREEZE_UTC_ISO was not set, breaking edge_sentinel and other reports.
    """
    # Clear env var to test default behavior
    monkeypatch.delenv('MM_FREEZE_UTC_ISO', raising=False)
    
    runtime = get_runtime_info()
    
    # Verify structure
    assert 'utc' in runtime
    assert 'version' in runtime
    assert isinstance(runtime['utc'], str)
    
    # Parse timestamp
    utc_str = runtime['utc']
    assert utc_str.endswith('Z'), "UTC timestamp must end with 'Z'"
    
    # Extract year (format: YYYY-MM-DDTHH:MM:SSZ)
    year = int(utc_str[:4])
    
    # Critical assertion: year must NOT be 1970 (the bug we're fixing)
    assert year != 1970, (
        f"runtime.utc should never default to 1970! Got: {utc_str}\n"
        "This breaks edge_sentinel and other reports that rely on valid timestamps."
    )
    
    # Sanity check: year should be reasonable (between 2020 and 2100)
    assert 2020 <= year <= 2100, (
        f"runtime.utc year is unreasonable: {year} (full timestamp: {utc_str})"
    )


def test_runtime_info_respects_frozen_time(monkeypatch):
    """
    Verify that MM_FREEZE_UTC_ISO is respected for deterministic testing.
    
    This is critical for CI/tests - frozen time must work correctly.
    """
    frozen_time = '2025-01-01T12:34:56Z'
    monkeypatch.setenv('MM_FREEZE_UTC_ISO', frozen_time)
    
    runtime = get_runtime_info()
    
    assert runtime['utc'] == frozen_time, (
        f"Expected frozen time {frozen_time}, got {runtime['utc']}"
    )


def test_runtime_info_frozen_time_not_1970(monkeypatch):
    """
    Verify that even when explicitly setting MM_FREEZE_UTC_ISO,
    we can distinguish between intentional 1970 (for tests) vs accidental default.
    """
    # If someone explicitly sets 1970 for a test, that's OK
    frozen_time = '1970-01-01T00:00:00Z'
    monkeypatch.setenv('MM_FREEZE_UTC_ISO', frozen_time)
    
    runtime = get_runtime_info()
    
    # This should match because it was explicitly set
    assert runtime['utc'] == frozen_time


def test_get_utc_now_iso_convenience_function(monkeypatch):
    """Test convenience wrapper function."""
    monkeypatch.delenv('MM_FREEZE_UTC_ISO', raising=False)
    
    utc = get_utc_now_iso()
    
    assert isinstance(utc, str)
    assert utc.endswith('Z')
    
    # Parse and verify it's a valid ISO timestamp
    year = int(utc[:4])
    assert 2020 <= year <= 2100


def test_runtime_info_version_default(monkeypatch):
    """Verify version handling."""
    monkeypatch.delenv('MM_VERSION', raising=False)
    
    runtime = get_runtime_info()
    
    # Default version is '0.1.0'
    assert runtime['version'] == '0.1.0'


def test_runtime_info_version_override(monkeypatch):
    """Verify version can be overridden."""
    monkeypatch.setenv('MM_VERSION', 'v1.2.3')
    
    runtime = get_runtime_info()
    
    assert runtime['version'] == 'v1.2.3'


def test_runtime_info_version_parameter():
    """Verify version can be set via parameter."""
    runtime = get_runtime_info(version='v9.9.9')
    
    assert runtime['version'] == 'v9.9.9'


def test_runtime_info_real_time_is_recent(monkeypatch):
    """
    Verify that real-time timestamp is actually current (within 5 seconds).
    
    This ensures we're not accidentally using cached or stale timestamps.
    """
    monkeypatch.delenv('MM_FREEZE_UTC_ISO', raising=False)
    
    before = datetime.now(timezone.utc)
    runtime = get_runtime_info()
    after = datetime.now(timezone.utc)
    
    # Parse returned timestamp
    utc_str = runtime['utc']
    # Format: YYYY-MM-DDTHH:MM:SSZ
    reported = datetime.strptime(utc_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    
    # Verify timestamp is between before and after (within 5 seconds tolerance)
    assert before.timestamp() - 5 <= reported.timestamp() <= after.timestamp() + 5, (
        f"Timestamp seems stale or incorrect:\n"
        f"  Before: {before.isoformat()}\n"
        f"  Reported: {utc_str}\n"
        f"  After: {after.isoformat()}"
    )


def test_runtime_info_json_serializable():
    """Verify that runtime info dict is JSON-serializable."""
    import json
    
    runtime = get_runtime_info()
    
    # Should not raise
    json_str = json.dumps(runtime, ensure_ascii=True, sort_keys=True)
    
    # Should round-trip correctly
    parsed = json.loads(json_str)
    assert parsed == runtime

