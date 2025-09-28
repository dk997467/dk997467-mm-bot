from src.deploy.rollout import format_json_output
from src.deploy.gate import make_canary_patch
from src.deploy.thresholds import GateThresholds


def test_soften_canary_calc_only():
    # Baseline patch and thresholds
    patch_full = {"levels_per_side": 8, "min_time_in_book_ms": 1000, "replace_threshold_bps": 5.0}
    # Softening factors
    thr = GateThresholds(
        autopolicy_soft_canary_shrink_pct=0.25,
        autopolicy_soft_tib_bump_pct=0.15,
        autopolicy_soft_repbps_bump_pct=0.15,
    )
    # initial canary shrink
    patch_canary = make_canary_patch(patch_full, shrink=0.5)
    # emulate soften
    shrink2 = 0.5 * (1.0 - thr.autopolicy_soft_canary_shrink_pct)
    patch_soft = make_canary_patch(patch_full, shrink=shrink2)
    if 'min_time_in_book_ms' in patch_soft:
        patch_soft['min_time_in_book_ms'] = int(round(patch_soft['min_time_in_book_ms'] * (1.0 + thr.autopolicy_soft_tib_bump_pct)))
    if 'replace_threshold_bps' in patch_soft:
        patch_soft['replace_threshold_bps'] = float(round(patch_soft['replace_threshold_bps'] * (1.0 + thr.autopolicy_soft_repbps_bump_pct), 6))
    # sanity checks
    assert patch_soft['levels_per_side'] <= patch_canary['levels_per_side']
    assert patch_soft['min_time_in_book_ms'] >= patch_canary.get('min_time_in_book_ms', 0)
    assert patch_soft['replace_threshold_bps'] >= patch_canary.get('replace_threshold_bps', 0.0)

