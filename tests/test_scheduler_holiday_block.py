from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_scheduler_holiday_blocks_trade_allowed():
    tz = "UTC"
    wins = [{"name": "all_day", "days": [1,2,3,4,5,6,7], "start": "00:00", "end": "23:59"}]
    sch = TimeOfDayScheduler(wins, tz=tz)
    sch.set_holidays(["2025-01-06"])  # Monday

    now = datetime(2025, 1, 6, 9, 0, tzinfo=ZoneInfo(tz))
    assert sch.is_open(now) is True
    assert sch.is_trade_allowed(now) is False  # holiday blocks

