#!/usr/bin/env python3
"""
Extended unit tests for tools/tuning/apply_from_sweep.py — Candidate selection logic.

Tests:
- _simulate function (deterministic calculations)
- Selector logic (simulated without subprocess)
- Edge cases: empty config, missing fields
- main() function (CLI logic with file I/O mocking)
"""
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
from tools.tuning.apply_from_sweep import _simulate, main


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def sweep_basic():
    """Basic valid sweep result."""
    return {
        'results': [
            {'metrics': {'net_bps': 3.0, 'order_age_p95_ms': 320.0, 'fill_rate': 0.7, 'replace_rate_per_min': 300.0}}
        ],
        'top3_by_net_bps_safe': [
            {
                'params': {'max_delta_ratio': 0.12, 'impact_cap_ratio': 0.08},
                'metrics': {'net_bps': 3.2, 'order_age_p95_ms': 300.0, 'replace_rate_per_min': 280.0, 'fill_rate': 0.75}
            },
            {
                'params': {'max_delta_ratio': 0.10, 'impact_cap_ratio': 0.06},
                'metrics': {'net_bps': 3.1, 'order_age_p95_ms': 310.0, 'replace_rate_per_min': 290.0, 'fill_rate': 0.72}
            },
        ],
    }


@pytest.fixture
def sweep_no_top3():
    """Sweep with results but no top3_by_net_bps_safe."""
    return {
        'results': [
            {
                'params': {'max_delta_ratio': 0.15, 'impact_cap_ratio': 0.10},
                'metrics': {'net_bps': 2.8, 'order_age_p95_ms': 340.0, 'replace_rate_per_min': 320.0, 'fill_rate': 0.68}
            }
        ]
    }


@pytest.fixture
def sweep_empty():
    """Empty sweep (no results)."""
    return {'results': []}


# ======================================================================
# Test Selector Logic (Simulated from sweep data)
# ======================================================================

def test_selector_top3_structure(sweep_basic):
    """Test top3_by_net_bps_safe has expected structure."""
    top3 = sweep_basic.get('top3_by_net_bps_safe', [])
    
    assert len(top3) == 2
    assert 'params' in top3[0]
    assert 'metrics' in top3[0]


def test_selector_fallback_structure(sweep_no_top3):
    """Test fallback to results[0] structure."""
    results = sweep_no_top3.get('results', [])
    
    assert len(results) == 1
    assert 'params' in results[0]
    assert 'metrics' in results[0]


def test_selector_empty_sweep(sweep_empty):
    """Test empty sweep has no results."""
    assert sweep_empty['results'] == []
    assert 'top3_by_net_bps_safe' not in sweep_empty


# ======================================================================
# Test _simulate Function (Direct Unit Test)
# ======================================================================

def test_simulate_empty_config():
    """Test _simulate with empty config."""
    from tools.tuning.apply_from_sweep import _simulate
    
    result = _simulate({})
    
    assert result['status'] == 'OK'
    assert result['applied'] is False
    assert result['metrics']['edge_bps'] == 0.0


def test_simulate_with_config():
    """Test _simulate with valid config."""
    from tools.tuning.apply_from_sweep import _simulate
    
    config = {
        'touch_dwell_ms': 30,
        'risk_limit': 0.35
    }
    
    result = _simulate(config)
    
    assert result['status'] == 'OK'
    assert result['applied'] is True
    assert result['config'] == config
    
    # Check metrics calculated
    assert result['metrics']['edge_bps'] > 0
    assert result['metrics']['latency_ms'] > 0
    assert result['metrics']['risk'] > 0


def test_simulate_deterministic():
    """Test _simulate produces deterministic results."""
    from tools.tuning.apply_from_sweep import _simulate
    
    config = {'touch_dwell_ms': 25, 'risk_limit': 0.40}
    
    result1 = _simulate(config)
    result2 = _simulate(config)
    
    # Should be identical
    assert result1 == result2


# ======================================================================
# Test main() Function (CLI Logic with Mocking)
# ======================================================================

def test_main_success_with_top3(tmp_path, sweep_basic):
    """Test main() successfully processes sweep with top3."""
    # Setup
    sweep_file = tmp_path / "PARAM_SWEEP.json"
    sweep_file.write_text(json.dumps(sweep_basic))
    
    artifacts_dir = tmp_path / "artifacts"
    tools_dir = tmp_path / "tools" / "tuning"
    
    with patch('tools.tuning.apply_from_sweep.Path') as mock_path:
        # Mock Path lookups
        mock_artifacts_sweep = MagicMock()
        mock_artifacts_sweep.exists.return_value = False
        
        mock_direct_sweep = MagicMock()
        mock_direct_sweep.exists.return_value = True
        mock_direct_sweep.__str__ = lambda self: str(sweep_file)
        
        # Configure Path constructor
        def path_constructor(p):
            if str(p).endswith("PARAM_SWEEP.json"):
                if "artifacts" in str(p):
                    return mock_artifacts_sweep
                return mock_direct_sweep
            elif str(p) == "artifacts":
                mock_dir = MagicMock()
                mock_dir.mkdir = MagicMock()
                mock_dir.__truediv__ = lambda self, other: tmp_path / "artifacts" / other
                return mock_dir
            elif "tools" in str(p):
                mock_dir = MagicMock()
                mock_dir.mkdir = MagicMock()
                mock_dir.__truediv__ = lambda self, other: tmp_path / "tools" / "tuning" / other
                return mock_dir
            return MagicMock()
        
        mock_path.side_effect = path_constructor
        
        # Mock builtins.open for both read and write operations
        open_calls = {}
        
        def mock_open_handler(file, *args, **kwargs):
            file_str = str(file)
            if "PARAM_SWEEP.json" in file_str:
                return mock_open(read_data=json.dumps(sweep_basic))()
            else:
                # Track write operations
                mock_file = MagicMock()
                open_calls[file_str] = []
                
                def write_side_effect(data):
                    open_calls[file_str].append(data)
                
                def writelines_side_effect(lines):
                    open_calls[file_str].extend(lines)
                
                mock_file.write = write_side_effect
                mock_file.writelines = writelines_side_effect
                mock_file.__enter__ = lambda self: self
                mock_file.__exit__ = lambda self, *args: None
                return mock_file
        
        with patch('builtins.open', side_effect=mock_open_handler):
            with patch('builtins.print') as mock_print:
                result = main()
        
        assert result == 0
        assert mock_print.call_count >= 2  # At least 2 success messages


def test_main_file_not_found():
    """Test main() when PARAM_SWEEP.json doesn't exist."""
    with patch('tools.tuning.apply_from_sweep.Path') as mock_path:
        mock_sweep = MagicMock()
        mock_sweep.exists.return_value = False
        mock_path.return_value = mock_sweep
        
        with patch('builtins.print') as mock_print:
            result = main()
        
        assert result == 1
        # Verify error message printed
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("not found" in str(c).lower() for c in calls)


def test_main_empty_results(tmp_path, sweep_empty):
    """Test main() with empty sweep results."""
    sweep_file = tmp_path / "PARAM_SWEEP.json"
    sweep_file.write_text(json.dumps(sweep_empty))
    
    with patch('tools.tuning.apply_from_sweep.Path') as mock_path:
        mock_direct_sweep = MagicMock()
        mock_direct_sweep.exists.side_effect = [False, True]  # artifacts fails, direct succeeds
        mock_direct_sweep.__str__ = lambda self: str(sweep_file)
        
        mock_path.side_effect = lambda p: mock_direct_sweep
        
        with patch('builtins.open', mock_open(read_data=json.dumps(sweep_empty))):
            with patch('builtins.print') as mock_print:
                result = main()
        
        assert result == 1
        # Verify error message printed
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("no results" in str(c).lower() for c in calls)


def test_main_fallback_to_results(tmp_path, sweep_no_top3):
    """Test main() falls back to results[0] when no top3."""
    sweep_file = tmp_path / "PARAM_SWEEP.json"
    sweep_file.write_text(json.dumps(sweep_no_top3))
    
    artifacts_dir = tmp_path / "artifacts"
    tools_dir = tmp_path / "tools" / "tuning"
    
    with patch('tools.tuning.apply_from_sweep.Path') as mock_path:
        mock_direct_sweep = MagicMock()
        mock_direct_sweep.exists.side_effect = [False, True]
        mock_direct_sweep.__str__ = lambda self: str(sweep_file)
        
        def path_constructor(p):
            if "PARAM_SWEEP" in str(p):
                return mock_direct_sweep
            elif str(p) == "artifacts":
                mock_dir = MagicMock()
                mock_dir.mkdir = MagicMock()
                mock_dir.__truediv__ = lambda self, other: tmp_path / "artifacts" / other
                return mock_dir
            elif "tools" in str(p):
                mock_dir = MagicMock()
                mock_dir.mkdir = MagicMock()
                mock_dir.__truediv__ = lambda self, other: tmp_path / "tools" / "tuning" / other
                return mock_dir
            return MagicMock()
        
        mock_path.side_effect = path_constructor
        
        open_calls = {}
        
        def mock_open_handler(file, *args, **kwargs):
            if "PARAM_SWEEP" in str(file):
                return mock_open(read_data=json.dumps(sweep_no_top3))()
            else:
                mock_file = MagicMock()
                open_calls[str(file)] = []
                mock_file.write = lambda d: open_calls[str(file)].append(d)
                mock_file.writelines = lambda l: open_calls[str(file)].extend(l)
                mock_file.__enter__ = lambda self: self
                mock_file.__exit__ = lambda self, *args: None
                return mock_file
        
        with patch('builtins.open', side_effect=mock_open_handler):
            with patch('builtins.print'):
                result = main()
        
        assert result == 0


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

