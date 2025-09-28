from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_overlap_priority_first_wins():
    sch = TimeOfDayScheduler(
      [
        {"name":"winA","days":[1,2,3,4,5],"start":"08:00","end":"12:00"},
        {"name":"winB","days":[1,2,3,4,5],"start":"10:00","end":"11:00"},
      ],
      tz="UTC"
    )
    now = datetime(2025,1,6,10,30, tzinfo=ZoneInfo("UTC"))
    assert sch.is_open(now) is True
    assert sch.current_window(now) == "winA"


