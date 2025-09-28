from types import SimpleNamespace
from src.guards.autopolicy import AutoPolicy


def test_effective_values():
    cfg = SimpleNamespace(
        enabled=True,
        trigger_backoff_ms=3000.0,
        trigger_events_total=40,
        hysteresis_bad_required=1,
        hysteresis_good_required=1,
        cooldown_minutes=0.0,
        max_level=3,
        min_time_in_book_ms_step_pct=0.15,
        replace_threshold_bps_step_pct=0.15,
        levels_per_side_shrink_step_pct=0.25,
        min_levels_cap=1,
        max_min_time_in_book_ms=60000.0,
        max_replace_threshold_bps=100.0,
        snapshot_path="",
        snapshot_period_sec=60,
    )
    ap = AutoPolicy(cfg)
    ap.set_base(1000, 5, 10)
    ap.level = 2
    eff = ap.apply()
    assert abs(eff['min_time_in_book_ms_eff'] - 1300.0) < 1e-6
    assert abs(eff['replace_threshold_bps_eff'] - 6.5) < 1e-6
    assert int(eff['levels_per_side_max_eff']) == 5

