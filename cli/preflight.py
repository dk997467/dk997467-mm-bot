"""
CLI entry point for RC-Validator preflight checks.
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.deploy.rc_validator import main as rc_main


def main() -> None:
    """Run RC validator and print summary."""
    exit_code = rc_main(None)
    
    if exit_code == 0:
        print("rc_validator: ok")
    else:
        # Try to read error count from report
        try:
            import json
            with open("artifacts/rc_validator.json", "r", encoding="utf-8") as f:
                report = json.load(f)
            error_count = len(report.get("errors", []))
            print(f"rc_validator: failed ({error_count} errors)")
        except Exception:
            print("rc_validator: failed")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
