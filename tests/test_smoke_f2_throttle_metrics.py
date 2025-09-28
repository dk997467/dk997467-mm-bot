import time
from scripts.smoke_f2 import run_mock_server, metrics_ticker
from urllib.request import urlopen


def _fetch_metrics(port):
    data = urlopen(f"http://127.0.0.1:{port}/metrics").read().decode("utf-8")
    lines = [l.strip() for l in data.splitlines() if l.strip() and not l.startswith('#')]
    d = {}
    for ln in lines:
        parts = ln.split()
        if len(parts) >= 2:
            try:
                d[parts[0]] = float(parts[1])
            except Exception:
                continue
    return d


def test_smoke_metrics_promote():
    port = 18083
    run_mock_server(port)
    import threading
    threading.Thread(target=metrics_ticker, args=("promote",), daemon=True).start()
    time.sleep(3.5)
    mm = _fetch_metrics(port)
    assert 'throttle_backoff_ms_max' in mm
    assert 'throttle_events_in_window_total' in mm


def test_smoke_metrics_rollback():
    port = 18084
    run_mock_server(port)
    import threading
    threading.Thread(target=metrics_ticker, args=("rollback",), daemon=True).start()
    time.sleep(10.5)
    mm = _fetch_metrics(port)
    # Expect backoff to ramp
    # In smoke we clamp at server state; allow >= 1000 to mark ramp
    assert mm.get('throttle_backoff_ms_max', 0) >= 1000

