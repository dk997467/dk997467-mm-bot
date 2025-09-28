from __future__ import annotations
import os
import json
import time
from dataclasses import asdict, is_dataclass
from typing import Dict, Any


class AutoPolicy:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.level = 0
        self._consec_bad = 0
        self._consec_good = 0
        self._last_change_ts = 0.0
        self._steps_total = 0
        self._base = {
            "min_time_in_book_ms": None,
            "replace_threshold_bps": None,
            "levels_per_side_max": None,
        }
        self._overrides: Dict[str, float] = {}

    def set_base(self, min_time_in_book_ms: float, replace_threshold_bps: float, levels_per_side_max: int) -> None:
        self._base["min_time_in_book_ms"] = float(min_time_in_book_ms or 0.0)
        self._base["replace_threshold_bps"] = float(replace_threshold_bps or 0.0)
        self._base["levels_per_side_max"] = int(levels_per_side_max or 1)

    def evaluate(self, now: float, backoff_ms_max: float, events_total: int) -> None:
        if not getattr(self.cfg, 'enabled', True):
            return
        bad = (backoff_ms_max >= float(getattr(self.cfg, 'trigger_backoff_ms', 3000.0))) \
              or (int(events_total) >= int(getattr(self.cfg, 'trigger_events_total', 40)))
        if bad:
            self._consec_bad += 1
            self._consec_good = 0
        else:
            self._consec_good += 1
            self._consec_bad = 0

        can_change = (now - self._last_change_ts) >= (float(getattr(self.cfg, 'cooldown_minutes', 2.0)) * 60.0)
        if bad and self._consec_bad >= int(getattr(self.cfg, 'hysteresis_bad_required', 2)) and can_change:
            if self.level < int(getattr(self.cfg, 'max_level', 3)):
                self.level += 1
                self._steps_total += 1
                self._last_change_ts = now
        if (not bad) and self._consec_good >= int(getattr(self.cfg, 'hysteresis_good_required', 2)) and can_change:
            if self.level > 0:
                self.level -= 1
                self._steps_total += 1
                self._last_change_ts = now

    def apply(self) -> Dict[str, float]:
        lvl = int(self.level)
        base_tib = float(self._base["min_time_in_book_ms"] or 0.0)
        base_rep = float(self._base["replace_threshold_bps"] or 0.0)
        base_lvl = int(self._base["levels_per_side_max"] or 1)
        tib = base_tib * (1.0 + float(getattr(self.cfg, 'min_time_in_book_ms_step_pct', 0.15)) * lvl)
        rep = base_rep * (1.0 + float(getattr(self.cfg, 'replace_threshold_bps_step_pct', 0.15)) * lvl)
        lvl_eff = int(round(base_lvl * (1.0 - float(getattr(self.cfg, 'levels_per_side_shrink_step_pct', 0.25)) * lvl)))
        lvl_eff = max(int(getattr(self.cfg, 'min_levels_cap', 1)), lvl_eff)
        tib = min(tib, float(getattr(self.cfg, 'max_min_time_in_book_ms', 60000.0)))
        rep = min(rep, float(getattr(self.cfg, 'max_replace_threshold_bps', 100.0)))
        self._overrides = {
            "min_time_in_book_ms_eff": float(round(tib, 6)),
            "replace_threshold_bps_eff": float(round(rep, 6)),
            "levels_per_side_max_eff": float(lvl_eff),
        }
        return dict(self._overrides)

    def metrics(self) -> Dict[str, float]:
        return {
            "autopolicy_active": 1.0 if (getattr(self.cfg, 'enabled', True) and self.level > 0) else 0.0,
            "autopolicy_level": float(self.level),
            "autopolicy_steps_total": float(self._steps_total),
            "autopolicy_last_change_ts": float(self._last_change_ts),
            **{k: float(v) for k, v in self._overrides.items()},
        }

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "_consec_bad": self._consec_bad,
            "_consec_good": self._consec_good,
            "_last_change_ts": self._last_change_ts,
            "_steps_total": self._steps_total,
            "_base": dict(self._base),
            "_overrides": dict(self._overrides),
            "cfg": asdict(self.cfg) if is_dataclass(self.cfg) else {},
        }

    def load_snapshot(self, data: Dict[str, Any]) -> None:
        try:
            self.level = int(data.get("level", 0))
            self._consec_bad = int(data.get("_consec_bad", 0))
            self._consec_good = int(data.get("_consec_good", 0))
            self._last_change_ts = float(data.get("_last_change_ts", 0.0))
            self._steps_total = int(data.get("_steps_total", 0))
            self._base.update(data.get("_base", {}))
            self._overrides.update(data.get("_overrides", {}))
        except Exception:
            pass


