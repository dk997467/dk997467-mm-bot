#!/usr/bin/env python3
"""
Unit tests for Post-Soak Analyzer V2
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from tools.soak.analyze_post_soak import (
    load_windows,
    generate_sparkline,
    calculate_trend,
    detect_violations,
    generate_recommendations,
    generate_analysis_report,
    generate_recommendations_report,
    generate_violations_json,
)


@pytest.fixture
def temp_iter_files(tmp_path):
    """Create temporary ITER_SUMMARY files for testing."""
    # Create 8 windows with normal metrics
    for i in range(8):
        data = {
            "symbol": "BTCUSDT",
            "net_bps": 3.5 - (i * 0.05),  # Slight downward trend
            "maker_taker_ratio": 0.85 + (i * 0.01),  # Slight upward trend
            "p95_latency_ms": 280 + (i * 5),  # Upward trend
            "risk_ratio": 0.30 + (i * 0.01),  # Upward trend
            "commit": f"abc123{i}",
            "profile": "S1"
        }
        
        file_path = tmp_path / f"ITER_SUMMARY_{i+1:03d}.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
    
    return tmp_path


@pytest.fixture
def temp_iter_files_crit(tmp_path):
    """Create temporary ITER_SUMMARY files with CRIT violations."""
    for i in range(8):
        data = {
            "symbol": "BTCUSDT",
            "net_bps": 2.8 - (i * 0.1),  # Drops below crit threshold (2.5)
            "maker_taker_ratio": 0.72 - (i * 0.005),  # Drops below crit (0.70)
            "p95_latency_ms": 320 + (i * 10),  # Rises above crit (350)
            "risk_ratio": 0.38 + (i * 0.01),  # Rises to crit (0.40)
            "commit": "def456",
            "profile": "S1"
        }
        
        file_path = tmp_path / f"ITER_SUMMARY_{i+1:03d}.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
    
    return tmp_path


@pytest.fixture
def temp_iter_files_warn(tmp_path):
    """Create temporary ITER_SUMMARY files with WARN violations."""
    for i in range(8):
        data = {
            "symbol": "BTCUSDT",
            "net_bps": 2.9,  # Between warn (3.0) and crit (2.5)
            "maker_taker_ratio": 0.73,  # Between warn (0.75) and crit (0.70)
            "p95_latency_ms": 335,  # Between warn (330) and crit (350)
            "risk_ratio": 0.36,  # Below thresholds
            "commit": "ghi789",
            "profile": "S1"
        }
        
        file_path = tmp_path / f"ITER_SUMMARY_{i+1:03d}.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
    
    return tmp_path


@pytest.fixture
def temp_iter_files_multi_symbol(tmp_path):
    """Create temporary ITER_SUMMARY files with multiple symbols."""
    symbols = ["BTCUSDT", "ETHUSDT"]
    
    for symbol_idx, symbol in enumerate(symbols):
        for i in range(4):
            data = {
                "symbol": symbol,
                "net_bps": 3.2 + symbol_idx,
                "maker_taker_ratio": 0.82 + symbol_idx * 0.02,
                "p95_latency_ms": 290 + symbol_idx * 10,
                "risk_ratio": 0.32 + symbol_idx * 0.02,
                "commit": "jkl012",
                "profile": "S1"
            }
            
            file_path = tmp_path / f"ITER_SUMMARY_{symbol}_{i+1:03d}.json"
            file_path.write_text(json.dumps(data), encoding="utf-8")
    
    return tmp_path


def test_load_windows_ok(temp_iter_files):
    """Test loading windows from files - OK case."""
    pattern = str(temp_iter_files / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern)
    
    assert "BTCUSDT" in windows
    assert len(windows["BTCUSDT"]) == 8
    
    # Check first window
    first_window = windows["BTCUSDT"][0]
    assert "metrics" in first_window
    assert first_window["metrics"]["edge_bps"] == 3.5
    assert first_window["metrics"]["maker_taker_ratio"] == 0.85


def test_load_windows_with_filter(temp_iter_files_multi_symbol):
    """Test loading windows with symbol filter."""
    pattern = str(temp_iter_files_multi_symbol / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern, symbols_filter=["BTCUSDT"])
    
    assert "BTCUSDT" in windows
    assert "ETHUSDT" not in windows
    assert len(windows["BTCUSDT"]) == 4


def test_generate_sparkline():
    """Test sparkline generation."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    sparkline = generate_sparkline(values, width=5)
    
    assert len(sparkline) == 5
    assert sparkline[0] < sparkline[-1]  # Ascending
    
    # Test empty values
    empty_sparkline = generate_sparkline([], width=5)
    assert "─" in empty_sparkline


def test_calculate_trend():
    """Test trend calculation."""
    # Upward trend
    up_values = [1.0, 2.0, 3.0, 4.0, 5.0]
    trend_up, slope_up = calculate_trend(up_values)
    assert trend_up == "↑"
    assert slope_up > 0
    
    # Downward trend
    down_values = [5.0, 4.0, 3.0, 2.0, 1.0]
    trend_down, slope_down = calculate_trend(down_values)
    assert trend_down == "↓"
    assert slope_down < 0
    
    # Stable trend
    stable_values = [3.0, 3.01, 2.99, 3.0, 3.02]
    trend_stable, slope_stable = calculate_trend(stable_values)
    assert trend_stable == "≈"


def test_detect_violations_ok():
    """Test violation detection - OK case."""
    metrics_series = {
        "edge_bps": [3.5, 3.6, 3.4, 3.5],
        "maker_taker_ratio": [0.85, 0.86, 0.84, 0.85],
        "p95_latency_ms": [280, 285, 290, 280],
        "risk_ratio": [0.30, 0.31, 0.29, 0.30]
    }
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    violations = detect_violations("BTCUSDT", metrics_series, thresholds)
    
    # Should have no violations
    critical_violations = [v for v in violations if v["level"] == "CRIT"]
    assert len(critical_violations) == 0


def test_detect_violations_crit():
    """Test violation detection - CRIT case."""
    metrics_series = {
        "edge_bps": [2.3, 2.2, 2.1, 2.0],  # Below crit (2.5)
        "maker_taker_ratio": [0.68, 0.67, 0.66, 0.65],  # Below crit (0.70)
        "p95_latency_ms": [360, 365, 370, 375],  # Above crit (350)
        "risk_ratio": [0.42, 0.43, 0.44, 0.45]  # Above crit (0.40)
    }
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    violations = detect_violations("BTCUSDT", metrics_series, thresholds)
    
    # Should have CRIT violations for all metrics
    critical_violations = [v for v in violations if v["level"] == "CRIT"]
    assert len(critical_violations) > 0
    
    # Check edge violation
    edge_crit = [v for v in violations if v["metric"] == "edge_bps" and v["level"] == "CRIT"]
    assert len(edge_crit) > 0


def test_detect_violations_warn():
    """Test violation detection - WARN case."""
    metrics_series = {
        "edge_bps": [2.9, 2.85, 2.8, 2.75],  # Between warn (3.0) and crit (2.5)
        "maker_taker_ratio": [0.73, 0.72, 0.74, 0.73],  # Between warn (0.75) and crit (0.70)
        "p95_latency_ms": [335, 340, 338, 342],  # Between warn (330) and crit (350)
        "risk_ratio": [0.30, 0.31, 0.30, 0.32]  # OK
    }
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    violations = detect_violations("BTCUSDT", metrics_series, thresholds)
    
    # Should have WARN violations (but no CRIT)
    warning_violations = [v for v in violations if v["level"] == "WARN"]
    critical_violations = [v for v in violations if v["level"] == "CRIT"]
    
    assert len(warning_violations) > 0
    assert len(critical_violations) == 0


def test_generate_recommendations():
    """Test recommendation generation."""
    metrics_series = {
        "edge_bps": [2.3, 2.2, 2.1, 2.0],  # Low edge
        "maker_taker_ratio": [0.85, 0.86, 0.84, 0.85],  # Good maker
        "p95_latency_ms": [280, 285, 290, 280],
        "risk_ratio": [0.30, 0.31, 0.29, 0.30]
    }
    
    violations = [
        {
            "symbol": "BTCUSDT",
            "metric": "edge_bps",
            "level": "CRIT",
            "window_index": 0,
            "value": 2.3,
            "threshold": 2.5,
            "note": "Edge below critical threshold"
        }
    ]
    
    recommendations = generate_recommendations("BTCUSDT", metrics_series, violations)
    
    assert len(recommendations) > 0
    # Should recommend tightening spread since maker is good but edge is low
    assert any("ужать spread" in rec.lower() for rec in recommendations)


def test_generate_analysis_report(temp_iter_files, tmp_path):
    """Test analysis report generation."""
    pattern = str(temp_iter_files / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern)
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    out_dir = tmp_path / "reports"
    crit_count, violations = generate_analysis_report(windows, thresholds, 48, out_dir)
    
    # Check report file exists
    report_path = out_dir / "POST_SOAK_ANALYSIS.md"
    assert report_path.exists()
    
    # Check content
    content = report_path.read_text(encoding="utf-8")
    assert "Post-Soak Analysis Report V2" in content
    assert "BTCUSDT" in content
    assert "Sparkline" in content or "▁" in content or "█" in content  # Check for sparklines


def test_generate_analysis_report_min_windows_warn(temp_iter_files, tmp_path):
    """Test analysis report with min_windows warning."""
    pattern = str(temp_iter_files / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern)
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    out_dir = tmp_path / "reports"
    # Require 24 windows but only have 8
    crit_count, violations = generate_analysis_report(windows, thresholds, 24, out_dir)
    
    report_path = out_dir / "POST_SOAK_ANALYSIS.md"
    content = report_path.read_text(encoding="utf-8")
    
    # Should have warning about min windows
    assert "Windows < min_windows" in content or "actual=8" in content


def test_generate_recommendations_report(temp_iter_files_crit, tmp_path):
    """Test recommendations report generation."""
    pattern = str(temp_iter_files_crit / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern)
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    # Generate violations
    all_violations = []
    for symbol, symbol_windows in windows.items():
        metrics_series = {
            "edge_bps": [],
            "maker_taker_ratio": [],
            "p95_latency_ms": [],
            "risk_ratio": []
        }
        
        for window in symbol_windows:
            for metric_name in metrics_series.keys():
                value = window["metrics"].get(metric_name)
                metrics_series[metric_name].append(value)
        
        violations = detect_violations(symbol, metrics_series, thresholds)
        all_violations.extend(violations)
    
    out_dir = tmp_path / "reports"
    generate_recommendations_report(windows, all_violations, thresholds, out_dir)
    
    rec_path = out_dir / "RECOMMENDATIONS.md"
    assert rec_path.exists()
    
    content = rec_path.read_text(encoding="utf-8")
    assert "Recommendations" in content or "рекомендации" in content.lower()
    # Should have Russian recommendations
    assert any(word in content for word in ["Увеличить", "Уменьшить", "Повысить", "Снизить"])


def test_generate_violations_json(temp_iter_files_crit, tmp_path):
    """Test violations JSON generation."""
    pattern = str(temp_iter_files_crit / "ITER_SUMMARY_*.json")
    windows = load_windows(pattern)
    
    thresholds = {
        "warn_edge": 3.0,
        "crit_edge": 2.5,
        "warn_maker": 0.75,
        "crit_maker": 0.70,
        "warn_lat": 330,
        "crit_lat": 350,
        "warn_risk": 0.40,
        "crit_risk": 0.40
    }
    
    # Generate violations
    all_violations = []
    for symbol, symbol_windows in windows.items():
        metrics_series = {
            "edge_bps": [],
            "maker_taker_ratio": [],
            "p95_latency_ms": [],
            "risk_ratio": []
        }
        
        for window in symbol_windows:
            for metric_name in metrics_series.keys():
                value = window["metrics"].get(metric_name)
                metrics_series[metric_name].append(value)
        
        violations = detect_violations(symbol, metrics_series, thresholds)
        all_violations.extend(violations)
    
    out_dir = tmp_path / "reports"
    generate_violations_json(all_violations, out_dir)
    
    json_path = out_dir / "VIOLATIONS.json"
    assert json_path.exists()
    
    # Load and check structure
    with open(json_path, 'r', encoding='utf-8') as f:
        violations_data = json.load(f)
    
    assert isinstance(violations_data, list)
    if violations_data:
        assert "symbol" in violations_data[0]
        assert "metric" in violations_data[0]
        assert "level" in violations_data[0]


def test_main_exit_on_crit(temp_iter_files_crit, tmp_path, monkeypatch):
    """Test main() with --exit-on-crit flag."""
    from tools.soak.analyze_post_soak import main
    
    pattern = str(temp_iter_files_crit / "ITER_SUMMARY_*.json")
    out_dir = tmp_path / "reports"
    
    # Mock sys.argv
    test_args = [
        "analyze_post_soak.py",
        "--iter-glob", pattern,
        "--out-dir", str(out_dir),
        "--exit-on-crit"
    ]
    
    monkeypatch.setattr(sys, "argv", test_args)
    
    # Should exit with 1 due to CRIT violations
    exit_code = main()
    assert exit_code == 1


def test_main_no_exit_on_crit(temp_iter_files_crit, tmp_path, monkeypatch):
    """Test main() without --exit-on-crit flag."""
    from tools.soak.analyze_post_soak import main
    
    pattern = str(temp_iter_files_crit / "ITER_SUMMARY_*.json")
    out_dir = tmp_path / "reports"
    
    # Mock sys.argv (no --exit-on-crit)
    test_args = [
        "analyze_post_soak.py",
        "--iter-glob", pattern,
        "--out-dir", str(out_dir)
    ]
    
    monkeypatch.setattr(sys, "argv", test_args)
    
    # Should exit with 0 even with CRIT violations
    exit_code = main()
    assert exit_code == 0

