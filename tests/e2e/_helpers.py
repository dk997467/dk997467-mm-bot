"""
Helper utilities for E2E tests.

Provides safe module checking and import with graceful degradation.
"""

import importlib.util
import subprocess
import sys
from typing import Optional


def module_available(mod: str) -> bool:
    """Check if module is available for import."""
    return importlib.util.find_spec(mod) is not None


def try_import(mod: str):
    """
    Try to import module. Returns None if module not available.
    
    Args:
        mod: Module name (e.g. 'tools.soak.runner')
        
    Returns:
        Module object or None
    """
    if not module_available(mod):
        return None
    return __import__(mod, fromlist=['*'])


def run_module_help(mod: str) -> Optional[subprocess.CompletedProcess]:
    """
    Safely try to run `python -m <mod> --help`.
    
    Returns CompletedProcess if successful (exit code 0).
    If module is missing or --help behaves non-standard, returns None.
    
    This is tolerant: some CLI tools exit with non-zero on --help,
    so we don't treat that as a failure.
    
    Args:
        mod: Module name (e.g. 'tools.soak.runner')
        
    Returns:
        CompletedProcess or None
    """
    if not module_available(mod):
        return None
    
    try:
        cp = subprocess.run(
            [sys.executable, "-m", mod, "--help"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,  # Prevent hanging
        )
        return cp
    except Exception:
        # Not a failure: some CLI --help exits with code != 0
        return None

