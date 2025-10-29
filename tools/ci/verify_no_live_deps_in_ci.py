#!/usr/bin/env python3
"""
CI Guard Script - Verify No Live Dependencies

This script verifies that live-only dependencies (exchange SDKs) are not
accidentally installed in CI environments where they're not needed.

Usage:
    python tools/ci/verify_no_live_deps_in_ci.py

Exit codes:
    0 - OK: No live dependencies found
    1 - ERROR: Live dependencies found in CI environment
"""

import sys
import subprocess
from typing import List, Tuple


# Live-only dependencies that should NOT be in CI
LIVE_ONLY_DEPS = [
    "bybit-connector",
    "bybit_connector",
]


def check_installed_packages() -> Tuple[List[str], List[str]]:
    """
    Check which packages are installed.
    
    Returns:
        Tuple of (installed_packages, found_live_deps)
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            check=True,
        )
        installed = result.stdout.strip().split("\n")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get pip list: {e}")
        sys.exit(1)
    
    found_live_deps = []
    for pkg in installed:
        pkg_name = pkg.split("==")[0].lower()
        for live_dep in LIVE_ONLY_DEPS:
            if live_dep.lower() in pkg_name:
                found_live_deps.append(pkg)
                break
    
    return installed, found_live_deps


def main() -> int:
    """Main entry point."""
    print("=" * 70)
    print("CI GUARD: Verifying no live dependencies in CI environment")
    print("=" * 70)
    print()
    
    installed, found_live_deps = check_installed_packages()
    
    if not found_live_deps:
        print("✅ OK: No live-only dependencies found")
        print()
        print("CI environment is clean:")
        print("  - No exchange SDKs installed")
        print("  - Safe for shadow/soak/testnet workflows")
        print()
        return 0
    else:
        print("❌ ERROR: Found live-only dependencies in CI environment:")
        print()
        for dep in found_live_deps:
            print(f"  - {dep}")
        print()
        print("These dependencies should only be installed in live workflows.")
        print()
        print("Expected installation:")
        print("  CI workflows:   pip install -e . && pip install -r requirements_ci.txt")
        print("  Live workflows: pip install -e .[live]")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())

