"""
Daily reset helper (UTC) for guards.

Provides a deterministic check for UTC date rollover. stdlib-only.
"""

from datetime import datetime, timezone


def current_utc_date_str() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def should_reset(prev_date: str, now_date: str) -> bool:
    return str(prev_date) != str(now_date)


