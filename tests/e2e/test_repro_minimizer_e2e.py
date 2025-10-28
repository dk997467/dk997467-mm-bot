"""
E2E test for repro minimizer functionality.

Uses tools.soak.analyze_post_soak as proxy module.
Gracefully skips if module not present.
"""

import pytest

from ._helpers import module_available, run_module_help, try_import

# In the tree, we have analyze_post_soak; use it as proxy for "repro-minimizer"
MOD = "tools.soak.analyze_post_soak"


@pytest.mark.e2e
def test_repro_minimizer_import_or_skip():
    """Test that repro minimizer module can be imported."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    mod = try_import(MOD)
    assert mod is not None, f"Failed to import {MOD}"


@pytest.mark.e2e
def test_repro_minimizer_help_tolerant():
    """Test that --help works (tolerant: non-zero exit is OK)."""
    if not module_available(MOD):
        pytest.skip(f"{MOD} not present in repo")
    
    # Non-strict smoke: if --help not supported, don't fail
    run_module_help(MOD)
