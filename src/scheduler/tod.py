"""
Time-of-day scheduler for trading windows.

Windows format example:
{"name": "eu_morning", "days": [1,2,3,4,5], "start": "08:00", "end": "12:00"}

Notes:
- days use ISO weekday numbers: Mon=1 ... Sun=7
- supports cross-midnight windows (end < start)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any, Tuple
from zoneinfo import ZoneInfo


@dataclass
class _Window:
    name: str
    days: List[int]
    start: time
    end: time


class TimeOfDayScheduler:
    def __init__(self, windows: List[Dict[str, Any]], tz: str = 'UTC', cooldown_open_minutes: float = 0.0, cooldown_close_minutes: float = 0.0, block_in_cooldown: bool = True) -> None:
        self._tz = tz or 'UTC'
        self._zone = ZoneInfo(self._tz)
        self._windows: List[_Window] = []
        self._cool_open = float(cooldown_open_minutes or 0.0)
        self._cool_close = float(cooldown_close_minutes or 0.0)
        self._block = bool(block_in_cooldown)
        self._last_transition_ts: Optional[datetime] = None
        self._next_transition_ts: Optional[datetime] = None
        self._holiday: Optional[HolidayCalendar] = None
        self.set_windows(windows or [])

    def set_windows(self, windows: List[Dict[str, Any]]) -> None:
        parsed: List[_Window] = []
        for w in windows or []:
            try:
                name = str(w.get('name', ''))
                days = list(w.get('days', []))
                s_raw = str(w.get('start', '00:00'))
                e_raw = str(w.get('end', '00:00'))
                hh, mm = s_raw.split(':')
                ss = time(int(hh), int(mm))
                hh2, mm2 = e_raw.split(':')
                ee = time(int(hh2), int(mm2))
                parsed.append(_Window(name=name, days=days, start=ss, end=ee))
            except Exception:
                continue
        self._windows = parsed
        # reset cached transitions on windows update
        self._last_transition_ts = None
        self._next_transition_ts = None

    def _local_now(self, now: Optional[datetime]) -> datetime:
        if now is None:
            return datetime.now(self._zone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self._zone)
        return now.astimezone(self._zone)

    def current_window(self, now: Optional[datetime] = None) -> Optional[str]:
        dtn = self._local_now(now)
        t = dtn.timetz().replace(tzinfo=None)
        iso_day = dtn.isoweekday()  # 1..7
        # also need prev day
        prev_day = ((iso_day + 5) % 7) + 1  # 1..7

        for w in self._windows:
            if self._is_open_for_window(w, iso_day, prev_day, t):
                return w.name
        return None

    def is_open(self, now: Optional[datetime] = None) -> bool:
        return self.current_window(now) is not None

    def is_trade_allowed(self, now: Optional[datetime] = None) -> bool:
        open_now = self.is_open(now)
        if not open_now:
            return False
        # holiday block
        try:
            if self._holiday and self._holiday.is_holiday(self._local_now(now)):
                return False
        except Exception:
            pass
        if self._block and self.in_cooldown_open(now):
            return False
        return True

    def in_cooldown_open(self, now: Optional[datetime] = None) -> bool:
        if self._cool_open <= 0:
            return False
        last = self._last_transition(now)
        if not last:
            return False
        if not self.is_open(now):
            return False
        delta = self._local_now(now) - last
        return delta.total_seconds() < self._cool_open * 60.0

    def in_cooldown_close(self, now: Optional[datetime] = None) -> bool:
        if self._cool_close <= 0:
            return False
        last = self._last_transition(now)
        if not last:
            return False
        if self.is_open(now):
            return False
        delta = self._local_now(now) - last
        return delta.total_seconds() < self._cool_close * 60.0

    def next_change(self, now: Optional[datetime] = None) -> Optional[datetime]:
        dtn = self._local_now(now)
        candidates: List[datetime] = []
        for off in (0, 1):
            day = dtn.date() + timedelta(days=off)
            iso_day = (dtn.isoweekday() + off - 1) % 7 + 1
            prev_iso_for_day = ((iso_day + 5) % 7) + 1
            for w in self._windows:
                st = datetime.combine(day, w.start, tzinfo=self._zone)
                en_same = datetime.combine(day, w.end, tzinfo=self._zone)
                if w.start <= w.end:
                    if iso_day in w.days:
                        if st > dtn:
                            candidates.append(st)
                        if en_same > dtn:
                            candidates.append(en_same)
                else:
                    # cross-midnight: start belongs to iso_day; end belongs to previous day window
                    if iso_day in w.days:
                        if st > dtn:
                            candidates.append(st)
                    if prev_iso_for_day in w.days:
                        en = datetime.combine(day, w.end, tzinfo=self._zone)
                        if en > dtn:
                            candidates.append(en)
        if not candidates:
            return None
        nxt = min(candidates)
        self._next_transition_ts = nxt
        return nxt

    def _last_transition(self, now: Optional[datetime]) -> Optional[datetime]:
        dtn = self._local_now(now)
        if self._last_transition_ts and self._last_transition_ts <= dtn:
            return self._last_transition_ts
        candidates: List[datetime] = []
        for off in (-1, 0):
            day = dtn.date() + timedelta(days=off)
            iso_day = (dtn.isoweekday() + off - 1) % 7 + 1
            for w in self._windows:
                if iso_day in w.days:
                    st = datetime.combine(day, w.start, tzinfo=self._zone)
                    en = datetime.combine(day, w.end, tzinfo=self._zone)
                    if w.start <= w.end:
                        if st <= dtn:
                            candidates.append(st)
                        if en <= dtn:
                            candidates.append(en)
                    else:
                        if st <= dtn:
                            candidates.append(st)
                        prev_day = day - timedelta(days=1)
                        en_prev = datetime.combine(prev_day, w.end, tzinfo=self._zone)
                        if en_prev <= dtn:
                            candidates.append(en_prev)
        if not candidates:
            return None
        self._last_transition_ts = max(candidates)
        return self._last_transition_ts

    def update_params(self, tz: str, co: float, cc: float, block: bool) -> None:
        # Update tz and cooldown params, reset caches
        try:
            self._tz = tz or 'UTC'
            self._zone = ZoneInfo(self._tz)
        except Exception:
            # keep previous tz on failure
            pass
        self._cool_open = float(co or 0.0)
        self._cool_close = float(cc or 0.0)
        self._block = bool(block)
        self._last_transition_ts = None
        self._next_transition_ts = None

    def set_holidays(self, dates: List[str]) -> None:
        try:
            self._holiday = HolidayCalendar(self._tz, dates or [])
        except Exception:
            self._holiday = None

    def _is_open_for_window(self, w: _Window, iso_day: int, prev_day: int, t: time) -> bool:
        start = w.start
        end = w.end
        if start <= end:
            # same-day window
            if iso_day in w.days and (start <= t < end):
                return True
            return False
        # cross-midnight window (e.g., 22:00 -> 02:00)
        if t >= start:
            # same day after start
            return iso_day in w.days
        elif t < end:
            # after midnight before end -> attribute to previous day
            return prev_day in w.days
        else:
            return False
class HolidayCalendar:
    def __init__(self, tz: str, dates: List[str]):
        self._zone = ZoneInfo(tz or 'UTC')
        self._days = set(dates or [])

    def is_holiday(self, dt: datetime) -> bool:
        local = dt.astimezone(self._zone)
        key = f"{local.year:04d}-{local.month:02d}-{local.day:02d}"
        return key in self._days


def suggest_windows(stats: Dict[str, Dict[str, float]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Suggest top windows by quality score.

    stats: {"HH:MM-HH:MM": {"median_spread_bps":float, "vola_ewma":float, "volume_norm":float, "sample":int}}
    cfg: {"top_k":int, "min_sample":int, "mode":"conservative|neutral|aggressive"}
    """
    try:
        top_k = int(cfg.get('top_k', 6))
    except Exception:
        top_k = 6
    try:
        min_sample = int(cfg.get('min_sample', 200))
    except Exception:
        min_sample = 200
    mode = str(cfg.get('mode', 'neutral')).lower()
    # mode weights: lower spread/vola better; higher volume better
    if mode == 'conservative':
        w_spread, w_vola, w_vol = (0.5, 0.3, 0.2)
    elif mode == 'aggressive':
        w_spread, w_vola, w_vol = (0.2, 0.2, 0.6)
    else:
        w_spread, w_vola, w_vol = (0.35, 0.25, 0.40)
    candidates: List[Tuple[float, str, Dict[str, Any]]] = []
    for key in sorted(stats.keys()):
        try:
            d = stats[key] or {}
            if int(d.get('sample', 0)) < min_sample:
                continue
            spread = max(0.0, float(d.get('median_spread_bps', 0.0)))
            vola = max(0.0, float(d.get('vola_ewma', 0.0)))
            vol = max(0.0, float(d.get('volume_norm', 0.0)))
            # normalize to [0,1] by simple clamps; avoid div-by-zero
            s_norm = 1.0 - min(1.0, spread / 50.0)
            v_norm = 1.0 - min(1.0, vola / 100.0)
            vol_norm = min(1.0, vol / 1.0)
            score = w_spread * s_norm + w_vola * v_norm + w_vol * vol_norm
            start, end = key.split('-')
            candidates.append((float(score), key, {"start": start, "end": end, "score": float(score)}))
        except Exception:
            continue
    # deterministic top-k
    candidates.sort(key=lambda x: (-x[0], x[1]))
    out = [c[2] for c in candidates[:top_k]]
    return out

