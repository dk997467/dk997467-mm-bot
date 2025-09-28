"""
Tests for E1+ calibration preflight functionality.
"""

import pytest
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from src.research.calibrate import (
    load_hourly_summary, parse_hour_from_filename, scan_summary_files,
    preflight_summaries, print_preflight_report
)


class TestCalibratePreflight:
    """Test calibration preflight functionality."""

    def create_mock_summary(self, symbol: str, hour_utc: datetime, 
                          orders: int = 5, quotes: int = 10, fills: int = 3) -> dict:
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
            "percentiles_used": [0.5, 0.9, 0.95],
            "counts": {
                "orders": orders,
                "quotes": quotes,
                "fills": fills
            },
            "hit_rate_by_bin": {
                "5": {"count": quotes // 2, "fills": fills // 2},
                "10": {"count": quotes - quotes // 2, "fills": fills - fills // 2}
            },
            "queue_wait_cdf_ms": [
                {"p": 0.5, "v": 100.0},
                {"p": 0.9, "v": 200.0}
            ],
            "metadata": {
                "git_sha": "test_sha_123",
                "cfg_hash": "test_cfg_456"
            }
        }

    def test_parse_hour_from_filename(self):
        """Test parsing hour from various filename formats."""
        test_cases = [
            ("BTCUSDT_2025-01-15_14.json", datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)),
            ("TEST_2025-12-31_23.json", datetime(2025, 12, 31, 23, 0, 0, tzinfo=timezone.utc)),
            ("BTC_USDT_PERP_2025-01-01_00.json", datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
            ("SYMBOL_2025-06-15_12.json", datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)),
        ]
        
        for filename, expected in test_cases:
            result = parse_hour_from_filename(filename)
            assert result == expected, f"Failed for {filename}"

    def test_parse_hour_from_invalid_filenames(self):
        """Test parsing invalid filenames returns None."""
        invalid_filenames = [
            "invalid.json",
            "SYMBOL_invalid_time.json",
            "not_json.txt",
            "SYMBOL_2025-01-01.json",  # Missing hour
            "SYMBOL_2025-13-01_12.json",  # Invalid month
            "SYMBOL_2025-01-32_12.json",  # Invalid day
            "SYMBOL_2025-01-01_25.json",  # Invalid hour
        ]
        
        for filename in invalid_filenames:
            result = parse_hour_from_filename(filename)
            assert result is None, f"Should return None for {filename}"

    def test_load_hourly_summary_valid_file(self, tmp_path):
        """Test loading a valid summary file."""
        symbol = "LOAD"
        hour = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        # Create valid summary file
        summary_data = self.create_mock_summary(symbol, hour)
        summary_file = tmp_path / f"{symbol}_2025-01-15_10.json"
        
        with open(summary_file, 'w') as f:
            json.dump(summary_data, f, indent=2)
        
        # Load and verify
        loaded = load_hourly_summary(summary_file)
        assert loaded["symbol"] == symbol
        assert loaded["schema_version"] == "e1.1"
        assert "window_utc" in loaded

    def test_load_hourly_summary_invalid_file(self, tmp_path):
        """Test loading invalid files raises appropriate errors."""
        # Non-existent file
        with pytest.raises(ValueError, match="not found"):
            load_hourly_summary(tmp_path / "nonexistent.json")
        
        # Invalid JSON
        invalid_json_file = tmp_path / "invalid.json"
        with open(invalid_json_file, 'w') as f:
            f.write("invalid json content {")
        
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_hourly_summary(invalid_json_file)
        
        # Valid JSON but invalid summary structure
        invalid_structure_file = tmp_path / "invalid_structure.json"
        with open(invalid_structure_file, 'w') as f:
            json.dump({"invalid": "structure"}, f)
        
        with pytest.raises(ValueError, match="validation failed"):
            load_hourly_summary(invalid_structure_file)

    def test_scan_summary_files(self, tmp_path):
        """Test scanning for summary files in time window."""
        symbol = "SCAN"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        # Create files for various hours
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        files_created = []
        
        for hour_offset in [0, 1, 2, 5, 10]:  # Hours 10, 11, 12, 15, 20
            hour = base_time + timedelta(hours=hour_offset)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = self.create_mock_summary(symbol, hour)
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
            
            files_created.append((hour, file_path))
        
        # Scan for files in window 10:00-13:00 (should find hours 10, 11, 12)
        from_utc = base_time
        to_utc = base_time + timedelta(hours=3)
        
        scanned = scan_summary_files(summaries_dir, symbol, from_utc, to_utc)
        
        # Should find 3 files
        assert len(scanned) == 3
        
        # Should be sorted by hour
        for i in range(len(scanned) - 1):
            assert scanned[i][0] < scanned[i + 1][0]
        
        # Check specific hours
        scanned_hours = [hour for hour, _ in scanned]
        expected_hours = [base_time, base_time + timedelta(hours=1), base_time + timedelta(hours=2)]
        assert scanned_hours == expected_hours

    def test_scan_summary_files_no_symbol_dir(self, tmp_path):
        """Test scanning when symbol directory doesn't exist."""
        symbol = "NOSYM"
        from_utc = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        to_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        scanned = scan_summary_files(tmp_path, symbol, from_utc, to_utc)
        assert len(scanned) == 0

    def test_preflight_summaries_success(self, tmp_path):
        """Test preflight check with sufficient valid data."""
        symbol = "SUCCESS"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        # Create 20 hours of valid data
        base_time = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        
        for hour_offset in range(20):
            hour = base_time + timedelta(hours=hour_offset)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            # Create summary with decent activity
            summary_data = self.create_mock_summary(symbol, hour, orders=10, quotes=25, fills=8)
            with open(file_path, 'w') as f:
                json.dump(summary_data, f, indent=2)
        
        # Run preflight
        from_utc = base_time
        to_utc = base_time + timedelta(hours=20)
        
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=18,
            min_total_count=100
        )
        
        assert is_ready
        assert info["files_found"] == 20
        assert info["files_valid"] == 20
        assert info["total_orders"] == 200  # 10 * 20
        assert info["total_quotes"] == 500  # 25 * 20
        assert info["total_fills"] == 160   # 8 * 20
        assert info["total_activity"] == 860
        assert len(info["gaps"]) == 0
        assert len(info["invalid_files"]) == 0

    def test_preflight_summaries_insufficient_files(self, tmp_path):
        """Test preflight check with insufficient files."""
        symbol = "INSUFFICIENT"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        # Create only 10 files (below threshold of 18)
        base_time = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        
        for hour_offset in range(10):
            hour = base_time + timedelta(hours=hour_offset)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = self.create_mock_summary(symbol, hour)
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
        
        # Run preflight
        from_utc = base_time
        to_utc = base_time + timedelta(hours=24)
        
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=18,
            min_total_count=100
        )
        
        assert not is_ready
        assert info["files_found"] == 10
        assert info["files_valid"] == 10
        assert len(info["gaps"]) == 14  # 24 - 10 = 14 missing hours

    def test_preflight_summaries_insufficient_activity(self, tmp_path):
        """Test preflight check with insufficient total activity."""
        symbol = "LOWACTIVITY"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        # Create 20 files but with very low activity
        base_time = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        
        for hour_offset in range(20):
            hour = base_time + timedelta(hours=hour_offset)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            # Very low activity: 1 order, 1 quote, 0 fills per hour
            summary_data = self.create_mock_summary(symbol, hour, orders=1, quotes=1, fills=0)
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
        
        # Run preflight
        from_utc = base_time
        to_utc = base_time + timedelta(hours=20)
        
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=18,
            min_total_count=100
        )
        
        assert not is_ready
        assert info["files_found"] == 20
        assert info["files_valid"] == 20
        assert info["total_activity"] == 40  # (1+1+0) * 20 = 40 < 100

    def test_preflight_summaries_with_invalid_files(self, tmp_path):
        """Test preflight check with some invalid files."""
        symbol = "INVALID"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        base_time = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        
        # Create mix of valid and invalid files
        for hour_offset in range(20):
            hour = base_time + timedelta(hours=hour_offset)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            if hour_offset < 15:
                # Valid files
                summary_data = self.create_mock_summary(symbol, hour)
                with open(file_path, 'w') as f:
                    json.dump(summary_data, f, indent=2)
            else:
                # Invalid files
                with open(file_path, 'w') as f:
                    f.write("invalid json content")
        
        # Run preflight
        from_utc = base_time
        to_utc = base_time + timedelta(hours=20)
        
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=18,
            min_total_count=100
        )
        
        assert not is_ready  # Invalid files should fail preflight
        assert info["files_found"] == 20
        assert info["files_valid"] == 15
        assert len(info["invalid_files"]) == 5

    def test_preflight_summaries_schema_version_tracking(self, tmp_path):
        """Test that preflight tracks schema versions."""
        symbol = "SCHEMA"
        summaries_dir = tmp_path
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir()
        
        base_time = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        
        # Create files with different schema versions
        schema_versions = ["e1.0", "e1.0", "e1.1", "e1.1", "e1.1"]
        
        for i, schema_version in enumerate(schema_versions):
            hour = base_time + timedelta(hours=i)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = self.create_mock_summary(symbol, hour)
            summary_data["schema_version"] = schema_version
            
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
        
        # Run preflight
        from_utc = base_time
        to_utc = base_time + timedelta(hours=5)
        
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=3,
            min_total_count=50
        )
        
        assert is_ready
        assert info["schema_versions"] == {"e1.1": 2, "e1.1": 3}  # After upgrade

    def test_print_preflight_report(self, capsys):
        """Test the preflight report printing function."""
        # Create mock preflight info
        info = {
            "symbol": "REPORT",
            "window": {
                "from_utc": "2025-01-15T00:00:00Z",
                "to_utc": "2025-01-15T24:00:00Z",
                "hours_expected": 24
            },
            "files_found": 20,
            "files_valid": 18,
            "total_orders": 150,
            "total_quotes": 300,
            "total_fills": 120,
            "total_activity": 570,
            "gaps": ["2025-01-15T10:00:00Z", "2025-01-15T15:00:00Z"],
            "invalid_files": [
                {"hour_utc": "2025-01-15T20:00:00Z", "error": "Invalid JSON"}
            ],
            "schema_versions": {"e1.1": 18},
            "requirements": {"min_files": 15, "min_total_count": 500},
            "is_ready": True
        }
        
        print_preflight_report(info)
        captured = capsys.readouterr()
        
        # Check that report contains key information
        assert "Preflight Report for REPORT" in captured.out
        assert "Files found: 20" in captured.out
        assert "Files valid: 18" in captured.out
        assert "Orders: 150" in captured.out
        assert "Missing hours (2)" in captured.out
        assert "Invalid JSON" in captured.out
        assert "e1.1: 18 files" in captured.out
        assert "Ready for E2" in captured.out

    def test_print_preflight_report_not_ready(self, capsys):
        """Test preflight report for failed preflight."""
        info = {
            "symbol": "NOTREADY",
            "window": {
                "from_utc": "2025-01-15T00:00:00Z",
                "to_utc": "2025-01-15T12:00:00Z",
                "hours_expected": 12
            },
            "files_found": 5,
            "files_valid": 5,
            "total_activity": 25,
            "gaps": [],
            "invalid_files": [],
            "schema_versions": {"e1.1": 5},
            "requirements": {"min_files": 10, "min_total_count": 100},
            "is_ready": False
        }
        
        print_preflight_report(info)
        captured = capsys.readouterr()
        
        assert "Not ready for E2" in captured.out
        assert "Suggestions:" in captured.out
        assert "need 5 more valid files" in captured.out
        assert "reduce min_total_count" in captured.out
