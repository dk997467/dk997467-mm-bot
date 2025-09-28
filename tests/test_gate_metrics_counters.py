from datetime import datetime, timezone

from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds, THROTTLE_GLOBAL, THROTTLE_PER_SYMBOL
from src.metrics import exporter as mexp


def _nowz():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_gate_metrics_counters_pass_and_fail():
    # Reset counters
    if hasattr(mexp, "_reset_f2_gate_metrics_for_tests"):
        mexp._reset_f2_gate_metrics_for_tests()

    THROTTLE_GLOBAL.clear()
    THROTTLE_GLOBAL.update({"max_throttle_backoff_ms": 1000, "max_throttle_events_in_window_total": 100})
    THROTTLE_PER_SYMBOL.clear()

    ok_aggregates = {"hit_rate_mean": 0.5, "maker_share_mean": 0.95, "net_pnl_mean_usd": 0.0, "cvar95_mean_usd": -1.0, "win_ratio": 0.8}

    # PASS case
    wf_pass = {
        "symbol": "BTCUSDT",
        "metadata": {"generated_at_utc": _nowz()},
        "champion": {"aggregates": ok_aggregates},
        "audit": {"throttle_backoff_ms_max": 10, "throttle_events_in_window": {"total": 5}, "autopolicy_level": 0},
    }
    ok1, _, _ = evaluate(wf_pass, GateThresholds())
    assert ok1 is True

    snap1 = mexp._get_f2_gate_metrics_snapshot_for_tests()
    assert snap1["pass"].get("BTCUSDT", 0) == 1

    # FAIL due to backoff
    wf_fail_b = {
        "symbol": "BTCUSDT",
        "metadata": {"generated_at_utc": _nowz()},
        "champion": {"aggregates": ok_aggregates},
        "audit": {"throttle_backoff_ms_max": 2000, "throttle_events_in_window": {"total": 5}, "autopolicy_level": 0},
    }
    ok2, reasons2, _ = evaluate(wf_fail_b, GateThresholds())
    assert ok2 is False
    assert any("Throttle backoff too high" in r for r in reasons2)

    # FAIL due to events
    wf_fail_e = {
        "symbol": "BTCUSDT",
        "metadata": {"generated_at_utc": _nowz()},
        "champion": {"aggregates": ok_aggregates},
        "audit": {"throttle_backoff_ms_max": 10, "throttle_events_in_window": {"total": 1000}, "autopolicy_level": 0},
    }
    ok3, reasons3, _ = evaluate(wf_fail_e, GateThresholds())
    assert ok3 is False
    assert any("Throttle events in window too high" in r for r in reasons3)

    snap2 = mexp._get_f2_gate_metrics_snapshot_for_tests()
    assert snap2["fail"].get(("BTCUSDT", "backoff"), 0) >= 1
    assert snap2["fail"].get(("BTCUSDT", "events"), 0) >= 1

