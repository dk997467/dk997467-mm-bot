#!/usr/bin/env python3
"""
Reproduction case minimizer: simplifies input for debugging.

Usage:
    from tools.debug.repro_minimizer import minimize, _write_jsonl_atomic
    minimized, steps = minimize(large_text)
"""
from __future__ import annotations
from pathlib import Path


def _write_jsonl_atomic(path: str, lines: list[str]) -> None:
    """
    Write JSONL file atomically (via temp file + replace).
    
    Args:
        path: Target file path
        lines: List of JSON line strings (without newlines)
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    # Use newline='' to prevent \r\n on Windows
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    tmp.replace(p)


def minimize(path_or_text: str) -> tuple[list[str], int]:
    """
    Minimize input text for reproduction cases.
    
    - Loads from file if path_or_text is a valid file path
    - Preserves lines with '"type":"guard"' (critical markers)
    - Removes other lines to simplify
    - Returns (minimal_lines, steps) where steps = number of lines removed
    
    Args:
        path_or_text: File path or raw text to minimize
    
    Returns:
        Tuple of (list_of_json_lines, steps_removed)
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
    # Also keep minimal context: first line and line before guard
    kept_lines = []
    guard_indices = []
    
    # Find guard lines
    for i, line in enumerate(lines):
        if '"type":"guard"' in line or '"type": "guard"' in line:
            guard_indices.append(i)
    
    # Build minimal set: first line + guard lines + context before each guard
    indices_to_keep = set()
    if lines:
        indices_to_keep.add(0)  # Always keep first line
    
    for guard_idx in guard_indices:
        indices_to_keep.add(guard_idx)  # Keep guard line
        if guard_idx > 0:
            indices_to_keep.add(guard_idx - 1)  # Keep line before guard for context
    
    # Extract kept lines in order
    for i in sorted(indices_to_keep):
        kept_lines.append(lines[i].strip())
    
    steps_removed = original_count - len(kept_lines)
    
    return (kept_lines, steps_removed)


if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Repro Minimizer: Simplify input for debugging")
    parser.add_argument("--events", help="Input events JSONL file")
    parser.add_argument("--out-jsonl", help="Output JSONL file")
    parser.add_argument("--out-md", help="Output markdown file")
    parser.add_argument("--in", dest="input_file", help="Input JSONL file (alias)")
    parser.add_argument("--out", help="Output JSONL file (alias)")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test")
    args = parser.parse_args()
    
    if args.smoke:
        # Smoke test mode
        test_input = '{"type":"quote","symbol":"BTCUSDT"}\n{"type":"trade"}\n{"type":"guard","reason":"DRIFT"}\n'
        lines, steps = minimize(test_input)
        print(f"Input lines: {len(test_input.splitlines())}")
        print(f"Output lines: {len(lines)}, steps removed: {steps}")
        assert isinstance(lines, list), f"Expected list, got {type(lines)}"
        assert len(lines) <= 3, f"Expected at most 3 lines, got {len(lines)}"
        print("[OK] Smoke test passed")
        sys.exit(0)
    
    # CLI mode
    input_file = args.events or args.input_file
    output_jsonl = args.out_jsonl or args.out
    output_md = args.out_md
    
    if not input_file:
        print("Usage: python -m tools.debug.repro_minimizer --events <input.jsonl> --out-jsonl <output.jsonl>", file=sys.stderr)
        sys.exit(1)
    
    # Read input file
    from pathlib import Path
    input_text = Path(input_file).read_text(encoding='utf-8')
    
    # Minimize
    lines, steps = minimize(input_text)
    
    # Write JSONL output
    if output_jsonl:
        _write_jsonl_atomic(output_jsonl, lines)
    
    # Write MD output if requested
    if output_md:
        md_path = Path(output_md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, 'w', encoding='utf-8', newline='') as f:
            f.write("# Repro Minimizer Report\n\n")
            f.write(f"- Original lines: {len(input_text.splitlines())}\n")
            f.write(f"- Minimized lines: {len(lines)}\n")
            f.write(f"- Steps removed: {steps}\n\n")
            f.write("## Minimized Output\n\n")
            f.write("```jsonl\n")
            f.write("".join(lines))
            f.write("```\n")
    
    # No stdout in CLI mode
    sys.exit(0)
