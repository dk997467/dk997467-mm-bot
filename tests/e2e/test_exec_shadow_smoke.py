"""
Minimal smoke tests for exec_demo.py shadow execution.

These tests always work in CI - no network, no complex scenarios.
Just validate basic CLI invocation and JSON structure.
"""

import json
import subprocess
import sys
from pathlib import Path


def _run_cmd(args):
    """Run exec_demo.py and return parsed JSON output."""
    cmd = [sys.executable, "-m", "tools.live.exec_demo"] + args
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    
    if proc.returncode != 0:
        raise RuntimeError(f"exec_demo failed: {proc.stderr}")
    
    return json.loads(proc.stdout)


def test_shadow_minimal_json_report():
    """Test basic shadow run produces valid JSON with expected keys."""
    data = _run_cmd([
        "--shadow",
        "--symbols", "BTCUSDT",
        "--iterations", "3",
        "--maker-only",
    ])
    
    # Sanity keys
    assert "execution" in data
    assert "orders" in data
    assert "risk" in data
    
    # Execution metadata
    assert "symbols" in data["execution"]
    assert isinstance(data["execution"]["symbols"], list)
    assert "BTCUSDT" in data["execution"]["symbols"]
    
    # Orders section
    assert "placed" in data["orders"]
    assert isinstance(data["orders"]["placed"], int)


def test_shadow_multiple_symbols():
    """Test shadow run with multiple symbols."""
    data = _run_cmd([
        "--shadow",
        "--symbols", "BTCUSDT,ETHUSDT",
        "--iterations", "2",
        "--maker-only",
    ])
    
    assert len(data["execution"]["symbols"]) == 2
    assert set(data["execution"]["symbols"]) == {"BTCUSDT", "ETHUSDT"}


def test_shadow_deterministic_structure():
    """Test that JSON structure is deterministic across runs."""
    data1 = _run_cmd([
        "--shadow",
        "--symbols", "BTCUSDT",
        "--iterations", "1",
        "--maker-only",
    ])
    
    data2 = _run_cmd([
        "--shadow",
        "--symbols", "BTCUSDT",
        "--iterations", "1",
        "--maker-only",
    ])
    
    # Keys should be identical
    assert set(data1.keys()) == set(data2.keys())
    assert set(data1["execution"].keys()) == set(data2["execution"].keys())
    assert set(data1["orders"].keys()) == set(data2["orders"].keys())
    assert set(data1["risk"].keys()) == set(data2["risk"].keys())

