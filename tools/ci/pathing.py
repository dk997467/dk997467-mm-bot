#!/usr/bin/env python3
"""
Path Resolution Utilities

Provides robust path resolution for project root, fixtures, and other resources.
Handles both CI environments and local development.

Usage:
    from tools.ci.pathing import project_root, fixtures_dir
    
    root = project_root()
    fixtures = fixtures_dir()
"""

import os
import sys
from pathlib import Path
from typing import Optional


def project_root(start: Optional[Path] = None) -> Path:
    """
    Find project root by looking for .git or pyproject.toml.
    
    Args:
        start: Starting path (default: this file's location)
    
    Returns:
        Path to project root
    
    Raises:
        RuntimeError: If project root cannot be found
    """
    if start is None:
        start = Path(__file__).resolve().parent
    
    current = start
    
    # Walk up directory tree looking for markers
    for _ in range(10):  # Limit search depth to prevent infinite loops
        # Check for common project root markers
        if (current / ".git").exists():
            return current
        if (current / "pyproject.toml").exists():
            return current
        if (current / "setup.py").exists():
            return current
        
        # Move up one level
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent
    
    # Fallback: assume we're in tools/ci, so go up 2 levels
    fallback = Path(__file__).resolve().parents[2]
    if fallback.exists():
        return fallback
    
    raise RuntimeError(f"Could not find project root starting from {start}")


def fixtures_dir() -> Path:
    """
    Get fixtures directory path.
    
    Priority:
    1. FIXTURES_DIR environment variable
    2. <project_root>/tests/fixtures (if exists)
    3. <project_root>/fixtures (if exists)
    4. <project_root>/tests/fixtures (fallback, may not exist)
    
    Returns:
        Path to fixtures directory
    """
    # 1. Check environment variable
    env_path = os.environ.get("FIXTURES_DIR")
    if env_path:
        path = Path(env_path)
        # Allow relative paths (resolve against current working directory)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    
    # 2. Check project root locations
    root = project_root()
    
    # Prefer tests/fixtures
    tests_fixtures = root / "tests" / "fixtures"
    if tests_fixtures.exists():
        return tests_fixtures
    
    # Fallback to root-level fixtures
    root_fixtures = root / "fixtures"
    if root_fixtures.exists():
        return root_fixtures
    
    # 3. Return tests/fixtures as best-effort default (may not exist)
    return tests_fixtures


def golden_dir() -> Path:
    """
    Get golden files directory path.
    
    Priority:
    1. GOLDEN_DIR environment variable
    2. <project_root>/tests/golden
    
    Returns:
        Path to golden directory
    """
    # 1. Check environment variable
    env_path = os.environ.get("GOLDEN_DIR")
    if env_path:
        path = Path(env_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    
    # 2. Default to tests/golden
    root = project_root()
    return root / "tests" / "golden"


def artifacts_dir() -> Path:
    """
    Get artifacts output directory path.
    
    Priority:
    1. ARTIFACTS_DIR environment variable
    2. <project_root>/artifacts
    
    Returns:
        Path to artifacts directory
    """
    # 1. Check environment variable
    env_path = os.environ.get("ARTIFACTS_DIR")
    if env_path:
        path = Path(env_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    
    # 2. Default to artifacts
    root = project_root()
    return root / "artifacts"


if __name__ == "__main__":
    # Simple CLI for debugging
    print(f"Project Root: {project_root()}")
    print(f"Fixtures Dir: {fixtures_dir()}")
    print(f"Golden Dir:   {golden_dir()}")
    print(f"Artifacts Dir: {artifacts_dir()}")

