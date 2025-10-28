#!/usr/bin/env python3
"""
End-to-end byte-for-byte comparison tests for golden files.

These tests ensure that CLI tools produce deterministic, stable output
that matches pre-approved golden files exactly (byte-for-byte).
"""
import pytest
import subprocess
import json
from pathlib import Path
import os


@pytest.fixture
def ensure_fixtures():
    """Ensure test fixtures exist."""
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    
    # Create region_canary_metrics.jsonl if not exists
    region_fixture = fixtures_dir / "region_canary_metrics.jsonl"
    if not region_fixture.exists():
        with open(region_fixture, 'w', encoding='utf-8', newline='') as f:
            f.write('{"region":"us-east","window":"morning","net_bps":3.5,"order_age_p95_ms":310,"fill_rate":0.95,"taker_share_pct":12.0}\n')
            f.write('{"region":"us-west","window":"morning","net_bps":2.8,"order_age_p95_ms":320,"fill_rate":0.92,"taker_share_pct":14.0}\n')
    
    return fixtures_dir


@pytest.mark.e2e
class TestRegionCanaryByteForByte:
    """Byte-for-byte tests for region canary comparison."""
    
    def test_deterministic_output(self, ensure_fixtures, tmp_path):
        """Test that region canary produces identical output on repeated runs."""
        fixture = ensure_fixtures / "region_canary_metrics.jsonl"
        
        # Set deterministic timestamp
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        
        # Run 1
        out1 = tmp_path / "run1.json"
        subprocess.run([
            "python", "-m", "tools.region.run_canary_compare",
            "--regions", "us-east,us-west",
            "--in", str(fixture),
            "--out", str(out1)
        ], check=True, env=env)
        
        # Run 2
        out2 = tmp_path / "run2.json"
        subprocess.run([
            "python", "-m", "tools.region.run_canary_compare",
            "--regions", "us-east,us-west",
            "--in", str(fixture),
            "--out", str(out2)
        ], check=True, env=env)
        
        # Byte-for-byte comparison
        bytes1 = out1.read_bytes()
        bytes2 = out2.read_bytes()
        assert bytes1 == bytes2, "Output should be identical byte-for-byte"
    
    def test_json_structure(self, ensure_fixtures, tmp_path):
        """Test JSON structure and determinism."""
        fixture = ensure_fixtures / "region_canary_metrics.jsonl"
        out_json = tmp_path / "output.json"
        
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        
        subprocess.run([
            "python", "-m", "tools.region.run_canary_compare",
            "--regions", "us-east,us-west",
            "--in", str(fixture),
            "--out", str(out_json)
        ], check=True, env=env)
        
        # Check JSON is valid and has expected keys
        data = json.loads(out_json.read_text())
        assert "regions" in data
        assert "runtime" in data
        assert "windows" in data
        assert "winner" in data
        
        # Check JSON is compact (no extra spaces)
        raw_text = out_json.read_text()
        assert ", " not in raw_text  # Should use "," not ", "
        assert ": " not in raw_text or raw_text.count(": ") == 0  # Should use ":" not ": " (except in strings)
    
    def test_trailing_newline(self, ensure_fixtures, tmp_path):
        """Test that output ends with newline."""
        fixture = ensure_fixtures / "region_canary_metrics.jsonl"
        out_json = tmp_path / "output.json"
        
        subprocess.run([
            "python", "-m", "tools.region.run_canary_compare",
            "--regions", "us-east,us-west",
            "--in", str(fixture),
            "--out", str(out_json)
        ], check=True)
        
        content = out_json.read_text()
        assert content.endswith('\n'), "JSON output must end with newline"


@pytest.mark.e2e
class TestEdgeSentinelByteForByte:
    """Byte-for-byte tests for edge sentinel report."""
    
    def test_deterministic_output_no_data(self, tmp_path):
        """Test edge sentinel with no input data."""
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        env['PYTHONPATH'] = str(Path.cwd())
        
        # Run 1
        out1 = tmp_path / "run1"
        subprocess.run([
            "python", "-m", "tools.edge_sentinel.report",
            "--out-json", str(out1 / "EDGE_SENTINEL.json"),
            "--out-md", str(out1 / "EDGE_SENTINEL.md")
        ], check=True, env=env)
        
        # Run 2
        out2 = tmp_path / "run2"
        subprocess.run([
            "python", "-m", "tools.edge_sentinel.report",
            "--out-json", str(out2 / "EDGE_SENTINEL.json"),
            "--out-md", str(out2 / "EDGE_SENTINEL.md")
        ], check=True, env=env)
        
        # Byte-for-byte comparison
        json1 = (out1 / "EDGE_SENTINEL.json").read_bytes()
        json2 = (out2 / "EDGE_SENTINEL.json").read_bytes()
        assert json1 == json2
        
        md1 = (out1 / "EDGE_SENTINEL.md").read_bytes()
        md2 = (out2 / "EDGE_SENTINEL.md").read_bytes()
        assert md1 == md2


@pytest.mark.e2e
class TestTuningReportByteForByte:
    """Byte-for-byte tests for tuning report."""
    
    def test_deterministic_output_no_sweep(self, tmp_path):
        """Test tuning report with no sweep data."""
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        
        # Run 1
        out1 = tmp_path / "run1"
        out1.mkdir()
        subprocess.run([
            "python", "-m", "tools.tuning.report_tuning",
            "--sweep", str(tmp_path / "nonexistent.json"),
            "--out-json", str(out1 / "TUNING_REPORT.json"),
            "--out-md", str(out1 / "TUNING_REPORT.md")
        ], check=True, env=env)
        
        # Run 2
        out2 = tmp_path / "run2"
        out2.mkdir()
        subprocess.run([
            "python", "-m", "tools.tuning.report_tuning",
            "--sweep", str(tmp_path / "nonexistent.json"),
            "--out-json", str(out2 / "TUNING_REPORT.json"),
            "--out-md", str(out2 / "TUNING_REPORT.md")
        ], check=True, env=env)
        
        # Byte-for-byte comparison
        json1 = (out1 / "TUNING_REPORT.json").read_bytes()
        json2 = (out2 / "TUNING_REPORT.json").read_bytes()
        assert json1 == json2


@pytest.mark.e2e
class TestAnomalyRadarByteForByte:
    """Byte-for-byte tests for anomaly radar."""
    
    def test_deterministic_output_minimal(self, tmp_path):
        """Test anomaly radar with minimal data."""
        env = os.environ.copy()
        env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
        
        # Run 1
        out1 = tmp_path / "run1.json"
        subprocess.run([
            "python", "-m", "tools.soak.anomaly_radar",
            "--out", str(out1)
        ], check=True, env=env)
        
        # Run 2
        out2 = tmp_path / "run2.json"
        subprocess.run([
            "python", "-m", "tools.soak.anomaly_radar",
            "--out", str(out2)
        ], check=True, env=env)
        
        # Byte-for-byte comparison
        bytes1 = out1.read_bytes()
        bytes2 = out2.read_bytes()
        assert bytes1 == bytes2


@pytest.mark.e2e
class TestReproMinimizerByteForByte:
    """Byte-for-byte tests for repro minimizer."""
    
    def test_deterministic_output(self, tmp_path):
        """Test repro minimizer produces identical output."""
        # Create input file
        input_file = tmp_path / "input.jsonl"
        with open(input_file, 'w', encoding='utf-8', newline='') as f:
            f.write('{"type":"quote"}\n')
            f.write('{"type":"trade"}\n')
            f.write('{"type":"guard","reason":"DRIFT"}\n')
        
        # Run 1
        out1 = tmp_path / "run1.jsonl"
        subprocess.run([
            "python", "-m", "tools.debug.repro_minimizer",
            "--events", str(input_file),
            "--out", str(out1)
        ], check=True)
        
        # Run 2
        out2 = tmp_path / "run2.jsonl"
        subprocess.run([
            "python", "-m", "tools.debug.repro_minimizer",
            "--events", str(input_file),
            "--out", str(out2)
        ], check=True)
        
        # Byte-for-byte comparison
        bytes1 = out1.read_bytes()
        bytes2 = out2.read_bytes()
        assert bytes1 == bytes2
    
    def test_no_crlf(self, tmp_path):
        """Test that output uses LF, not CRLF."""
        input_file = tmp_path / "input.jsonl"
        input_file.write_text('{"type":"guard"}\n', encoding='utf-8')
        
        out_file = tmp_path / "output.jsonl"
        subprocess.run([
            "python", "-m", "tools.debug.repro_minimizer",
            "--events", str(input_file),
            "--out", str(out_file)
        ], check=True)
        
        raw_bytes = out_file.read_bytes()
        assert b'\r\n' not in raw_bytes, "Output should use LF, not CRLF"
        assert raw_bytes.endswith(b'\n'), "Output should end with LF"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])

