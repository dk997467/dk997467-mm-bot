import io
import time
from contextlib import redirect_stdout

from scripts.smoke_f2 import run_mock_server, metrics_ticker, STATE
from src.deploy.rollout import monitor_metrics
from src.deploy.thresholds import GateThresholds


def test_smoke_promote_pass(monkeypatch):
    server = run_mock_server(18081)
    STATE['ticks'] = 0
    t = metrics_ticker
    th = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    # start ticker in promote mode
    import threading
    thrd = threading.Thread(target=t, args=("promote",), daemon=True)
    thrd.start()
    # Wait a couple of ticks
    time.sleep(7.0)
    ok, reasons, stats = monitor_metrics("http://127.0.0.1:18081/metrics", minutes=0.05, thresholds=th, poll_sec=0)
    assert ok is True


def test_smoke_rollback_fail(monkeypatch):
    server = run_mock_server(18082)
    STATE['ticks'] = 0
    import threading
    thrd = threading.Thread(target=metrics_ticker, args=("rollback",), daemon=True)
    thrd.start()
    # Wait enough ticks to trigger bursts
    time.sleep(10.0)
    th = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    ok, reasons, stats = monitor_metrics("http://127.0.0.1:18082/metrics", minutes=0.05, thresholds=th, poll_sec=0)
    assert ok is False
    assert len(reasons) >= 1

