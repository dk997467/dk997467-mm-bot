"""Smoke tests for E1 live summaries functionality."""

import json
import subprocess
import pytest
from pathlib import Path


class TestE1Smoke:
    """Test E1 smoke script functionality."""
    
    def test_e1_smoke_script_execution(self, tmp_path):
        """Test that the E1 smoke script runs successfully and generates valid summaries."""
        # Define output directory within tmp_path
        out_dir = tmp_path / "summaries"
        
        # Run the smoke script
        cmd = [
            "python", "-m", "scripts.smoke_e1",
            "--symbol", "SMK",
            "--seed", "12345",
            "--out", str(out_dir)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent  # Project root
        )
        
        # Check that the script succeeded
        assert result.returncode == 0, f"Script failed with stdout: {result.stdout}, stderr: {result.stderr}"
        
        # Check that "E1 SMOKE: OK" appears in stdout
        assert "E1 SMOKE: OK" in result.stdout, f"Success message not found in stdout: {result.stdout}"
        
        # Check that summary files were created
        # Files are under summaries/symbol due to ResearchRecorder structure
        symbol_dir = out_dir / "summaries" / "SMK"
        assert symbol_dir.exists(), f"Symbol directory not created: {symbol_dir}"
        
        json_files = list(symbol_dir.glob("SMK_*.json"))
        assert len(json_files) >= 1, f"No summary files found in {symbol_dir}"
        
        # Validate at least one summary file
        summary_file = json_files[0]
        with open(summary_file, 'r') as f:
            summary_data = json.load(f)
        
        # Check required schema fields
        required_fields = ["symbol", "hour_utc", "counts", "hit_rate_by_bin", 
                          "queue_wait_cdf_ms", "metadata"]
        for field in required_fields:
            assert field in summary_data, f"Missing required field '{field}' in summary"
        
        # Validate symbol
        assert summary_data["symbol"] == "SMK"
        
        # Validate counts structure
        counts = summary_data["counts"]
        assert isinstance(counts["orders"], int)
        assert isinstance(counts["quotes"], int)
        assert isinstance(counts["fills"], int)
        assert counts["orders"] >= 0
        assert counts["quotes"] >= 0
        assert counts["fills"] >= 0
        
        # Validate hit_rate_by_bin structure
        hit_rates = summary_data["hit_rate_by_bin"]
        assert isinstance(hit_rates, dict)
        
        for bin_key, bin_data in hit_rates.items():
            assert isinstance(bin_data, dict)
            assert "count" in bin_data
            assert "fills" in bin_data
            assert isinstance(bin_data["count"], int)
            assert isinstance(bin_data["fills"], int)
            assert bin_data["fills"] <= bin_data["count"], f"Fills > count in bin {bin_key}"
        
        # Validate CDF structure and monotonicity
        cdf = summary_data["queue_wait_cdf_ms"]
        assert isinstance(cdf, list)
        
        if len(cdf) > 0:
            prev_p = -1
            prev_v = -1
            
            for point in cdf:
                assert isinstance(point, dict)
                assert "p" in point
                assert "v" in point
                
                p = point["p"]
                v = point["v"]
                
                assert 0 <= p <= 1, f"Invalid probability {p}"
                assert v >= 0, f"Invalid value {v}"
                assert p > prev_p, f"CDF p values not increasing: {p} <= {prev_p}"
                assert v >= prev_v, f"CDF v values decreasing: {v} < {prev_v}"
                
                prev_p = p
                prev_v = v
        
        # Validate metadata
        metadata = summary_data["metadata"]
        assert "git_sha" in metadata
        assert "cfg_hash" in metadata
        assert isinstance(metadata["git_sha"], str)
        assert isinstance(metadata["cfg_hash"], str)
        
        print(f"Successfully validated summary file: {summary_file}")
    
    def test_e1_smoke_script_determinism(self, tmp_path):
        """Test that the smoke script produces deterministic results with same seed."""
        out_dir1 = tmp_path / "run1"
        out_dir2 = tmp_path / "run2"
        
        # Run script twice with same seed
        seed = "99999"
        symbol = "DET"
        
        for out_dir in [out_dir1, out_dir2]:
            cmd = [
                "python", "-m", "scripts.smoke_e1",
                "--symbol", symbol,
                "--seed", seed,
                "--out", str(out_dir)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent.parent
            )
            
            assert result.returncode == 0, f"Script failed: {result.stderr}\nStdout: {result.stdout}"
        
        # Compare generated files - they are under summaries/symbol due to ResearchRecorder structure
        files1 = list((out_dir1 / "summaries" / symbol).glob(f"{symbol}_*.json"))
        files2 = list((out_dir2 / "summaries" / symbol).glob(f"{symbol}_*.json"))
        
        assert len(files1) == len(files2), "Different number of files generated"
        assert len(files1) > 0, "No files generated"
        
        # Sort files by name for comparison
        files1.sort(key=lambda x: x.name)
        files2.sort(key=lambda x: x.name)
        
        # Compare content of corresponding files
        for f1, f2 in zip(files1, files2):
            with open(f1, 'r') as file1, open(f2, 'r') as file2:
                data1 = json.load(file1)
                data2 = json.load(file2)
            
            # Files should be identical with same seed
            assert data1 == data2, f"Files differ between runs: {f1.name} vs {f2.name}"
    
    def test_e1_smoke_script_different_symbols(self, tmp_path):
        """Test that different symbols create separate directories."""
        symbols = ["SYM1", "SYM2"]
        
        for symbol in symbols:
            cmd = [
                "python", "-m", "scripts.smoke_e1",
                "--symbol", symbol,
                "--seed", "777",
                "--out", str(tmp_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent.parent
            )
            
            assert result.returncode == 0, f"Script failed for {symbol}: {result.stderr}"
        
        # Check that separate directories were created
        for symbol in symbols:
            symbol_dir = tmp_path / "summaries" / symbol
            assert symbol_dir.exists(), f"Directory not created for {symbol}"
            
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) > 0, f"No files created for {symbol}"
    
    def test_e1_smoke_script_help(self):
        """Test that the smoke script shows help when requested."""
        cmd = ["python", "-m", "scripts.smoke_e1", "--help"]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent
        )
        
        assert result.returncode == 0
        assert "E1 Smoke Test for Live Summaries" in result.stdout
        assert "--symbol" in result.stdout
        assert "--seed" in result.stdout
        assert "--out" in result.stdout
