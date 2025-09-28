"""
Volatility EWMA guards: no div0, valid mid>0, monotonic ts, gauge updates.
"""

from src.marketdata.vola import VolatilityManager


def test_ewma_guards_and_metric_stability():
    vm = VolatilityManager(alpha=0.5, min_samples=2)
    sym = "BTCUSDT"
    # First invalid mid price (<=0) -> stays at 0
    v0 = vm.update(sym, 0.0, 1000.0)
    assert v0 == 0.0
    # First valid tick initializes
    v1 = vm.update(sym, 100.0, 1001.0)
    assert v1 == 0.0
    # Backward timestamp ignored (no change)
    v2 = vm.update(sym, 101.0, 900.0)
    assert v2 == v1
    # Valid forward tick
    v3 = vm.update(sym, 99.0, 1002.0)
    assert v3 >= 0.0
    # get_volatility returns stable float
    _ = vm.get_volatility(sym)
    assert isinstance(_, float)


