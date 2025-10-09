"""
Centralized runtime information provider for all artifacts.

This module ensures consistent UTC timestamp handling across all report generation:
- In production: uses real datetime.now(timezone.utc)
- In CI/tests: respects MM_FREEZE_UTC_ISO for determinism
- Never defaults to 1970 epoch (old bug)

All report generators (edge_report, kpi_gate, readiness, weekly, etc.)
should use get_runtime_info() instead of manually constructing runtime dict.
"""
import os
from datetime import datetime, timezone
from typing import Dict, Any


def get_runtime_info(version: str = None) -> Dict[str, Any]:
    """
    Get runtime information for artifact generation.
    
    Returns a dict with 'utc' (ISO8601 timestamp) and 'version' (semver string).
    
    Timestamp resolution:
    1. If MM_FREEZE_UTC_ISO env var is set, use that (for deterministic tests)
    2. Otherwise, use current UTC time from datetime.now(timezone.utc)
    
    Args:
        version: Optional version string override. If None, reads from MM_VERSION env var,
                 falling back to '0.1.0' for development builds.
    
    Returns:
        Dict with keys:
            - utc: ISO8601 timestamp string (e.g., "2025-01-01T12:34:56Z")
            - version: Semver version string (e.g., "v0.1.0" or "ci-0.0.0")
    
    Example:
        >>> runtime = get_runtime_info()
        >>> runtime
        {'utc': '2025-01-15T14:23:45Z', 'version': 'v0.1.0'}
        
        >>> # In CI with frozen time
        >>> os.environ['MM_FREEZE_UTC_ISO'] = '2025-01-01T00:00:00Z'
        >>> runtime = get_runtime_info()
        >>> runtime['utc']
        '2025-01-01T00:00:00Z'
    """
    # Timestamp: frozen for tests, real for production
    utc_timestamp = os.environ.get('MM_FREEZE_UTC_ISO')
    if not utc_timestamp:
        # Use current UTC time (never default to 1970 epoch!)
        utc_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Version: from env var or default
    if version is None:
        version = os.environ.get('MM_VERSION', '0.1.0')
    
    return {
        'utc': utc_timestamp,
        'version': version,
    }


def get_utc_now_iso() -> str:
    """
    Get current UTC timestamp as ISO8601 string.
    
    Convenience wrapper for get_runtime_info()['utc'].
    Respects MM_FREEZE_UTC_ISO for deterministic testing.
    
    Returns:
        ISO8601 timestamp string (e.g., "2025-01-01T12:34:56Z")
    
    Example:
        >>> utc = get_utc_now_iso()
        >>> utc
        '2025-01-15T14:23:45Z'
    """
    return get_runtime_info()['utc']

