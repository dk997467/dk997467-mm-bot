#!/usr/bin/env python3
"""
Reproduction case minimizer: simplifies input for debugging.

Usage:
    from tools.debug.repro_minimizer import minimize
    minimized, steps = minimize(large_text)
"""
from __future__ import annotations
from pathlib import Path


def minimize(path_or_text: str) -> tuple[str, int]:
    """
    Minimize input text for reproduction cases.
    
    - Loads from file if path_or_text is a valid file path
    - Preserves lines with '"type":"guard"' (critical markers)
    - Removes other lines to simplify
    - Returns (minimal_text, steps) where steps = number of lines removed
    
    Args:
        path_or_text: File path or raw text to minimize
    
    Returns:
        Tuple of (minimal_text, steps_removed)
    """
    # Try to load from file if it's a path
    text = path_or_text
    path = Path(path_or_text)
    if path.exists() and path.is_file():
        text = path.read_text(encoding='utf-8')
    
    # Split into lines
    lines = text.splitlines()
    original_count = len(lines)
    
    # Keep lines with critical markers (e.g. "type":"guard")
    # Also keep first and last line for context
    kept_lines = []
    for i, line in enumerate(lines):
        # Always keep first/last line
        if i == 0 or i == len(lines) - 1:
            kept_lines.append(line)
            continue
        
        # Keep critical markers
        if '"type":"guard"' in line or '"type": "guard"' in line:
            kept_lines.append(line)
            continue
        
        # Keep non-empty lines with JSON structure
        stripped = line.strip()
        if stripped and (stripped.startswith('{') or stripped.startswith('[')):
            kept_lines.append(line)
    
    minimal_text = '\n'.join(kept_lines)
    steps_removed = original_count - len(kept_lines)
    
    return (minimal_text, steps_removed)


if __name__ == "__main__":
    # Simple smoke test
    test_input = "   Hello    world   \n\n   from   repro_minimizer   "
    result = minimize(test_input, max_len=20)
    print(f"Input: {repr(test_input)}")
    print(f"Output: {repr(result)}")
    assert result == "Hello world from rep", f"Expected 'Hello world from rep', got {repr(result)}"
    print("[OK] Smoke test passed")
