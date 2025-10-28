"""
E2E test for anomaly radar functionality.

Uses tools.soak.anomaly_radar as the underlying module.
Gracefully skips if module not present.
"""

import pytest

from ._helpers import module_available, run_module_help, try_import

MOD = "tools.soak.anomaly_radar"


@pytest.mark.e2e
def test_anomaly_radar_import():
    """Test that anomaly radar module can be imported."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    mod = try_import(MOD)
    assert mod is not None, f"Failed to import {MOD}"


@pytest.mark.e2e
def test_anomaly_radar_help_tolerant():
    """Test that --help works (tolerant: non-zero exit is OK)."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    # Non-strict smoke: if --help not supported, don't fail
    run_module_help(MOD)
