"""
Test that rollout_overlay_compiled_total metric increments only once per compilation.
"""
from types import SimpleNamespace


def test_rollout_overlay_compiled_once():
    from src.execution.order_manager import OrderManager

    class _RESTStub:
        def __init__(self):
            pass
        def _round_to_tick(self, p, s): 
            return p
        def _round_to_lot(self, q, s): 
            return q

    class MockMetrics:
        def __init__(self):
            self.compiled_count = 0
        
        def inc_rollout_overlay_compiled(self):
            self.compiled_count += 1

    # Setup with mock metrics
    overlay_green = {"autopolicy.level_max": 3, "replace_threshold_bps": 3.5}
    cfg = SimpleNamespace(
        strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        rollout=SimpleNamespace(
            traffic_split_pct=50, active="blue", salt="test", 
            pinned_cids_green=[], blue={}, green=overlay_green
        )
    )
    
    metrics = MockMetrics()
    ctx = SimpleNamespace(cfg=cfg, metrics=metrics)
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    # Test 1: First compilation should increment metric
    assert metrics.compiled_count == 0, "Initial count should be 0"
    
    om.update_rollout_config(cfg.rollout)
    assert metrics.compiled_count == 1, "First compilation should increment metric"
    
    # Test 2: Subsequent updates with same overlays should increment again
    om.update_rollout_config(cfg.rollout)
    assert metrics.compiled_count == 2, "Second compilation should increment metric again"
    
    # Test 3: Empty overlays should not increment metric
    empty_rollout = SimpleNamespace(
        traffic_split_pct=0, active="blue", salt="test",
        pinned_cids_green=[], blue={}, green={}
    )
    om.update_rollout_config(empty_rollout)
    assert metrics.compiled_count == 2, "Empty overlays should not increment metric"
    
    # Test 4: Using compiled overlays multiple times should not increment
    base = {'autopolicy': {'level_max': 6}, 'replace_threshold_bps': 2.0}
    om.update_rollout_config(cfg.rollout)  # Re-enable overlays (this increments once more)
    initial_count = metrics.compiled_count
    
    # Apply overlay multiple times
    for _ in range(10):
        om._apply_overlay(base, overlay_green)
    
    assert metrics.compiled_count == initial_count, "Multiple applications should not increment metric"
    
    print(f"✓ Metric incremented correctly: {metrics.compiled_count} times")
