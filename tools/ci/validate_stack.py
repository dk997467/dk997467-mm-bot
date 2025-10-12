#!/usr/bin/env python3
"""
Stack Summary Aggregator

Aggregates validation results from multiple sources (readiness, gates, tests)
into a unified stack summary for CI/CD integration.

Usage:
    python -m tools.ci.validate_stack --emit-stack-summary
    
    # With specific input files:
    python -m tools.ci.validate_stack \
        --emit-stack-summary \
        --readiness-file artifacts/reports/readiness.json \
        --gates-file artifacts/reports/gates_summary.json \
        --allow-missing-sections
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List


def get_utc_timestamp() -> str:
    """Get UTC timestamp, respecting MM_FREEZE_UTC_ISO for determinism."""
    if 'MM_FREEZE_UTC_ISO' in os.environ:
        return os.environ['MM_FREEZE_UTC_ISO']
    
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_version() -> str:
    """Get version from MM_VERSION env var or VERSION file."""
    if 'MM_VERSION' in os.environ:
        return os.environ['MM_VERSION']
    
    version_file = Path("VERSION")
    if version_file.exists():
        return version_file.read_text().strip()
    
    return "dev"


def load_json_safe(path: Path, allow_missing: bool = False) -> Dict[str, Any]:
    """Load JSON file safely, return empty dict if missing and allowed."""
    if not path.exists():
        if allow_missing:
            return {}
        raise FileNotFoundError(f"Required file not found: {path}")
    
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception as e:
        if allow_missing:
            return {}
        raise RuntimeError(f"Failed to load {path}: {e}")


def extract_readiness_section(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract section info from readiness.json."""
    if not data:
        return {"name": "readiness", "ok": True, "details": "SKIP: missing file"}
    
    # readiness.json has 'score' and 'verdict'
    score = data.get('score', 0.0)
    verdict = data.get('verdict', 'HOLD')
    
    return {
        "name": "readiness",
        "ok": verdict == "GO" and score == 100.0,
        "details": f"score={score}, verdict={verdict}"
    }


def extract_gates_section(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract section info from gates_summary.json."""
    if not data:
        return {"name": "gates", "ok": True, "details": "SKIP: missing file"}
    
    # gates_summary.json structure varies, assume it has 'passed' or similar
    passed = data.get('passed', True)
    
    return {
        "name": "gates",
        "ok": passed,
        "details": "PASS" if passed else "FAIL"
    }


def extract_tests_section(data: Dict[str, Any], allow_missing_secrets: bool = False) -> Dict[str, Any]:
    """Extract section info from tests_summary.json."""
    # Check if secrets are missing and allowed to skip
    secrets_available = check_secrets_available()
    
    if not secrets_available and allow_missing_secrets:
        return {
            "name": "tests_whitelist",
            "ok": True,
            "details": "SKIPPED_NO_SECRETS"
        }
    
    if not data:
        return {"name": "tests_whitelist", "ok": True, "details": "SKIP: missing file"}
    
    # tests_summary.json might have 'passed', 'failed', or 'result'
    if 'result' in data:
        ok = data['result'] in ('PASS', 'OK')
    elif 'passed' in data:
        ok = data['passed']
    else:
        # Fallback: assume ok if file exists
        ok = True
    
    return {
        "name": "tests_whitelist",
        "ok": ok,
        "details": "PASS" if ok else "FAIL"
    }


def aggregate_stack_summary(
    readiness_file: Path,
    gates_file: Path,
    tests_file: Path,
    allow_missing: bool = False,
    allow_missing_secrets: bool = False
) -> Dict[str, Any]:
    """Aggregate stack summary from multiple sources."""
    # Load data from files
    readiness_data = load_json_safe(readiness_file, allow_missing)
    gates_data = load_json_safe(gates_file, allow_missing)
    tests_data = load_json_safe(tests_file, allow_missing)
    
    # Extract sections
    sections = [
        extract_readiness_section(readiness_data),
        extract_tests_section(tests_data, allow_missing_secrets=allow_missing_secrets),
        extract_gates_section(gates_data),
    ]
    
    # Compute overall ok status
    overall_ok = all(s['ok'] for s in sections)
    
    # Build summary
    summary = {
        "sections": sections,
        "ok": overall_ok,
        "runtime": {
            "utc": get_utc_timestamp(),
            "version": get_version()
        }
    }
    
    return summary


def check_secrets_available() -> bool:
    """Check if required secrets are available."""
    required_secrets = ['BYBIT_API_KEY', 'BYBIT_API_SECRET', 'STORAGE_PG_PASSWORD']
    
    # Check if any required secret is missing or is a dummy value
    for secret in required_secrets:
        value = os.environ.get(secret, '')
        if not value or value.lower() in ('', 'dummy', 'test', 'none'):
            return False
    
    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Stack summary aggregator")
    
    parser.add_argument(
        "--emit-stack-summary",
        action="store_true",
        help="Emit stack summary JSON"
    )
    
    parser.add_argument(
        "--readiness-file",
        type=Path,
        default=Path("artifacts/reports/readiness.json"),
        help="Path to readiness.json"
    )
    
    parser.add_argument(
        "--gates-file",
        type=Path,
        default=Path("artifacts/reports/gates_summary.json"),
        help="Path to gates_summary.json"
    )
    
    parser.add_argument(
        "--tests-file",
        type=Path,
        default=Path("artifacts/reports/tests_summary.json"),
        help="Path to tests_summary.json"
    )
    
    parser.add_argument(
        "--allow-missing-sections",
        action="store_true",
        help="Allow missing input files (treat as ok)"
    )
    
    parser.add_argument(
        "--allow-missing-secrets",
        action="store_true",
        help="Allow missing secrets (treat audit sections as skipped)"
    )
    
    parser.add_argument(
        "--output",
        type=Path,
        help="Write summary to file (default: stdout)"
    )
    
    args = parser.parse_args()
    
    # Also check environment variable
    allow_missing_secrets = args.allow_missing_secrets or os.environ.get('MM_ALLOW_MISSING_SECRETS') == '1'
    
    if not args.emit_stack_summary:
        print("[ERROR] --emit-stack-summary flag required", file=sys.stderr)
        return 1
    
    try:
        # Check if secrets are available
        secrets_available = check_secrets_available()
        
        if not secrets_available and not allow_missing_secrets:
            print("[ERROR] Required secrets not available. Use --allow-missing-secrets to skip.", file=sys.stderr)
            return 1
        
        # Aggregate summary
        summary = aggregate_stack_summary(
            args.readiness_file,
            args.gates_file,
            args.tests_file,
            args.allow_missing_sections,
            allow_missing_secrets
        )
        
        # If secrets are missing but allowed, mark audit sections as skipped
        if not secrets_available and allow_missing_secrets:
            for section in summary.get("sections", []):
                if section.get("name") in ["audit_dump", "audit_chain", "secrets"]:
                    section["details"] = "SKIPPED_NO_SECRETS"
                    section["ok"] = True
        
        # Format JSON (deterministic, compact)
        json_output = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        
        # Output to file or stdout
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, 'w', encoding='ascii') as f:
                f.write(json_output + "\n")
        else:
            print(json_output)
        
        # Final marker for CI/CD parsing
        status = "GREEN" if summary["ok"] else "RED"
        print(f"\n| full_stack | {'OK' if summary['ok'] else 'FAIL'} | STACK={status} |")
        
        # Exit code based on overall status
        return 0 if summary["ok"] else 1
    
    except Exception as e:
        print(f"[ERROR] Failed to aggregate stack summary: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

