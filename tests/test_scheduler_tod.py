"""
TimeOfDayScheduler tests: same-day and cross-midnight windows, DOW filtering.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_same_day_window_open_close():
    tz = 'UTC'
    sch = TimeOfDayScheduler([
        {"name": "eu_morning", "days": [1,2,3,4,5], "start": "08:00", "end": "12:00"}
    ], tz=tz)
    # Monday 09:00 UTC
    now = datetime(2025, 1, 6, 9, 0, tzinfo=ZoneInfo(tz))
    assert sch.is_open(now)
    assert sch.current_window(now) == "eu_morning"
    # Monday 13:00 UTC
    now2 = datetime(2025, 1, 6, 13, 0, tzinfo=ZoneInfo(tz))
    assert not sch.is_open(now2)
    assert sch.current_window(now2) is None


def test_cross_midnight_window():
    tz = 'UTC'
    sch = TimeOfDayScheduler([
        {"name": "night", "days": [1,2,3,4,5], "start": "22:00", "end": "02:00"}
    ], tz=tz)
    # Monday 23:00 (in window)
    now = datetime(2025, 1, 6, 23, 0, tzinfo=ZoneInfo(tz))
    assert sch.is_open(now)
    assert sch.current_window(now) == "night"
    # Tuesday 01:00 (still in window from previous day night)
    now2 = datetime(2025, 1, 7, 1, 0, tzinfo=ZoneInfo(tz))
    assert sch.is_open(now2)
    assert sch.current_window(now2) == "night"
    # Tuesday 03:00 (outside)
    now3 = datetime(2025, 1, 7, 3, 0, tzinfo=ZoneInfo(tz))
    assert not sch.is_open(now3)


