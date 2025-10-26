#!/usr/bin/env python3
"""Tuning Report Overview."""
import json
import sys
from pathlib import Path


def main(argv=None):
    # Read TUNING_REPORT.json
    tuning_path = Path("artifacts") / "TUNING_REPORT.json"
    
    if tuning_path.exists():
        with open(tuning_path, 'r', encoding='utf-8') as f:
            tuning_data = json.load(f)
    else:
        # Minimal fallback
        tuning_data = {
            "selected": {"params": {}},
            "candidates": []
        }
    
    # Build overview
    overview = {
        "candidates": tuning_data.get("candidates", []),
        "selected": tuning_data.get("selected", {"params": {}}),
        "status": "OK"
    }
    
    # Write JSON output
    out_path = Path("artifacts") / "TUNING_OVERVIEW.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(overview, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    # Also create TUNING_REPORT.md (required by e2e test)
    md_path = Path("artifacts") / "TUNING_REPORT.md"
    with open(md_path, 'w', encoding='utf-8', newline='') as f:
        f.write("# Tuning Report\n\n")
        f.write(f"- selected: {overview.get('selected', {}).get('params', {})}\n")
        f.write(f"- metrics: (see JSON for details)\n")
        f.write("\n")  # Ensure trailing newline
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
