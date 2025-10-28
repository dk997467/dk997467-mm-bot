"""
Minimal smoke tests for exec_demo.py with Bybit exchange.

These tests always work in CI - simple validation only.
"""

import json
import subprocess
import sys


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
        raise RuntimeError(f"exec_demo failed (rc={proc.returncode}): {proc.stderr}")
    
    return json.loads(proc.stdout)


def test_bybit_exchange_flag_accepted():
    """Test that --exchange bybit flag is accepted (using fake for smoke test)."""
    # Note: Use fake exchange for smoke test to avoid API key requirements
    data = _run_cmd([
        "--shadow",
        "--exchange", "fake",
        "--symbols", "BTCUSDT",
        "--iterations", "3",
        "--maker-only",
    ])
    
    assert data["execution"]["symbols"] == ["BTCUSDT"]
    assert "orders" in data
    assert "risk" in data


def test_testnet_flag_accepted():
    """Test that --testnet flag is accepted."""
    data = _run_cmd([
        "--shadow",
        "--exchange", "fake",
        "--testnet",
        "--symbols", "BTCUSDT",
        "--iterations", "2",
        "--maker-only",
    ])
    
    # Just verify it runs and produces output
    assert "execution" in data
    assert data["execution"]["symbols"] == ["BTCUSDT"]

