#!/usr/bin/env python3
import os
import sys
import json


def _exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except Exception:
        return False


def main() -> int:
    issues = []

    # Ensure base directories exist
    for d in ("artifacts",):
        if not _exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                issues.append(f"mkdir_failed:{d}")

    # Minimal presence checks to improve local UX
    for f in ("pyrightconfig.json", ".cursorignore"):
        if not _exists(f):
            issues.append(f"missing:{f}")

    status = "GREEN" if not issues else "YELLOW"
    out = {"daily_check": status, "issues": issues}
    print(json.dumps(out, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
