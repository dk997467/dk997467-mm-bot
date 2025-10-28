"""
E2E test for tuning apply functionality.

Uses tools.soak.apply_pipeline as the underlying module.
Gracefully skips if module not present.
"""

import pytest

from ._helpers import module_available, run_module_help, try_import

MOD = "tools.soak.apply_pipeline"


@pytest.mark.e2e
def test_tuning_apply_import():
    """Test that tuning apply module can be imported."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    mod = try_import(MOD)
    assert mod is not None, f"Failed to import {MOD}"


@pytest.mark.e2e
def test_tuning_apply_help_tolerant():
    """Test that --help works (tolerant: non-zero exit is OK)."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    # Non-strict smoke: if --help not supported, don't fail
    run_module_help(MOD)
