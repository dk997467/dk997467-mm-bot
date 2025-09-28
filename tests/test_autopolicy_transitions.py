import time
from types import SimpleNamespace
from src.guards.autopolicy import AutoPolicy


def _cfg(**kw):
    base = dict(enabled=True, trigger_backoff_ms=3000.0, trigger_events_total=40,
                hysteresis_bad_required=2, hysteresis_good_required=2, cooldown_minutes=0.0,
                max_level=3, min_time_in_book_ms_step_pct=0.15, replace_threshold_bps_step_pct=0.15,
                levels_per_side_shrink_step_pct=0.25, min_levels_cap=1,
                max_min_time_in_book_ms=60000.0, max_replace_threshold_bps=100.0,
                snapshot_path="", snapshot_period_sec=60)
    base.update(kw)
    return SimpleNamespace(**base)


def test_autopolicy_escalate_and_deescalate():
    ap = AutoPolicy(_cfg())
    ap.set_base(1000, 5, 10)
    now = time.time()
    # bad twice
    ap.evaluate(now, 4000, 0)
    ap.evaluate(now + 1, 4000, 0)
    ap.apply()
    assert ap.level == 1
    # good twice -> down
    ap.evaluate(now + 2, 0, 0)
    ap.evaluate(now + 3, 0, 0)
    ap.apply()
    assert ap.level == 0


def test_autopolicy_cooldown():
    ap = AutoPolicy(_cfg(cooldown_minutes=10.0))
    ap.set_base(1000, 5, 10)
    t = time.time()
    ap.evaluate(t, 4000, 0)
    ap.evaluate(t + 1, 4000, 0)
    ap.apply()
    # tries to escalate again during cooldown
    lvl_before = ap.level
    ap.evaluate(t + 2, 4000, 0)
    ap.evaluate(t + 3, 4000, 0)
    ap.apply()
    assert ap.level == lvl_before

