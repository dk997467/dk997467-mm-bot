"""
Unit tests for MultiStratMux.
"""

from src.strategy.mux import MultiStratMux
from tests.helpers.fake_clock import FakeClock
from src.metrics.registry import DummyMetricsRegistry


def test_regime_mapping_exact_edges():
    """Test regime mapping at exact band edges."""
    profiles = {
        'low': {'weights': {'A': 1.0}, 'band': [0.0, 0.8]},
        'mid': {'weights': {'B': 1.0}, 'band': [0.8, 1.5]},
        'high': {'weights': {'C': 1.0}, 'band': [1.5, 9.99]}
    }
    
    clock = FakeClock()
    mux = MultiStratMux(profiles, hysteresis_s=0, clock=clock.time)
    
    # Test exact boundaries (left-inclusive, right-exclusive)
    assert mux._determine_regime(0.0) == 'low'
    assert mux._determine_regime(0.79) == 'low'
    assert mux._determine_regime(0.8) == 'mid'
    assert mux._determine_regime(1.49) == 'mid'
    assert mux._determine_regime(1.5) == 'high'
    assert mux._determine_regime(9.99) == 'high'  # Last band includes upper bound


def test_hysteresis_holds_for_60s():
    """Test that hysteresis prevents switching for 60s."""
    profiles = {
        'low': {'weights': {'A': 1.0}, 'band': [0.0, 0.8]},
        'high': {'weights': {'B': 1.0}, 'band': [0.8, 9.99]}
    }
    
    clock = FakeClock()
    mux = MultiStratMux(profiles, hysteresis_s=60, clock=clock.time)
    
    # Start in low regime
    weights = mux.on_sigma(0.5)
    assert mux.current_regime == 'low'
    assert weights['A'] == 1.0
    
    # Try to switch after 30s - should stay in low due to hysteresis
    clock.tick(30)
    weights = mux.on_sigma(1.5)  # Should trigger high regime
    assert mux.current_regime == 'low'  # But stays low due to hysteresis
    assert weights['A'] == 1.0


def test_switch_after_60s():
    """Test that regime switches after hysteresis period."""
    profiles = {
        'low': {'weights': {'A': 1.0}, 'band': [0.0, 0.8]},
        'high': {'weights': {'B': 1.0}, 'band': [0.8, 9.99]}
    }
    
    clock = FakeClock()
    mux = MultiStratMux(profiles, hysteresis_s=60, clock=clock.time)
    
    # Start in low regime
    mux.on_sigma(0.5)
    assert mux.current_regime == 'low'
    
    # Switch after 60s
    clock.tick(60)
    weights = mux.on_sigma(1.5)
    assert mux.current_regime == 'high'
    assert weights['B'] == 1.0


def test_weight_caps_and_normalization():
    """Test weight caps and normalization."""
    profiles = {
        'test': {
            'weights': {'A': 0.6, 'B': 0.4},
            'band': [0.0, 9.99]
        }
    }
    
    clock = FakeClock()
    weight_caps = {'A': 0.3}  # Cap A at 30%
    mux = MultiStratMux(profiles, weight_caps=weight_caps, clock=clock.time)
    
    weights = mux.on_sigma(0.5)
    
    # A should be capped at 0.3, then normalized
    # Original: A=0.6, B=0.4 -> Capped: A=0.3, B=0.4 -> Normalized: A=0.3/0.7, B=0.4/0.7
    expected_a = 0.3 / 0.7
    expected_b = 0.4 / 0.7
    
    assert abs(weights['A'] - expected_a) < 1e-12
    assert abs(weights['B'] - expected_b) < 1e-12
    assert abs(sum(weights.values()) - 1.0) < 1e-12


def test_determinism():
    """Test that identical inputs produce identical outputs."""
    profiles = {
        'low': {'weights': {'A': 0.7, 'B': 0.3}, 'band': [0.0, 0.8]},
        'high': {'weights': {'A': 0.3, 'B': 0.7}, 'band': [0.8, 9.99]}
    }
    
    # Run 1
    clock1 = FakeClock()
    mux1 = MultiStratMux(profiles, hysteresis_s=60, clock=clock1.time)
    results1 = []
    for sigma in [0.5, 0.9, 0.7]:
        clock1.tick(30)
        weights = mux1.on_sigma(sigma)
        results1.append((mux1.current_regime, tuple(sorted(weights.items()))))
    
    # Run 2
    clock2 = FakeClock()
    mux2 = MultiStratMux(profiles, hysteresis_s=60, clock=clock2.time)
    results2 = []
    for sigma in [0.5, 0.9, 0.7]:
        clock2.tick(30)
        weights = mux2.on_sigma(sigma)
        results2.append((mux2.current_regime, tuple(sorted(weights.items()))))
    
    assert results1 == results2


def test_metrics_no_crash_with_dummy_registry():
    """Test that DummyMetricsRegistry doesn't crash."""
    profiles = {
        'test': {'weights': {'A': 1.0}, 'band': [0.0, 9.99]}
    }
    
    clock = FakeClock()
    metrics = DummyMetricsRegistry()
    mux = MultiStratMux(profiles, clock=clock.time, metrics=metrics)
    
    # Should not crash
    weights = mux.on_sigma(0.5)
    assert weights['A'] == 1.0
