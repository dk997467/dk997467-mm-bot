#!/usr/bin/env python3
"""
Unit tests for tools.ci.pathing module.

Tests path resolution logic for project root, fixtures, golden files, etc.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tools.ci.pathing import project_root as get_project_root
from tools.ci.pathing import fixtures_dir, golden_dir, artifacts_dir


class TestPathing(unittest.TestCase):
    """Tests for path resolution utilities."""
    
    def test_project_root_finds_git(self):
        """Test that project_root() finds .git directory."""
        root = get_project_root()
        
        # Should find project root
        self.assertTrue(root.exists())
        
        # Should have .git or pyproject.toml
        has_git = (root / ".git").exists()
        has_pyproject = (root / "pyproject.toml").exists()
        
        self.assertTrue(has_git or has_pyproject,
                       f"Project root {root} should have .git or pyproject.toml")
    
    def test_project_root_is_consistent(self):
        """Test that project_root() returns consistent results."""
        root1 = get_project_root()
        root2 = get_project_root()
        
        self.assertEqual(root1, root2)
    
    def test_fixtures_dir_respects_env(self):
        """Test that fixtures_dir() respects FIXTURES_DIR environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_fixtures = Path(tmpdir) / "custom_fixtures"
            custom_fixtures.mkdir()
            
            # Set environment variable
            original = os.environ.get("FIXTURES_DIR")
            try:
                os.environ["FIXTURES_DIR"] = str(custom_fixtures)
                
                result = fixtures_dir()
                
                # Should return the custom path
                self.assertEqual(result, custom_fixtures)
            
            finally:
                # Restore original value
                if original is None:
                    os.environ.pop("FIXTURES_DIR", None)
                else:
                    os.environ["FIXTURES_DIR"] = original
    
    def test_fixtures_dir_without_env(self):
        """Test that fixtures_dir() finds tests/fixtures without env var."""
        # Remove env var if set
        original = os.environ.pop("FIXTURES_DIR", None)
        
        try:
            result = fixtures_dir()
            
            # Should return tests/fixtures (may or may not exist)
            # But should be under project root
            root = get_project_root()
            
            # Result should be absolute
            self.assertTrue(result.is_absolute())
            
            # Result should be under project root
            try:
                result.relative_to(root)
            except ValueError:
                self.fail(f"Fixtures dir {result} is not under project root {root}")
            
            # Should prefer tests/fixtures
            expected = root / "tests" / "fixtures"
            if expected.exists():
                self.assertEqual(result, expected)
        
        finally:
            # Restore original value
            if original is not None:
                os.environ["FIXTURES_DIR"] = original
    
    def test_golden_dir_respects_env(self):
        """Test that golden_dir() respects GOLDEN_DIR environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_golden = Path(tmpdir) / "custom_golden"
            custom_golden.mkdir()
            
            # Set environment variable
            original = os.environ.get("GOLDEN_DIR")
            try:
                os.environ["GOLDEN_DIR"] = str(custom_golden)
                
                result = golden_dir()
                
                # Should return the custom path
                self.assertEqual(result, custom_golden)
            
            finally:
                # Restore original value
                if original is None:
                    os.environ.pop("GOLDEN_DIR", None)
                else:
                    os.environ["GOLDEN_DIR"] = original
    
    def test_golden_dir_default(self):
        """Test that golden_dir() defaults to tests/golden."""
        # Remove env var if set
        original = os.environ.pop("GOLDEN_DIR", None)
        
        try:
            result = golden_dir()
            root = get_project_root()
            expected = root / "tests" / "golden"
            
            self.assertEqual(result, expected)
        
        finally:
            # Restore original value
            if original is not None:
                os.environ["GOLDEN_DIR"] = original
    
    def test_artifacts_dir_respects_env(self):
        """Test that artifacts_dir() respects ARTIFACTS_DIR environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_artifacts = Path(tmpdir) / "custom_artifacts"
            custom_artifacts.mkdir()
            
            # Set environment variable
            original = os.environ.get("ARTIFACTS_DIR")
            try:
                os.environ["ARTIFACTS_DIR"] = str(custom_artifacts)
                
                result = artifacts_dir()
                
                # Should return the custom path
                self.assertEqual(result, custom_artifacts)
            
            finally:
                # Restore original value
                if original is None:
                    os.environ.pop("ARTIFACTS_DIR", None)
                else:
                    os.environ["ARTIFACTS_DIR"] = original
    
    def test_artifacts_dir_default(self):
        """Test that artifacts_dir() defaults to artifacts/."""
        # Remove env var if set
        original = os.environ.pop("ARTIFACTS_DIR", None)
        
        try:
            result = artifacts_dir()
            root = get_project_root()
            expected = root / "artifacts"
            
            self.assertEqual(result, expected)
        
        finally:
            # Restore original value
            if original is not None:
                os.environ["ARTIFACTS_DIR"] = original
    
    def test_relative_env_paths(self):
        """Test that relative paths in env vars are resolved against cwd."""
        # Test with FIXTURES_DIR
        original = os.environ.get("FIXTURES_DIR")
        try:
            # Set relative path
            os.environ["FIXTURES_DIR"] = "my_fixtures"
            
            result = fixtures_dir()
            
            # Should be absolute
            self.assertTrue(result.is_absolute())
            
            # Should be under current working directory
            expected = Path.cwd() / "my_fixtures"
            self.assertEqual(result, expected)
        
        finally:
            # Restore original value
            if original is None:
                os.environ.pop("FIXTURES_DIR", None)
            else:
                os.environ["FIXTURES_DIR"] = original


if __name__ == "__main__":
    unittest.main()

