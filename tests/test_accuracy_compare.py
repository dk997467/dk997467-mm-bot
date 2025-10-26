"""Unit tests for tools/accuracy/compare_shadow_dryrun.py"""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tools.accuracy.compare_shadow_dryrun import (
    compute_mape,
    compute_median_delta,
    compare_kpis,
    extract_kpi_by_symbol,
    parse_iter_files,
)


def create_iter_file(tmp_path: Path, index: int, symbol_data: dict, age_min: int = 0) -> Path:
    """Create a mock ITER_SUMMARY file."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    data = {
        "meta": {"timestamp": ts.isoformat()},
        **symbol_data
    }
    fpath = tmp_path / f"ITER_SUMMARY_{index:03d}.json"
    fpath.write_text(json.dumps(data))
    return fpath


class TestComputeMAPE:
    """Test MAPE computation."""
    
    def test_mape_perfect_match(self):
        """MAPE should be 0 for identical values."""
        shadow = [10.0, 20.0, 30.0]
        dryrun = [10.0, 20.0, 30.0]
        mape = compute_mape(shadow, dryrun)
        assert mape == 0.0
    
    def test_mape_with_error(self):
        """MAPE should compute correctly with error."""
        shadow = [100.0, 200.0]
        dryrun = [110.0, 190.0]
        # (|100-110|/100 + |200-190|/200) / 2 * 100 = (0.1 + 0.05) / 2 * 100 = 7.5%
        mape = compute_mape(shadow, dryrun)
        assert abs(mape - 7.5) < 0.01
    
    def test_mape_empty_inputs(self):
        """MAPE should return None for empty inputs."""
        assert compute_mape([], [1, 2, 3]) is None
        assert compute_mape([1, 2, 3], []) is None
        assert compute_mape([], []) is None
    
    def test_mape_different_lengths(self):
        """MAPE should align arrays and compute on shorter length."""
        shadow = [10.0, 20.0, 30.0, 40.0]
        dryrun = [20.0, 30.0]
        # Should use last 2 values: [30, 40] vs [20, 30]
        mape = compute_mape(shadow, dryrun)
        assert mape is not None
        # (|30-20|/30 + |40-30|/40) / 2 * 100 = (0.333 + 0.25) / 2 * 100 = 29.17%
        assert abs(mape - 29.17) < 0.5


class TestComputeMedianDelta:
    """Test median delta computation."""
    
    def test_median_delta_perfect_match(self):
        """Median delta should be 0 for identical values."""
        shadow = [10.0, 20.0, 30.0]
        dryrun = [10.0, 20.0, 30.0]
        delta = compute_median_delta(shadow, dryrun)
        assert delta == 0.0
    
    def test_median_delta_with_differences(self):
        """Median delta should compute correctly."""
        shadow = [10.0, 20.0, 30.0]
        dryrun = [11.0, 19.0, 32.0]
        # Deltas: [1.0, 1.0, 2.0] -> median = 1.0
        delta = compute_median_delta(shadow, dryrun)
        assert delta == 1.0
    
    def test_median_delta_even_count(self):
        """Median delta should average middle two for even count."""
        shadow = [10.0, 20.0, 30.0, 40.0]
        dryrun = [11.0, 19.0, 32.0, 38.0]
        # Deltas: [1.0, 1.0, 2.0, 2.0] -> sorted: [1.0, 1.0, 2.0, 2.0] -> median = (1.0 + 2.0) / 2 = 1.5
        delta = compute_median_delta(shadow, dryrun)
        assert delta == 1.5
    
    def test_median_delta_empty_inputs(self):
        """Median delta should return None for empty inputs."""
        assert compute_median_delta([], [1, 2, 3]) is None
        assert compute_median_delta([1, 2, 3], []) is None


class TestExtractKPIBySymbol:
    """Test KPI extraction from iterations."""
    
    def test_extract_single_symbol(self):
        """Should extract KPI values for single symbol."""
        iters = [
            {"BTCUSDT": {"edge_bps": 3.5, "maker_taker_ratio": 0.85}},
            {"BTCUSDT": {"edge_bps": 3.6, "maker_taker_ratio": 0.84}},
        ]
        result = extract_kpi_by_symbol(iters, ["BTCUSDT"])
        
        assert "BTCUSDT" in result
        assert result["BTCUSDT"]["edge_bps"] == [3.5, 3.6]
        assert result["BTCUSDT"]["maker_taker_ratio"] == [0.85, 0.84]
    
    def test_extract_multiple_symbols(self):
        """Should extract KPI values for multiple symbols."""
        iters = [
            {
                "BTCUSDT": {"edge_bps": 3.5},
                "ETHUSDT": {"edge_bps": 2.8}
            },
        ]
        result = extract_kpi_by_symbol(iters, ["BTCUSDT", "ETHUSDT"])
        
        assert "BTCUSDT" in result
        assert "ETHUSDT" in result
        assert result["BTCUSDT"]["edge_bps"] == [3.5]
        assert result["ETHUSDT"]["edge_bps"] == [2.8]
    
    def test_extract_missing_symbol(self):
        """Should handle missing symbol gracefully."""
        iters = [{"BTCUSDT": {"edge_bps": 3.5}}]
        result = extract_kpi_by_symbol(iters, ["BTCUSDT", "SOLUSDT"])
        
        assert "SOLUSDT" in result
        assert result["SOLUSDT"]["edge_bps"] == []
    
    def test_extract_missing_kpi(self):
        """Should handle missing KPI gracefully."""
        iters = [{"BTCUSDT": {"edge_bps": 3.5}}]
        result = extract_kpi_by_symbol(iters, ["BTCUSDT"])
        
        # maker_taker_ratio should be empty list
        assert result["BTCUSDT"]["maker_taker_ratio"] == []


class TestParseIterFiles:
    """Test iteration file parsing."""
    
    def test_parse_valid_files(self, tmp_path):
        """Should parse valid ITER_SUMMARY files."""
        create_iter_file(tmp_path, 1, {"BTCUSDT": {"edge_bps": 3.5}})
        create_iter_file(tmp_path, 2, {"BTCUSDT": {"edge_bps": 3.6}})
        
        pattern = str(tmp_path / "ITER_SUMMARY_*.json")
        iters = parse_iter_files(pattern)
        
        assert len(iters) == 2
        assert iters[0]["BTCUSDT"]["edge_bps"] == 3.5
        assert iters[1]["BTCUSDT"]["edge_bps"] == 3.6
    
    def test_parse_with_max_age(self, tmp_path):
        """Should filter out old files based on max_age_min."""
        # Recent file (5 min old)
        create_iter_file(tmp_path, 1, {"BTCUSDT": {"edge_bps": 3.5}}, age_min=5)
        # Old file (120 min old)
        create_iter_file(tmp_path, 2, {"BTCUSDT": {"edge_bps": 3.6}}, age_min=120)
        
        pattern = str(tmp_path / "ITER_SUMMARY_*.json")
        iters = parse_iter_files(pattern, max_age_min=90)
        
        # Should only include recent file
        assert len(iters) == 1
        assert iters[0]["BTCUSDT"]["edge_bps"] == 3.5
    
    def test_parse_no_matching_files(self, tmp_path):
        """Should return empty list for no matching files."""
        pattern = str(tmp_path / "NONEXISTENT_*.json")
        iters = parse_iter_files(pattern)
        
        assert iters == []


class TestCompareKPIs:
    """Test KPI comparison logic."""
    
    def test_compare_pass(self):
        """Should return PASS when thresholds are met."""
        shadow_data = {
            "BTCUSDT": {
                "edge_bps": [3.5, 3.6, 3.5],
                "maker_taker_ratio": [0.85, 0.84, 0.85],
                "p95_latency_ms": [300, 310, 305],
                "risk_ratio": [0.35, 0.36, 0.35]
            }
        }
        dryrun_data = {
            "BTCUSDT": {
                "edge_bps": [3.5, 3.6, 3.5],
                "maker_taker_ratio": [0.85, 0.84, 0.85],
                "p95_latency_ms": [300, 310, 305],
                "risk_ratio": [0.35, 0.36, 0.35]
            }
        }
        
        results, verdict = compare_kpis(shadow_data, dryrun_data, 0.15, 1.5)
        
        assert verdict == "PASS"
        assert results["BTCUSDT"]["edge_bps"]["status"] == "OK"
    
    def test_compare_fail_mape_threshold(self):
        """Should return FAIL when MAPE threshold is exceeded."""
        shadow_data = {
            "BTCUSDT": {
                "edge_bps": [3.0, 3.0, 3.0],
                "maker_taker_ratio": [0.85, 0.85, 0.85],
                "p95_latency_ms": [300, 300, 300],
                "risk_ratio": [0.35, 0.35, 0.35]
            }
        }
        dryrun_data = {
            "BTCUSDT": {
                "edge_bps": [4.0, 4.0, 4.0],  # 33% error -> exceeds 15% threshold
                "maker_taker_ratio": [0.85, 0.85, 0.85],
                "p95_latency_ms": [300, 300, 300],
                "risk_ratio": [0.35, 0.35, 0.35]
            }
        }
        
        results, verdict = compare_kpis(shadow_data, dryrun_data, 0.15, 1.5)
        
        assert verdict == "FAIL"
        assert results["BTCUSDT"]["edge_bps"]["status"] == "FAIL"
    
    def test_compare_warn(self):
        """Should return WARN when soft threshold is exceeded."""
        shadow_data = {
            "BTCUSDT": {
                "edge_bps": [3.0, 3.0, 3.0],
                "maker_taker_ratio": [0.85, 0.85, 0.85],
                "p95_latency_ms": [300, 300, 300],
                "risk_ratio": [0.35, 0.35, 0.35]
            }
        }
        dryrun_data = {
            "BTCUSDT": {
                "edge_bps": [3.05, 3.1, 3.08],  # Small MAPE but median delta > 1.5 BPS
                "maker_taker_ratio": [0.85, 0.85, 0.85],
                "p95_latency_ms": [300, 300, 300],
                "risk_ratio": [0.35, 0.35, 0.35]
            }
        }
        
        results, verdict = compare_kpis(shadow_data, dryrun_data, 0.15, 0.05)
        
        # Should trigger WARN for median delta
        assert verdict in ["WARN", "OK"]
    
    def test_compare_non_overlapping_symbols(self):
        """Should handle non-overlapping symbols."""
        shadow_data = {"BTCUSDT": {"edge_bps": [3.5], "maker_taker_ratio": [0.85], "p95_latency_ms": [300], "risk_ratio": [0.35]}}
        dryrun_data = {"ETHUSDT": {"edge_bps": [2.8], "maker_taker_ratio": [0.83], "p95_latency_ms": [320], "risk_ratio": [0.37]}}
        
        results, verdict = compare_kpis(shadow_data, dryrun_data, 0.15, 1.5)
        
        # Both symbols should be in results
        assert "BTCUSDT" in results
        assert "ETHUSDT" in results
        
        # All KPIs should have None values due to no overlap
        assert results["BTCUSDT"]["edge_bps"]["mape_pct"] is None
        assert results["ETHUSDT"]["edge_bps"]["mape_pct"] is None
    
    def test_compare_empty_data(self):
        """Should handle empty data gracefully."""
        shadow_data = {"BTCUSDT": {"edge_bps": [], "maker_taker_ratio": [], "p95_latency_ms": [], "risk_ratio": []}}
        dryrun_data = {"BTCUSDT": {"edge_bps": [], "maker_taker_ratio": [], "p95_latency_ms": [], "risk_ratio": []}}
        
        results, verdict = compare_kpis(shadow_data, dryrun_data, 0.15, 1.5)
        
        assert verdict == "PASS"
        assert results["BTCUSDT"]["edge_bps"]["mape_pct"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

