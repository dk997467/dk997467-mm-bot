"""
Runtime mode utilities.

Mode is controlled by env var MM_MODE.
"""

import os


def current_mode() -> str:
    return os.environ.get("MM_MODE", "sim").lower()


