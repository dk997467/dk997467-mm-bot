"""
E2E test for edge sentinel functionality.

Gracefully skips if module not present in repo.
"""

import pytest

from ._helpers import module_available, run_module_help, try_import

MOD_CANDIDATE = "tools.soak.edge_sentinel"


@pytest.mark.e2e
def test_edge_sentinel_skip_when_missing():
    """Test edge sentinel import or skip if not present."""
    if not module_available(MOD_CANDIDATE):
        pytest.skip(f"{MOD_CANDIDATE} not present in repo")
    
    mod = try_import(MOD_CANDIDATE)
    assert mod is not None, f"Failed to import {MOD_CANDIDATE}"
    
    # Try --help (tolerant)
    run_module_help(MOD_CANDIDATE)
