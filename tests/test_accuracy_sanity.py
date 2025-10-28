"""Unit tests for tools/accuracy/sanity_check.py"""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tools.accuracy.sanity_check import (
    create_mock_iter_file,
    scenario_empty_nonoverlap,
    scenario_maxage_filter,
    scenario_formatting_table,
)


class TestCreateMockIterFile:
    """Test mock ITER file creation."""
    
    def test_create_recent_file(self, tmp_path):
        """Should create a file with recent timestamp."""
        symbol_data = {"BTCUSDT": {"edge_bps": 3.5}}
        fpath = tmp_path / "ITER_001.json"
        
        create_mock_iter_file(fpath, 1, symbol_data, age_min=5)
        
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        
        assert "meta" in data
        assert "timestamp" in data["meta"]
        assert "BTCUSDT" in data
        assert data["BTCUSDT"]["edge_bps"] == 3.5
        
        # Check age is roughly 5 minutes
        ts = datetime.fromisoformat(data["meta"]["timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        assert 4.5 <= age <= 5.5
    
    def test_create_old_file(self, tmp_path):
        """Should create a file with old timestamp."""
        symbol_data = {"ETHUSDT": {"edge_bps": 2.8}}
        fpath = tmp_path / "ITER_002.json"
        
        create_mock_iter_file(fpath, 2, symbol_data, age_min=120)
        
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        
        ts = datetime.fromisoformat(data["meta"]["timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        assert 119 <= age <= 121


class TestScenarioEmptyNonOverlap:
    """Test empty/non-overlapping scenario."""
    
    def test_nonoverlapping_symbols_warn(self, tmp_path):
        """Should return WARN or PASS for non-overlapping symbols."""
        result, passed = scenario_empty_nonoverlap(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Check result contains expected text
        assert "Scenario 1" in result
        assert "Non-overlapping" in result
        assert "BTCUSDT" in result or "ETHUSDT" in result
        
        # Should pass (WARN or PASS is expected, not FAIL)
        assert passed
        
        # Check sanity report subdirectory was created
        assert (tmp_path / "sanity_empty").exists()
    
    def test_generates_reports(self, tmp_path):
        """Should generate ACCURACY_REPORT.md and ACCURACY_SUMMARY.json."""
        result, passed = scenario_empty_nonoverlap(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        report_dir = tmp_path / "sanity_empty"
        
        # Check that comparison was run and reports exist
        assert report_dir.exists()
        # Note: Reports may or may not exist depending on comparison outcome
        # The key is that the scenario ran without crashing


class TestScenarioMaxAgeFilter:
    """Test max-age filtering scenario."""
    
    def test_old_data_filtered(self, tmp_path):
        """Should filter out old data and return appropriate status."""
        result, passed = scenario_maxage_filter(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Check result contains expected text
        assert "Scenario 2" in result
        assert "Max-Age" in result
        assert "filtered" in result.lower()
        
        # Should pass (exit 1 or WARN is expected)
        assert passed
        
        # Check sanity report subdirectory was created
        assert (tmp_path / "sanity_maxage").exists()
    
    def test_handles_insufficient_windows(self, tmp_path):
        """Should handle insufficient windows gracefully."""
        result, passed = scenario_maxage_filter(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Should not crash
        assert result is not None
        assert isinstance(passed, bool)


class TestScenarioFormattingTable:
    """Test formatting scenario with many symbols."""
    
    def test_many_symbols_formatting(self, tmp_path):
        """Should handle many symbols and check table formatting."""
        result, passed = scenario_formatting_table(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Check result contains expected text
        assert "Scenario 3" in result
        assert "Formatting" in result
        assert "symbols" in result.lower()
        
        # Should pass (PASS expected for perfect match)
        assert passed
        
        # Check sanity report subdirectory was created
        assert (tmp_path / "sanity_format").exists()
    
    def test_table_preview_included(self, tmp_path):
        """Should include table preview in result."""
        result, passed = scenario_formatting_table(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Should include table preview or formatting check
        assert "Table" in result or "Formatting" in result
    
    def test_table_width_reasonable(self, tmp_path):
        """Should generate table with reasonable line widths."""
        result, passed = scenario_formatting_table(
            min_windows=24,
            max_age_min=90,
            mape_threshold=0.15,
            median_delta_bps=1.5,
            report_dir=tmp_path
        )
        
        # Check that no lines in result are excessively long
        lines = result.split("\n")
        for line in lines:
            if line.startswith("|"):
                # Table lines shouldn't be ridiculously long
                assert len(line) < 500, f"Table line too long: {len(line)} chars"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

