from datetime import datetime, timezone
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def _wf(audit):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "champion": {
            "aggregates": {
                "hit_rate_mean": 0.5,
                "maker_share_mean": 0.95,
                "net_pnl_mean_usd": 1.0,
                "cvar95_mean_usd": -1.0,
                "win_ratio": 0.8,
            }
        },
        "metadata": {"report_utc": now_iso},
        "audit": audit,
    }


def test_gate_throttle_pass():
    thr = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    audit = {"throttle_backoff_ms_max": 3000.0, "throttle_events_in_window": {"total": 40}}
    ok, reasons, metrics = evaluate(_wf(audit), thr)
    assert ok is True
    assert reasons == []


def test_gate_throttle_fail_backoff():
    thr = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    audit = {"throttle_backoff_ms_max": 6000.0, "throttle_events_in_window": {"total": 10}}
    ok, reasons, metrics = evaluate(_wf(audit), thr)
    assert ok is False
    assert any("Throttle backoff too high" in r for r in reasons)


def test_gate_throttle_fail_events():
    thr = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    audit = {"throttle_backoff_ms_max": 1000.0, "throttle_events_in_window": {"total": 60}}
    ok, reasons, metrics = evaluate(_wf(audit), thr)
    assert ok is False
    assert any("Throttle events in window too high" in r for r in reasons)


def test_gate_throttle_missing_fields():
    thr = GateThresholds(max_throttle_backoff_ms=5000.0, max_throttle_events_in_window_total=50)
    audit = {}
    ok, reasons, metrics = evaluate(_wf(audit), thr)
    assert ok is True
    assert reasons == []

