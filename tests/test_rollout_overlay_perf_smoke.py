"""
Smoke test: N applications of compiled overlays without errors (not a benchmark).
"""
from types import SimpleNamespace


def test_rollout_overlay_perf_smoke():
    from src.execution.order_manager import OrderManager

    class _RESTStub:
        def __init__(self):
            pass
        def _round_to_tick(self, p, s): 
            return p
        def _round_to_lot(self, q, s): 
            return q

    # Setup
    base = {
        'autopolicy': {'level_max': 6},
        'levels_per_side_max': 6,
        'replace_threshold_bps': 2.0,
        'nested': {'a': {'b': {'c': 1}}}
    }
    
    overlay = {
        "autopolicy.level_max": 3, 
        "replace_threshold_bps": 3.5,
        "nested.a.b.c": 999,
        "new_path.x.y": "test"
    }

    cfg = SimpleNamespace(
        strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        rollout=SimpleNamespace(
            traffic_split_pct=50, active="blue", salt="test", 
            pinned_cids_green=[], blue={}, green=overlay
        )
    )
    ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_overlay_compiled=lambda: None))
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    # Compile overlays
    om.update_rollout_config(cfg.rollout)
    
    # Smoke test: apply overlays N times without errors
    N = 100
    results = []
    for i in range(N):
        try:
            result = om._apply_overlay(base, overlay)
            results.append(result)
            # Verify consistency
            assert result['autopolicy']['level_max'] == 3
            assert result['nested']['a']['b']['c'] == 999
            assert result['new_path']['x']['y'] == "test"
        except Exception as e:
            assert False, f"Application {i} failed: {e}"
    
    # All results should be identical
    first_result = results[0]
    for i, result in enumerate(results[1:], 1):
        assert result == first_result, f"Result {i} differs from first result"
    
    # Base should remain unchanged after N applications
    assert base['autopolicy']['level_max'] == 6
    assert base['nested']['a']['b']['c'] == 1
    assert 'new_path' not in base  # new path should not leak into base
    
    print(f"✓ Applied compiled overlay {N} times successfully")
