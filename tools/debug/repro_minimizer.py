#!/usr/bin/env python3
"""
Reproduction case minimizer: simplifies input for debugging.

Usage:
    from tools.debug.repro_minimizer import minimize
    minimized = minimize(large_text, max_len=128)
"""
from __future__ import annotations


def minimize(input_text: str, max_len: int = 128) -> str:
    """
    Minimize input text for reproduction cases.
    
    - Normalizes whitespace
    - Truncates to max_len
    - Ensures deterministic output
    
    Args:
        input_text: Text to minimize
        max_len: Maximum length (default: 128)
    
    Returns:
        Minimized string
    """
    if not isinstance(input_text, str):
        input_text = str(input_text)
    
    # Normalize whitespace
    s = " ".join(input_text.split())
    
    # Truncate if needed
    if len(s) > max_len:
        s = s[:max_len]
    
    return s


if __name__ == "__main__":
    # Simple smoke test
    test_input = "   Hello    world   \n\n   from   repro_minimizer   "
    result = minimize(test_input, max_len=20)
    print(f"Input: {repr(test_input)}")
    print(f"Output: {repr(result)}")
    assert result == "Hello world from rep", f"Expected 'Hello world from rep', got {repr(result)}"
    print("[OK] Smoke test passed")
