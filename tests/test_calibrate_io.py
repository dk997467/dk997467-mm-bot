"""
Tests for E2 Part 1 calibration I/O and determinism.
"""

import pytest
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from src.research.calibrate import (
    load_live_summaries, build_live_distributions, write_json_sorted,
    round_floats
)


class TestCalibrateIO:
    """Test calibration I/O functions and determinism."""

    def create_mock_summary(self, symbol: str, hour_utc: datetime, 
                          orders: int = 10, quotes: int = 20, fills: int = 5) -> dict:
        """Create a mock summary for testing."""
        return {
            "schema_version": "e1.1",
            "symbol": symbol,
            "hour_utc": hour_utc.isoformat() + "Z",
            "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
            "window_utc": {
                "hour_start": hour_utc.isoformat() + "Z",
                "hour_end": (hour_utc + timedelta(hours=1)).isoformat() + "Z"
            },
            "bins_max_bps": 50,
            "percentiles_used": [0.25, 0.5, 0.75, 0.9],
            "counts": {
                "orders": orders,
                "quotes": quotes,
                "fills": fills
            },
            "hit_rate_by_bin": {
                "0": {"count": quotes // 3, "fills": fills // 3},
                "5": {"count": quotes // 3, "fills": fills // 3},
                "10": {"count": quotes - 2 * (quotes // 3), "fills": fills - 2 * (fills // 3)}
            },
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 100.0},
                {"p": 0.5, "v": 150.0},
                {"p": 0.75, "v": 200.0},
                {"p": 0.9, "v": 250.0}
            ],
            "metadata": {
                "git_sha": "test_sha_123",
                "cfg_hash": "test_cfg_456"
            }
        }

    def test_load_live_summaries_basic(self, tmp_path):
        """Test loading basic LIVE summaries."""
        symbol = "TESTLOAD"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        # Create test summaries
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        summaries_created = []
        for i in range(3):
            hour = base_time + timedelta(hours=i)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = self.create_mock_summary(symbol, hour, orders=10+i, quotes=20+i, fills=5+i)
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
            
            summaries_created.append(summary_data)
        
        # Load summaries
        from_utc = base_time
        to_utc = base_time + timedelta(hours=3)
        
        with patch('src.research.calibrate.load_hourly_summary') as mock_load:
            mock_load.side_effect = summaries_created
            
            loaded = load_live_summaries(summaries_dir, symbol, from_utc, to_utc)
        
        assert len(loaded) == 3
        for i, summary in enumerate(loaded):
            assert summary["counts"]["orders"] == 10 + i
            assert summary["counts"]["quotes"] == 20 + i
            assert summary["counts"]["fills"] == 5 + i

    def test_load_live_summaries_empty_directory(self, tmp_path):
        """Test loading summaries from empty directory."""
        symbol = "EMPTY"
        from_utc = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        to_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        loaded = load_live_summaries(tmp_path, symbol, from_utc, to_utc)
        assert len(loaded) == 0

    def test_load_live_summaries_with_invalid_files(self, tmp_path):
        """Test loading summaries with some invalid files."""
        symbol = "INVALID"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        # Create one valid file
        valid_hour = base_time
        valid_filename = f"{symbol}_{valid_hour.strftime('%Y-%m-%d_%H')}.json"
        valid_path = symbol_dir / valid_filename
        valid_data = self.create_mock_summary(symbol, valid_hour)
        with open(valid_path, 'w') as f:
            json.dump(valid_data, f)
        
        # Create one invalid file  
        invalid_hour = base_time + timedelta(hours=1)
        invalid_filename = f"{symbol}_{invalid_hour.strftime('%Y-%m-%d_%H')}.json"
        invalid_path = symbol_dir / invalid_filename
        with open(invalid_path, 'w') as f:
            f.write("invalid json content")
        
        from_utc = base_time
        to_utc = base_time + timedelta(hours=2)
        
        # Mock to make load_hourly_summary raise exception for invalid file
        def mock_load_side_effect(path):
            if "invalid" in path.name:
                raise ValueError("Invalid file")
            return valid_data
        
        with patch('src.research.calibrate.load_hourly_summary', side_effect=mock_load_side_effect):
            loaded = load_live_summaries(summaries_dir, symbol, from_utc, to_utc)
        
        # Should only load the valid file
        assert len(loaded) == 1
        assert loaded[0] == valid_data

    def test_build_live_distributions_basic(self):
        """Test building LIVE distributions from summaries."""
        # Create mock summaries
        summaries = [
            {
                "counts": {"orders": 10, "quotes": 20, "fills": 5},
                "hit_rate_by_bin": {
                    "0": {"count": 8, "fills": 2},
                    "5": {"count": 7, "fills": 2},
                    "10": {"count": 5, "fills": 1}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.5, "v": 100.0},
                    {"p": 0.9, "v": 200.0}
                ]
            },
            {
                "counts": {"orders": 15, "quotes": 30, "fills": 8},
                "hit_rate_by_bin": {
                    "0": {"count": 12, "fills": 3},
                    "5": {"count": 10, "fills": 3},
                    "10": {"count": 8, "fills": 2}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.5, "v": 120.0},
                    {"p": 0.9, "v": 220.0}
                ]
            }
        ]
        
        distributions = build_live_distributions(summaries, bins_max_bps=15, percentiles=[0.5, 0.9])
        
        # Check aggregated data
        assert distributions["live_hit"] == (5 + 8) / (20 + 30)  # 13/50 = 0.26
        assert distributions["live_maker"] == distributions["live_hit"]  # Simplified
        
        # Check bins are aggregated
        assert "0" in distributions["hit_rate_by_bin"]
        assert "5" in distributions["hit_rate_by_bin"]
        assert "10" in distributions["hit_rate_by_bin"]
        
        bin_0 = distributions["hit_rate_by_bin"]["0"]
        assert bin_0["count"] == 8 + 12  # 20
        assert bin_0["fills"] == 2 + 3   # 5
        
        # Check all bins 0-15 are present
        for i in range(16):
            assert str(i) in distributions["hit_rate_by_bin"]
        
        # Check CDF is built
        assert len(distributions["queue_wait_cdf_ms"]) == 2
        cdf = distributions["queue_wait_cdf_ms"]
        assert all(entry["p"] in [0.5, 0.9] for entry in cdf)

    def test_build_live_distributions_empty_input(self):
        """Test building distributions from empty input."""
        distributions = build_live_distributions([], bins_max_bps=10, percentiles=[0.5])
        
        assert distributions["live_hit"] == 0.0
        assert distributions["live_maker"] is None
        assert distributions["hit_rate_by_bin"] == {}
        assert distributions["queue_wait_cdf_ms"] == []

    def test_build_live_distributions_no_queue_data(self):
        """Test building distributions without queue wait data."""
        summaries = [
            {
                "counts": {"orders": 10, "quotes": 20, "fills": 5},
                "hit_rate_by_bin": {
                    "0": {"count": 10, "fills": 2},
                    "5": {"count": 10, "fills": 3}
                },
                "queue_wait_cdf_ms": []  # Empty CDF
            }
        ]
        
        distributions = build_live_distributions(summaries, bins_max_bps=10, percentiles=[0.5, 0.9])
        
        assert distributions["live_hit"] == 5 / 20  # 0.25
        assert len(distributions["queue_wait_cdf_ms"]) == 0  # No CDF data

    def test_build_live_distributions_bins_filtering(self):
        """Test that bins outside max_bps are filtered."""
        summaries = [
            {
                "counts": {"orders": 10, "quotes": 20, "fills": 5},
                "hit_rate_by_bin": {
                    "0": {"count": 5, "fills": 1},
                    "5": {"count": 5, "fills": 2},
                    "15": {"count": 5, "fills": 1},  # Within max
                    "25": {"count": 5, "fills": 1}   # Above max (should be filtered)
                },
                "queue_wait_cdf_ms": []
            }
        ]
        
        distributions = build_live_distributions(summaries, bins_max_bps=20, percentiles=[])
        
        # Should have bins 0-20, including 15 but not 25
        bins = distributions["hit_rate_by_bin"]
        assert "0" in bins and bins["0"]["count"] == 5
        assert "5" in bins and bins["5"]["count"] == 5  
        assert "15" in bins and bins["15"]["count"] == 5
        assert "25" not in bins  # Filtered out
        
        # All bins 0-20 should be present
        for i in range(21):
            assert str(i) in bins

    def test_write_json_sorted_deterministic(self, tmp_path):
        """Test that JSON writing is deterministic."""
        data = {
            "zebra": 1,
            "alpha": 2,
            "beta": {"charlie": 3, "alice": 4},
            "numbers": [3, 1, 2]
        }
        
        file_path = tmp_path / "test.json"
        
        # Write the same data twice
        write_json_sorted(file_path, data)
        with open(file_path, 'r') as f:
            content1 = f.read()
        
        write_json_sorted(file_path, data)
        with open(file_path, 'r') as f:
            content2 = f.read()
        
        # Should be identical
        assert content1 == content2
        
        # Should be sorted
        lines = content1.split('\n')
        # First key should be "alpha" (sorted)
        assert '"alpha"' in lines[1]
        # Nested object should also be sorted
        assert content1.find('"alice"') < content1.find('"charlie"')

    def test_write_json_sorted_creates_directory(self, tmp_path):
        """Test that write_json_sorted creates parent directories."""
        nested_path = tmp_path / "deep" / "nested" / "path" / "test.json"
        
        data = {"test": "value"}
        write_json_sorted(nested_path, data)
        
        assert nested_path.exists()
        assert nested_path.parent.exists()
        
        with open(nested_path, 'r') as f:
            loaded = json.load(f)
        
        assert loaded == data

    def test_deterministic_distributions_same_seed(self, tmp_path):
        """Test that same seed produces identical distributions."""
        import random
        import numpy as np
        
        # Create test summaries with some randomness
        summaries = [
            {
                "counts": {"orders": 100, "quotes": 200, "fills": 50},
                "hit_rate_by_bin": {
                    "0": {"count": 60, "fills": 15},
                    "5": {"count": 80, "fills": 20},
                    "10": {"count": 60, "fills": 15}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 90.0},
                    {"p": 0.5, "v": 150.0},
                    {"p": 0.75, "v": 210.0},
                    {"p": 0.9, "v": 270.0}
                ]
            }
        ]
        
        # First run with seed 42
        random.seed(42)
        np.random.seed(42)
        dist1 = build_live_distributions(summaries, bins_max_bps=20, percentiles=[0.25, 0.5, 0.75, 0.9])
        rounded1 = round_floats(dist1, dp=6)
        
        # Write to file
        path1 = tmp_path / "dist1.json"
        write_json_sorted(path1, rounded1)
        
        # Second run with same seed
        random.seed(42)
        np.random.seed(42)
        dist2 = build_live_distributions(summaries, bins_max_bps=20, percentiles=[0.25, 0.5, 0.75, 0.9])
        rounded2 = round_floats(dist2, dp=6)
        
        # Write to file
        path2 = tmp_path / "dist2.json"
        write_json_sorted(path2, rounded2)
        
        # Files should be identical
        with open(path1, 'r') as f:
            content1 = f.read()
        with open(path2, 'r') as f:
            content2 = f.read()
        
        assert content1 == content2, "Same seed should produce identical output"

    def test_deterministic_distributions_different_seed(self, tmp_path):
        """Test that different seeds can produce different results (when applicable)."""
        import random
        import numpy as np
        
        summaries = [
            {
                "counts": {"orders": 100, "quotes": 200, "fills": 50},
                "hit_rate_by_bin": {
                    "0": {"count": 60, "fills": 15},
                    "5": {"count": 80, "fills": 20}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.5, "v": 150.0}
                ]
            }
        ]
        
        # Run with different seeds
        random.seed(42)
        np.random.seed(42)
        dist1 = build_live_distributions(summaries, bins_max_bps=10, percentiles=[0.5])
        
        random.seed(123)
        np.random.seed(123)
        dist2 = build_live_distributions(summaries, bins_max_bps=10, percentiles=[0.5])
        
        # Basic structure should be the same (deterministic parts)
        assert dist1["live_hit"] == dist2["live_hit"]
        assert len(dist1["hit_rate_by_bin"]) == len(dist2["hit_rate_by_bin"])
        
        # Note: Current implementation is deterministic regardless of seed,
        # but this test ensures the seed setting doesn't break anything

    def test_live_distributions_contains_config(self):
        """Test that live_distributions.json contains bins_max_bps and percentiles_used."""
        summaries = [
            {
                "counts": {"orders": 50, "quotes": 100, "fills": 25},
                "hit_rate_by_bin": {
                    "0": {"count": 30, "fills": 8},
                    "5": {"count": 35, "fills": 9},
                    "10": {"count": 35, "fills": 8}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 120.0},
                    {"p": 0.5, "v": 180.0},
                    {"p": 0.75, "v": 240.0}
                ]
            }
        ]
        
        bins_max_bps = 15
        percentiles = [0.25, 0.5, 0.75]
        
        distributions = build_live_distributions(summaries, bins_max_bps, percentiles)
        
        # E2 Part 1 Polish: Should always contain config fields
        assert "bins_max_bps" in distributions
        assert "percentiles_used" in distributions
        
        assert distributions["bins_max_bps"] == bins_max_bps
        assert distributions["percentiles_used"] == percentiles
        
        # Should work even with empty input
        empty_distributions = build_live_distributions([], bins_max_bps, percentiles)
        assert empty_distributions["bins_max_bps"] == bins_max_bps
        assert empty_distributions["percentiles_used"] == percentiles

    def test_round_floats_preserves_structure(self):
        """Test that round_floats preserves data structure."""
        original = {
            "live_hit": 0.123456789,
            "live_maker": 0.987654321,
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 123.456789},
                {"p": 0.75, "v": 987.654321}
            ],
            "hit_rate_by_bin": {
                "0": {"count": 100, "fills": 25},
                "5": {"count": 80, "fills": 16}
            },
            "metadata": {
                "symbol": "TEST",
                "precision": 3.14159
            }
        }
        
        rounded = round_floats(original, dp=3)
        
        assert rounded["live_hit"] == 0.123
        assert rounded["live_maker"] == 0.988
        assert rounded["queue_wait_cdf_ms"][0]["v"] == 123.457
        assert rounded["queue_wait_cdf_ms"][1]["v"] == 987.654
        assert rounded["metadata"]["precision"] == 3.142
        
        # Non-float values should be unchanged
        assert rounded["hit_rate_by_bin"]["0"]["count"] == 100
        assert rounded["metadata"]["symbol"] == "TEST"
