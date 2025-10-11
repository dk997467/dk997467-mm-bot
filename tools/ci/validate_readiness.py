#!/usr/bin/env python3
"""
Readiness Validator - CI Gate for Production Readiness

Validates readiness.json structure, ranges, and verdict.

Usage:
    python -m tools.ci.validate_readiness artifacts/reports/readiness.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def validate_structure(data: Dict[str, Any]) -> List[str]:
    """Validate JSON structure."""
    errors = []
    
    # Check required top-level keys
    required_keys = ["runtime", "score", "sections", "verdict"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: '{key}'")
    
    if errors:
        return errors
    
    # Validate runtime
    if not isinstance(data["runtime"], dict):
        errors.append("'runtime' must be a dict")
    else:
        if "utc" not in data["runtime"]:
            errors.append("Missing 'runtime.utc'")
        if "version" not in data["runtime"]:
            errors.append("Missing 'runtime.version'")
    
    # Validate score
    if not isinstance(data["score"], (int, float)):
        errors.append("'score' must be a number")
    
    # Validate sections
    if not isinstance(data["sections"], dict):
        errors.append("'sections' must be a dict")
    else:
        expected_sections = ["chaos", "edge", "guards", "latency", "taker", "tests"]
        for section in expected_sections:
            if section not in data["sections"]:
                errors.append(f"Missing section: '{section}'")
            elif not isinstance(data["sections"][section], (int, float)):
                errors.append(f"Section '{section}' must be a number")
    
    # Validate verdict
    if not isinstance(data["verdict"], str):
        errors.append("'verdict' must be a string")
    elif data["verdict"] not in ["GO", "HOLD"]:
        errors.append(f"'verdict' must be 'GO' or 'HOLD', got: '{data['verdict']}'")
    
    return errors


def validate_ranges(data: Dict[str, Any]) -> List[str]:
    """Validate value ranges."""
    errors = []
    
    # Score must be 0-100
    score = data.get("score", -1)
    if not (0 <= score <= 100):
        errors.append(f"'score' must be 0-100, got: {score}")
    
    # Sections must be 0-max
    sections = data.get("sections", {})
    max_scores = {
        "chaos": 10.0,
        "edge": 30.0,
        "guards": 10.0,
        "latency": 25.0,
        "taker": 15.0,
        "tests": 10.0
    }
    
    for section, max_score in max_scores.items():
        if section in sections:
            val = sections[section]
            if not (0 <= val <= max_score):
                errors.append(f"Section '{section}' must be 0-{max_score}, got: {val}")
    
    return errors


def validate_verdict(data: Dict[str, Any]) -> List[str]:
    """Validate verdict logic."""
    errors = []
    
    score = data.get("score", -1)
    verdict = data.get("verdict", "")
    
    # GO only if score == 100
    if verdict == "GO" and score != 100.0:
        errors.append(f"Verdict 'GO' requires score=100.0, got: {score}")
    
    # HOLD if score < 100
    if verdict == "HOLD" and score == 100.0:
        errors.append(f"Verdict 'HOLD' invalid for score=100.0")
    
    return errors


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate readiness JSON")
    parser.add_argument("file", help="Path to readiness.json")
    args = parser.parse_args(argv)
    
    # Check file exists
    if not Path(args.file).exists():
        print(f"[ERROR] File not found: {args.file}", file=sys.stderr)
        return 1
    
    # Load JSON
    try:
        with open(args.file, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
        return 1
    
    # Validate
    all_errors = []
    all_errors.extend(validate_structure(data))
    
    if not all_errors:  # Only validate ranges/verdict if structure is OK
        all_errors.extend(validate_ranges(data))
        all_errors.extend(validate_verdict(data))
    
    # Report
    if all_errors:
        print(f"[VALIDATION FAILED] {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    
    # Check verdict
    verdict = data["verdict"]
    score = data["score"]
    
    if verdict == "GO":
        print(f"[PASS] Readiness: GO (score={score})")
        return 0
    else:
        print(f"[FAIL] Readiness: HOLD (score={score})")
        print("[INFO] Production deployment blocked")
        return 1


if __name__ == "__main__":
    sys.exit(main())

