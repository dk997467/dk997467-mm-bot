"""
E2E tests for MultiStratMux with fixtures and golden snapshots.
"""

import json
import yaml
from pathlib import Path

from src.strategy.mux import MultiStratMux
from tests.helpers.fake_clock import FakeClock
from src.metrics.registry import DummyMetricsRegistry


def test_mux_e2e_golden_snapshot():
    """Test MUX with fixtures against golden snapshot."""
    # Load profiles
    profiles_path = Path('tests/fixtures/mux_profiles.yaml')
    with open(profiles_path, 'r') as f:
        profiles_data = yaml.safe_load(f)
    profiles = profiles_data['profiles']
    
    # Load sigma series
    sigma_path = Path('tests/fixtures/mux_sigma_series.jsonl')
    sigma_series = []
    with open(sigma_path, 'r') as f:
        for line in f:
            sigma_series.append(json.loads(line.strip()))
    
    # Setup MUX
    clock = FakeClock(start=0.0)
    metrics = DummyMetricsRegistry()
    mux = MultiStratMux(profiles, hysteresis_s=60, clock=clock.time, metrics=metrics)
    
    # Process series and build snapshot
    snapshot_lines = []
    for entry in sigma_series:
        ts = entry['ts']
        sigma = entry['sigma']
        
        clock.set(ts)
        weights = mux.on_sigma(sigma)
        
        # Format weights deterministically
        weights_str = ",".join(f"{k}:{v:.6f}" for k, v in sorted(weights.items()))
        line = f"ts={ts} regime={mux.current_regime} weights={weights_str}"
        snapshot_lines.append(line)
    
    # Compare with golden
    golden_path = Path('tests/golden/mux_weights_case1.out')
    expected = golden_path.read_text(encoding='ascii')
    actual = "\n".join(snapshot_lines) + "\n"
    
    assert actual == expected
    
    # Additional checks
    for line in snapshot_lines:
        # Check that all weight values match float format
        import re
        weight_matches = re.findall(r':(-?\d+\.\d{6})', line)
        for match in weight_matches:
            assert re.match(r'^-?\d+\.\d{6}$', match)
        
        # Check sum of weights = 1.0 (extract and sum)
        weights_part = line.split('weights=')[1]
        weight_values = [float(w.split(':')[1]) for w in weights_part.split(',')]
        assert abs(sum(weight_values) - 1.0) < 1e-12
