#!/usr/bin/env python3
"""
Simple test script for walk-forward CLI functionality.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.strategy.tuner import ParameterTuner, compute_walkforward_splits
from src.common.config import AppConfig

def test_walkforward_basics():
    """Test basic walk-forward functionality."""
    print("🧪 Testing walk-forward basics...")
    
    # Create minimal config
    config = AppConfig()
    
    # Create tuner
    tuner = ParameterTuner(config, data_dir=".", symbol="BTCUSDT")
    
    # Test time range
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 5, 0, 0, tzinfo=timezone.utc)
    
    # Generate splits
    splits = compute_walkforward_splits(start, end, train_days=1, validate_hours=12)
    print(f"✅ Generated {len(splits)} splits")
    
    # Test walk-forward tuning (with mocked backtest)
    print("🧪 Testing walk-forward tuning...")
    
    # Mock the _test_parameters method
    def mock_test_parameters(self, params, start_time=None, end_time=None):
        from src.strategy.tuner import TuningResult
        net_pnl = sum(float(v) for v in params.values())
        return TuningResult(
            parameters=params,
            net_pnl=net_pnl,
            total_fees=0.0,
            sharpe_ratio=0.0,
            hit_rate=0.5,
            max_drawdown=0.0,
            cvar_95=0.1,
            objective_value=0.0,
            timestamp=datetime.now(timezone.utc)
        )
    
    # Apply mock
    import types
    tuner._test_parameters = types.MethodType(mock_test_parameters, tuner)
    
    # Run walk-forward
    results = tuner.walk_forward_tuning(
        train_days=1, 
        validate_hours=12, 
        method="random", 
        trials=3,
        seed=42,
        start_time=start, 
        end_time=end
    )
    
    print(f"✅ Walk-forward completed: {results['total_splits']} splits")
    print(f"✅ Seed: {results['seed']}")
    print(f"✅ Method: {results['method']}")
    
    # Check results structure
    assert 'splits' in results
    assert 'total_splits' in results
    assert 'seed' in results
    assert 'method' in results
    
    print("✅ All basic tests passed!")

if __name__ == "__main__":
    test_walkforward_basics()
