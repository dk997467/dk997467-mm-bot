"""
Intraday risk caps guard (stdlib-only).

Tracks cumulative PnL, turnover and volatility for the current UTC day and
signals breach when configured daily limits are exceeded. Limits set to 0.0
are treated as disabled.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class IntradayCapsConfig:
    daily_pnl_stop: float = 0.0
    daily_turnover_cap: float = 0.0
    daily_vol_cap: float = 0.0


class IntradayCapsGuard:
    def __init__(self, daily_pnl_stop: float, daily_turnover_cap: float, daily_vol_cap: float) -> None:
        self.daily_pnl_stop = float(max(0.0, daily_pnl_stop))
        self.daily_turnover_cap = float(max(0.0, daily_turnover_cap))
        self.daily_vol_cap = float(max(0.0, daily_vol_cap))
        self.cum_pnl: float = 0.0
        self.cum_turnover: float = 0.0
        self.cum_vol: float = 0.0
        self._current_utc_date: Optional[str] = None

    def record_trade(self, pnl: float, turnover: float, vol: float) -> None:
        self.cum_pnl = float(self.cum_pnl) + float(pnl)
        self.cum_turnover = float(self.cum_turnover) + float(turnover)
        self.cum_vol = float(self.cum_vol) + float(vol)

    def is_breached(self) -> bool:
        # PnL stop: if enabled and cumulative pnl <= -stop
        if self.daily_pnl_stop > 0.0 and float(self.cum_pnl) <= -float(self.daily_pnl_stop):
            return True
        # Turnover cap: if enabled and cumulative turnover >= cap
        if self.daily_turnover_cap > 0.0 and float(self.cum_turnover) >= float(self.daily_turnover_cap):
            return True
        # Volatility cap: if enabled and cumulative vol >= cap
        if self.daily_vol_cap > 0.0 and float(self.cum_vol) >= float(self.daily_vol_cap):
            return True
        return False

    def reset_if_new_day(self, current_utc_date: str) -> None:
        d = str(current_utc_date)
        if self._current_utc_date is None:
            self._current_utc_date = d
            return
        if d != self._current_utc_date:
            self._current_utc_date = d
            # reset state
            self.cum_pnl = 0.0
            self.cum_turnover = 0.0
            self.cum_vol = 0.0


