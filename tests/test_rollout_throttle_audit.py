import io
from contextlib import redirect_stdout

from src.deploy.rollout import monitor_metrics
from src.deploy.thresholds import GateThresholds


def test_rollout_throttle_audit_defaults(monkeypatch):
    payloads = [
        "guard_paused 0\n",  # no throttle metrics present
        "guard_paused 0\n",
    ]
    idx = {'i': 0}

    def _fake_get_text(url, timeout=10):
        i = idx['i']
        idx['i'] = min(i + 1, len(payloads) - 1)
        return payloads[i]

    monkeypatch.setattr('src.deploy.rollout._http_get_text', _fake_get_text)

    buf = io.StringIO()
    with redirect_stdout(buf):
        ok, reasons, stats = monitor_metrics("http://x/metrics", minutes=0.01, thresholds=GateThresholds(), poll_sec=0)
    assert 'throttle_backoff_ms_max' in stats
    assert 'throttle_events_in_window' in stats


def test_rollout_throttle_audit_with_metrics(monkeypatch):
    payloads = [
        "\n".join([
            "guard_paused 0",
            "throttle_backoff_ms 1200",
            "throttle_events_in_window{op=\"create\",symbol=\"BTCUSDT\"} 3",
            "throttle_events_in_window{op=\"cancel\",symbol=\"BTCUSDT\"} 2",
        ]),
        "\n".join([
            "guard_paused 0",
            "throttle_backoff_ms 1500",
            "throttle_events_in_window{op=\"create\",symbol=\"BTCUSDT\"} 4",
        ]),
    ]
    idx = {'i': 0}

    def _fake_get_text(url, timeout=10):
        i = idx['i']
        idx['i'] = min(i + 1, len(payloads) - 1)
        return payloads[i]

    monkeypatch.setattr('src.deploy.rollout._http_get_text', _fake_get_text)

    ok, reasons, stats = monitor_metrics("http://x/metrics", minutes=0.01, thresholds=GateThresholds(), poll_sec=0)
    lv = stats['last_values']
    assert lv['throttle_backoff_ms_max'] >= 1500
    ev = lv['throttle_events_in_window']
    assert ev['total'] >= 4
    assert 'create' in ev

