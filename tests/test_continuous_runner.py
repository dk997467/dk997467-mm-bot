"""
Unit tests for tools/soak/continuous_runner.py

Tests:
- File lock mechanism
- Single cycle execution
- Max iterations limit
- Alert building and sending (dry-run)
- Idempotency (unchanged summary skip)
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture
def sample_summary():
    """Sample SOAK_SUMMARY.json."""
    return {
        "generated_at_utc": "2025-10-26T12:00:00Z",
        "windows": 24,
        "min_windows_required": 24,
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"median": 3.2, "last": 3.1, "trend": "↑", "status": "OK"},
                "maker_taker_ratio": {"median": 0.84, "last": 0.86, "trend": "≈", "status": "OK"},
                "p95_latency_ms": {"median": 245, "last": 232, "trend": "↓", "status": "OK"},
                "risk_ratio": {"median": 0.33, "last": 0.34, "trend": "≈", "status": "OK"}
            },
            "ETHUSDT": {
                "edge_bps": {"median": 2.9, "last": 2.4, "trend": "↓", "status": "CRIT"},
                "maker_taker_ratio": {"median": 0.82, "last": 0.82, "trend": "≈", "status": "OK"},
                "p95_latency_ms": {"median": 360, "last": 360, "trend": "↑", "status": "CRIT"},
                "risk_ratio": {"median": 0.42, "last": 0.42, "trend": "↑", "status": "WARN"}
            }
        },
        "overall": {
            "crit_count": 2,
            "warn_count": 1,
            "ok_count": 1,
            "verdict": "CRIT"
        },
        "meta": {
            "commit_range": "abc123..def456",
            "profile": "moderate",
            "source": "soak"
        }
    }


@pytest.fixture
def sample_violations():
    """Sample VIOLATIONS.json."""
    return [
        {
            "symbol": "ETHUSDT",
            "metric": "p95_latency_ms",
            "level": "CRIT",
            "window_index": 20,
            "value": 360.0,
            "threshold": 350.0,
            "note": "p95_latency_ms (360.0) > critical threshold (350.0)"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "edge_bps",
            "level": "CRIT",
            "window_index": 22,
            "value": 2.4,
            "threshold": 2.5,
            "note": "edge_bps (2.4) < critical threshold (2.5)"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "risk_ratio",
            "level": "WARN",
            "window_index": 23,
            "value": 0.42,
            "threshold": 0.40,
            "note": "risk_ratio (0.42) > warning threshold (0.40)"
        }
    ]


def test_file_lock_basic(tmp_path):
    """Test basic file lock acquire and release."""
    from tools.soak.continuous_runner import FileLock
    
    lock_file = tmp_path / "test.lock"
    lock = FileLock(lock_file)
    
    # First acquire should succeed
    assert lock.acquire() is True
    assert lock_file.exists()
    
    # Lock file should contain PID
    pid = int(lock_file.read_text())
    assert pid == lock.pid
    
    # Release
    lock.release()
    assert not lock_file.exists()


def test_file_lock_already_locked(tmp_path):
    """Test that second lock fails when already locked."""
    from tools.soak.continuous_runner import FileLock
    
    lock_file = tmp_path / "test.lock"
    lock1 = FileLock(lock_file)
    lock2 = FileLock(lock_file)
    
    # First lock succeeds
    assert lock1.acquire() is True
    
    # Second lock fails
    assert lock2.acquire() is False
    
    # Cleanup
    lock1.release()


def test_file_lock_stale_removal(tmp_path):
    """Test that stale locks are auto-removed."""
    from tools.soak.continuous_runner import FileLock
    
    lock_file = tmp_path / "test.lock"
    
    # Create a stale lock (>6h old)
    lock_file.write_text("99999")
    # Manually set mtime to 7 hours ago
    old_time = time.time() - (7 * 3600)
    lock_file.touch()
    import os
    os.utime(lock_file, (old_time, old_time))
    
    # New lock should remove stale and acquire
    lock = FileLock(lock_file, stale_hours=6)
    assert lock.acquire() is True
    assert lock_file.exists()
    
    # PID should be updated
    pid = int(lock_file.read_text())
    assert pid == lock.pid
    
    lock.release()


def test_build_alert_text(sample_summary, sample_violations):
    """Test alert text building."""
    from tools.soak.continuous_runner import build_alert_text
    
    text = build_alert_text(sample_summary, sample_violations, "dev", "bybit")
    
    # Check basic structure
    assert "[🔴 CRIT]" in text
    assert "env=dev" in text
    assert "exch=bybit" in text
    assert "windows=24" in text
    assert "symbols=2" in text
    assert "crit=2" in text
    assert "warn=1" in text
    
    # Check top violations
    assert "Top violations:" in text
    assert "ETHUSDT" in text
    assert "POST_SOAK_ANALYSIS.md" in text


def test_send_telegram_dry_run(sample_summary, sample_violations, capsys):
    """Test Telegram alert in dry-run mode."""
    from tools.soak.continuous_runner import send_telegram_message, build_alert_text
    
    text = build_alert_text(sample_summary, sample_violations, "dev", "bybit")
    result = send_telegram_message("fake_token", "fake_chat_id", text, dry_run=True)
    
    assert result is True
    
    captured = capsys.readouterr()
    assert "[DRY-RUN] Telegram message:" in captured.out
    assert "CRIT" in captured.out


def test_send_slack_dry_run(sample_summary, sample_violations, capsys):
    """Test Slack alert in dry-run mode."""
    from tools.soak.continuous_runner import send_slack_webhook, build_alert_text
    
    text = build_alert_text(sample_summary, sample_violations, "dev", "bybit")
    result = send_slack_webhook("https://hooks.slack.com/fake", text, dry_run=True)
    
    assert result is True
    
    captured = capsys.readouterr()
    assert "[DRY-RUN] Slack message:" in captured.out
    assert "CRIT" in captured.out


def test_compute_file_hash(tmp_path):
    """Test file hash computation."""
    from tools.soak.continuous_runner import compute_file_hash
    
    file_path = tmp_path / "test.json"
    
    # Non-existent file
    assert compute_file_hash(file_path) == ""
    
    # Create file
    file_path.write_text('{"test": "data"}')
    hash1 = compute_file_hash(file_path)
    assert hash1 != ""
    assert len(hash1) == 64  # SHA256
    
    # Same content = same hash
    hash2 = compute_file_hash(file_path)
    assert hash1 == hash2
    
    # Different content = different hash
    file_path.write_text('{"test": "changed"}')
    hash3 = compute_file_hash(file_path)
    assert hash1 != hash3


def test_run_single_cycle_unchanged_summary(tmp_path, sample_summary, monkeypatch, capsys):
    """Test that unchanged summary skips export."""
    from tools.soak.continuous_runner import run_single_cycle
    
    # Setup paths
    out_dir = tmp_path / "reports" / "analysis"
    out_dir.mkdir(parents=True)
    summary_path = out_dir / "SOAK_SUMMARY.json"
    
    # Create initial summary
    summary_path.write_text(json.dumps(sample_summary))
    
    # Mock args
    args = MagicMock()
    args.iter_glob = "artifacts/soak/latest/ITER_SUMMARY_*.json"
    args.min_windows = 24
    args.out_dir = str(out_dir)
    args.exit_on_crit = False
    args.verbose = True
    args.env = "dev"
    args.exchange = "bybit"
    args.redis_url = "redis://localhost:6379/0"
    args.ttl = 3600
    args.stream = True
    args.stream_maxlen = 5000
    args.dry_run = True
    args.alert = []
    
    # Mock run_analyzer to return success without changing summary
    with patch('tools.soak.continuous_runner.run_analyzer', return_value=0):
        metrics = run_single_cycle(args)
    
    # Should detect unchanged and skip
    assert metrics["verdict"] == "UNCHANGED"
    
    captured = capsys.readouterr()
    assert "Summary unchanged, skip export" in captured.out


def test_run_single_cycle_crit_verdict(tmp_path, sample_summary, sample_violations, monkeypatch):
    """Test single cycle with CRIT verdict."""
    from tools.soak.continuous_runner import run_single_cycle
    
    # Setup paths
    out_dir = tmp_path / "reports" / "analysis"
    out_dir.mkdir(parents=True)
    summary_path = out_dir / "SOAK_SUMMARY.json"
    violations_path = out_dir / "VIOLATIONS.json"
    
    # Mock args
    args = MagicMock()
    args.iter_glob = "artifacts/soak/latest/ITER_SUMMARY_*.json"
    args.min_windows = 24
    args.out_dir = str(out_dir)
    args.exit_on_crit = False
    args.verbose = True
    args.env = "dev"
    args.exchange = "bybit"
    args.redis_url = "redis://localhost:6379/0"
    args.ttl = 3600
    args.stream = True
    args.stream_maxlen = 5000
    args.dry_run = True
    args.alert = ["telegram"]
    
    # Mock run_analyzer to create summary and violations
    def mock_analyzer(*args, **kwargs):
        summary_path.write_text(json.dumps(sample_summary))
        violations_path.write_text(json.dumps(sample_violations))
        return 0
    
    with patch('tools.soak.continuous_runner.run_analyzer', side_effect=mock_analyzer):
        with patch('tools.soak.continuous_runner.send_telegram_message', return_value=True) as mock_telegram:
            metrics = run_single_cycle(args)
    
    # Check metrics
    assert metrics["verdict"] == "CRIT"
    assert metrics["windows"] == 24
    assert metrics["symbols"] == 2
    assert metrics["crit"] == 2
    assert metrics["warn"] == 1
    assert metrics["ok"] == 1
    
    # Check that telegram alert was sent
    assert mock_telegram.call_count == 1


def test_main_max_iterations_one(tmp_path, monkeypatch, capsys):
    """Test main() with max_iterations=1."""
    from tools.soak.continuous_runner import main
    
    # Mock args
    monkeypatch.setattr(sys, 'argv', [
        'continuous_runner.py',
        '--iter-glob', 'artifacts/soak/latest/ITER_SUMMARY_*.json',
        '--min-windows', '24',
        '--max-iterations', '1',
        '--interval-min', '0',
        '--env', 'dev',
        '--exchange', 'bybit',
        '--redis-url', 'redis://localhost:6379/0',
        '--lock-file', str(tmp_path / 'test.lock'),
        '--dry-run'
    ])
    
    # Mock run_single_cycle to return quickly
    with patch('tools.soak.continuous_runner.run_single_cycle', return_value={"verdict": "OK"}):
        exit_code = main()
    
    assert exit_code == 0
    
    captured = capsys.readouterr()
    assert "=== Cycle 1 ===" in captured.out
    assert "Reached max iterations (1)" in captured.out


def test_main_lock_already_held(tmp_path, monkeypatch, capsys):
    """Test main() exits when lock is already held."""
    from tools.soak.continuous_runner import main
    
    lock_file = tmp_path / 'test.lock'
    
    # Pre-create lock
    lock_file.write_text("99999")
    
    # Mock args
    monkeypatch.setattr(sys, 'argv', [
        'continuous_runner.py',
        '--iter-glob', 'artifacts/soak/latest/ITER_SUMMARY_*.json',
        '--min-windows', '24',
        '--max-iterations', '1',
        '--lock-file', str(lock_file),
        '--dry-run'
    ])
    
    exit_code = main()
    
    assert exit_code == 1
    
    captured = capsys.readouterr()
    assert "Failed to acquire lock" in captured.out or "Lock already held" in captured.out

