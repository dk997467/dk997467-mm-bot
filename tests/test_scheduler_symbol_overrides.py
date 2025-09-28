from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.tod import TimeOfDayScheduler


def test_scheduler_symbol_overrides_basic():
    tz = "UTC"
    wins_by_symbol = {
        "BTCUSDT": [{"name": "btc_morning", "days": [1,2,3,4,5], "start": "08:00", "end": "12:00"}],
    }
    sch_map = {sym: TimeOfDayScheduler(wins, tz=tz) for sym, wins in wins_by_symbol.items()}

    now = datetime(2025, 1, 6, 9, 0, tzinfo=ZoneInfo(tz))  # Monday 09:00
    assert sch_map["BTCUSDT"].is_open(now) is True

    # ETHUSDT has no specific windows, would be considered closed unless global scheduler exists
    # Here we simulate absence of global windows by not creating a scheduler for ETHUSDT
    # So we only assert BTC is open as per override

