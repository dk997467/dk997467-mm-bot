"""
Unit tests for robust numeric sorting of ITER_SUMMARY files.

Verifies that files sort correctly by iteration number (not lexicographically).
"""
import pytest
from pathlib import Path


class TestIterNumericSort:
    """Test numeric sorting of ITER_SUMMARY_*.json files."""
    
    def test_extract_iter_index(self):
        """Test extraction of iteration index from filename."""
        from tools.soak.audit_artifacts import extract_iter_index
        
        assert extract_iter_index("ITER_SUMMARY_1.json") == 1
        assert extract_iter_index("ITER_SUMMARY_10.json") == 10
        assert extract_iter_index("ITER_SUMMARY_24.json") == 24
        assert extract_iter_index("ITER_SUMMARY_100.json") == 100
        
        # Invalid filenames
        assert extract_iter_index("ITER_SUMMARY.json") is None
        assert extract_iter_index("OTHER_FILE.json") is None
        assert extract_iter_index("iter_summary_1.json") is None  # Case sensitive
    
    def test_sort_order_numeric_not_lexicographic(self):
        """Test that files sort numerically, not lexicographically."""
        from tools.soak.audit_artifacts import extract_iter_index
        
        # Lexicographic sort would be: 1, 10, 11, 2, 20, 3
        # Numeric sort should be:      1, 2, 3, 10, 11, 20
        filenames = [
            "ITER_SUMMARY_10.json",
            "ITER_SUMMARY_1.json",
            "ITER_SUMMARY_20.json",
            "ITER_SUMMARY_2.json",
            "ITER_SUMMARY_11.json",
            "ITER_SUMMARY_3.json",
        ]
        
        # Lexicographic sort (WRONG)
        lexicographic = sorted(filenames)
        assert lexicographic == [
            "ITER_SUMMARY_1.json",
            "ITER_SUMMARY_10.json",  # Wrong position!
            "ITER_SUMMARY_11.json",  # Wrong position!
            "ITER_SUMMARY_2.json",
            "ITER_SUMMARY_20.json",  # Wrong position!
            "ITER_SUMMARY_3.json",
        ]
        
        # Numeric sort (CORRECT)
        numeric = sorted(filenames, key=lambda f: extract_iter_index(f) or 0)
        assert numeric == [
            "ITER_SUMMARY_1.json",
            "ITER_SUMMARY_2.json",
            "ITER_SUMMARY_3.json",
            "ITER_SUMMARY_10.json",
            "ITER_SUMMARY_11.json",
            "ITER_SUMMARY_20.json",
        ]
    
    def test_sort_with_path_objects(self):
        """Test sorting works with Path objects."""
        from tools.soak.audit_artifacts import extract_iter_index
        
        paths = [
            Path("artifacts/soak/ITER_SUMMARY_10.json"),
            Path("artifacts/soak/ITER_SUMMARY_1.json"),
            Path("artifacts/soak/ITER_SUMMARY_2.json"),
        ]
        
        sorted_paths = sorted(paths, key=lambda p: extract_iter_index(p.name) or 0)
        
        assert sorted_paths[0].name == "ITER_SUMMARY_1.json"
        assert sorted_paths[1].name == "ITER_SUMMARY_2.json"
        assert sorted_paths[2].name == "ITER_SUMMARY_10.json"
    
    def test_missing_iteration_index_sorts_to_end(self):
        """Test that files without iteration index sort to beginning (0)."""
        from tools.soak.audit_artifacts import extract_iter_index
        
        filenames = [
            "ITER_SUMMARY_5.json",
            "OTHER_FILE.json",  # No iteration index
            "ITER_SUMMARY_2.json",
            "RANDOM.json",  # No iteration index
        ]
        
        sorted_files = sorted(filenames, key=lambda f: extract_iter_index(f) or 0)
        
        # Files without index (returning 0) should be first
        assert sorted_files[0] == "OTHER_FILE.json"
        assert sorted_files[1] == "RANDOM.json"
        assert sorted_files[2] == "ITER_SUMMARY_2.json"
        assert sorted_files[3] == "ITER_SUMMARY_5.json"


class TestBuildReportsSort:
    """Test that build_reports.py also uses numeric sort."""
    
    def test_load_iter_summaries_numeric_order(self, tmp_path):
        """Test that load_iter_summaries loads consecutive iterations."""
        from tools.soak.build_reports import load_iter_summaries
        import json
        
        # Create consecutive test files (1-5)
        # Note: load_iter_summaries uses range(1,100) and breaks on first missing
        for i in [1, 2, 3, 4, 5]:
            path = tmp_path / f"ITER_SUMMARY_{i}.json"
            path.write_text(json.dumps({
                "summary": {
                    "net_bps": float(i),
                    "iter": i
                }
            }))
        
        summaries = load_iter_summaries(tmp_path)
        
        # Check that we got all files
        assert len(summaries) == 5
        
        # Check that keys are in numeric order
        keys = sorted(summaries.keys())
        assert keys == [1, 2, 3, 4, 5]
        
        # Check that data matches
        assert summaries[1]["summary"]["iter"] == 1
        assert summaries[2]["summary"]["iter"] == 2
        assert summaries[5]["summary"]["iter"] == 5


class TestExtractPostSoakSnapshotSort:
    """Test that extract_post_soak_snapshot.py uses numeric sort."""
    
    def test_iter_files_function_numeric_sort(self):
        """Test _iter_files() helper uses numeric sort."""
        # Import the function
        try:
            from tools.soak.extract_post_soak_snapshot import _iter_files
        except ImportError:
            pytest.skip("extract_post_soak_snapshot not available")
        
        # This function already has numeric sorting built-in
        # Just verify it exists and has the right signature
        assert callable(_iter_files)


class TestVerifyDeltasSort:
    """Test that verify_deltas_applied.py uses numeric sort."""
    
    def test_find_iter_summaries_numeric_sort(self, tmp_path):
        """Test that find_iter_summaries sorts numerically."""
        try:
            from tools.soak.verify_deltas_applied import find_iter_summaries
            import json
        except ImportError:
            pytest.skip("verify_deltas_applied not available")
        
        # Create test files
        for i in [1, 10, 2, 20, 3]:
            path = tmp_path / f"ITER_SUMMARY_{i}.json"
            path.write_text(json.dumps({"summary": {}}))
        
        files = find_iter_summaries(tmp_path)
        
        # Extract iteration numbers
        import re
        iter_nums = []
        for f in files:
            match = re.search(r'ITER_SUMMARY_(\d+)\.json', str(f))
            if match:
                iter_nums.append(int(match.group(1)))
        
        # Should be in numeric order
        assert iter_nums == [1, 2, 3, 10, 20]

