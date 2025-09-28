"""
Test compiled overlays: semantics identical to plain, base not mutated, deterministic.
"""
from types import SimpleNamespace


def test_rollout_overlay_compiled_paths():
    from src.execution.order_manager import OrderManager

    class _RESTStub:
        def __init__(self):
            pass
        def _round_to_tick(self, p, s): 
            return p
        def _round_to_lot(self, q, s): 
            return q

    # Test data
    base = {
        'autopolicy': {'level_max': 6, 'other': 'kept'},
        'levels_per_side_max': 6,
        'replace_threshold_bps': 2.0,
        'nested': {'deep': {'value': 42}}
    }
    
    overlay_green = {
        "autopolicy.level_max": 3, 
        "replace_threshold_bps": 3.5,
        "nested.deep.value": 99,
        "new_key": "added"
    }
    overlay_blue = {}

    cfg = SimpleNamespace(
        strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        rollout=SimpleNamespace(
            traffic_split_pct=50, active="blue", salt="test", 
            pinned_cids_green=[], blue=overlay_blue, green=overlay_green
        )
    )
    ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_overlay_compiled=lambda: None))
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    # Update rollout config to trigger compilation
    om.update_rollout_config(cfg.rollout)
    
    # Store original base id to verify no mutation
    original_base_id = id(base)
    original_autopolicy_id = id(base['autopolicy'])
    original_nested_id = id(base['nested'])
    
    # Apply compiled overlays
    result_green_compiled = om._apply_overlay(base, overlay_green)
    result_blue_compiled = om._apply_overlay(base, overlay_blue)
    
    # Clear compiled overlays and test fallback
    om._rollout_compiled = {"blue": [], "green": []}
    result_green_plain = om._apply_overlay(base, overlay_green)
    result_blue_plain = om._apply_overlay(base, overlay_blue)
    
    # Test 1: Compiled == Plain semantics
    assert result_green_compiled == result_green_plain, "Green compiled must match plain"
    assert result_blue_compiled == result_blue_plain, "Blue compiled must match plain"
    
    # Test 2: Base not mutated (id unchanged)
    assert id(base) == original_base_id, "Base dict must not be mutated"
    assert id(base['autopolicy']) == original_autopolicy_id, "Nested autopolicy dict must not be mutated"
    assert id(base['nested']) == original_nested_id, "Nested dict must not be mutated"
    assert base['autopolicy']['level_max'] == 6, "Base value must remain unchanged"
    assert base['replace_threshold_bps'] == 2.0, "Base value must remain unchanged"
    assert base['nested']['deep']['value'] == 42, "Deep nested value must remain unchanged"
    
    # Test 3: Results have correct values
    assert result_green_compiled['autopolicy']['level_max'] == 3
    assert result_green_compiled['replace_threshold_bps'] == 3.5
    assert result_green_compiled['nested']['deep']['value'] == 99
    assert result_green_compiled['new_key'] == "added"
    assert result_green_compiled['autopolicy']['other'] == "kept"  # preserved from base
    
    assert result_blue_compiled['autopolicy']['level_max'] == 6  # unchanged from base
    assert result_blue_compiled['replace_threshold_bps'] == 2.0  # unchanged from base
    
    # Test 4: Deterministic compilation order
    compiled_green = om._compile_overlay(overlay_green)
    compiled_green_2 = om._compile_overlay(overlay_green)
    assert compiled_green == compiled_green_2, "Compilation must be deterministic"
    assert len(compiled_green) == 4, "Should have 4 compiled paths"
    # Verify sorted order by path tuple
    paths = [path for path, _ in compiled_green]
    assert paths == sorted(paths), "Compiled paths must be sorted"
