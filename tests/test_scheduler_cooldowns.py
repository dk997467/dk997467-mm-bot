from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_open_cooldown_blocks_trade_allowed():
    sch = TimeOfDayScheduler(
        [{"name":"eu","days":[1,2,3,4,5],"start":"08:00","end":"12:00"}],
        tz="UTC", cooldown_open_minutes=10.0, block_in_cooldown=True
    )
    now = datetime(2025,1,6,8,1, tzinfo=ZoneInfo("UTC"))
    assert sch.is_open(now) is True
    assert sch.in_cooldown_open(now) is True
    assert sch.is_trade_allowed(now) is False

    now2 = datetime(2025,1,6,8,15, tzinfo=ZoneInfo("UTC"))
    assert sch.is_open(now2) is True
    assert sch.in_cooldown_open(now2) is False
    assert sch.is_trade_allowed(now2) is True


