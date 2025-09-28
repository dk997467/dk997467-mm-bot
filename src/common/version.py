"""
Version and runtime information for artifacts.
"""

import os
from datetime import datetime, timezone


VERSION = "0.1.0"


def get_git_sha_short() -> str:
    """Get short git SHA from .git/HEAD and refs (stdlib only)."""
    try:
        git_dir = ".git"
        if not os.path.exists(git_dir):
            return "unknown"
        
        head_path = os.path.join(git_dir, "HEAD")
        if not os.path.exists(head_path):
            return "unknown"
        
        with open(head_path, 'r', encoding='utf-8') as f:
            head_content = f.read().strip()
        
        if head_content.startswith("ref: "):
            # Branch reference
            ref_path = head_content[5:]  # Remove "ref: "
            ref_file = os.path.join(git_dir, ref_path)
            if os.path.exists(ref_file):
                with open(ref_file, 'r', encoding='utf-8') as f:
                    sha = f.read().strip()
                    return sha[:8] if len(sha) >= 8 else sha
        elif len(head_content) >= 8:
            # Direct SHA
            return head_content[:8]
        
        return "unknown"
    except Exception:
        return "unknown"


def get_mode() -> str:
    """Get mode from MM_MODE env var."""
    return os.environ.get("MM_MODE", "sim").lower()


def get_env() -> str:
    """Get environment from MM_ENV env var."""
    return os.environ.get("MM_ENV", "dev").lower()


def utc_now_str() -> str:
    """Get current UTC time as YYYY-MM-DDTHH:MM:SSZ (no milliseconds)."""
    try:
        if os.environ.get("MM_FREEZE_UTC") == "1":
            return "1970-01-01T00:00:00Z"
    except Exception:
        pass
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
