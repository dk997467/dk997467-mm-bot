from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_dst_transition_berlin_no_exceptions():
    sch = TimeOfDayScheduler(
      [{"name":"morning","days":[1,2,3,4,5,6,7],"start":"01:30","end":"03:30"}],
      tz="Europe/Berlin"
    )
    t1 = datetime(2025,3,30,1,45, tzinfo=ZoneInfo("Europe/Berlin"))
    t2 = datetime(2025,3,30,3,15, tzinfo=ZoneInfo("Europe/Berlin"))
    assert isinstance(sch.is_open(t1), bool)
    assert isinstance(sch.is_open(t2), bool)
    assert sch.next_change(t1) is not None


