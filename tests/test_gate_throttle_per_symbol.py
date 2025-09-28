from src.deploy.thresholds import THROTTLE_GLOBAL, THROTTLE_PER_SYMBOL
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def test_gate_throttle_per_symbol_overrides():
    # Setup global lax thresholds
    THROTTLE_GLOBAL.clear()
    THROTTLE_GLOBAL.update({"max_throttle_backoff_ms": 5000, "max_throttle_events_in_window_total": 1000})
    # Per-symbol strict for BTCUSDT
    THROTTLE_PER_SYMBOL.clear()
    THROTTLE_PER_SYMBOL.update({"BTCUSDT": {"max_throttle_backoff_ms": 100, "max_throttle_events_in_window_total": 10}})

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    ok_aggregates = {"hit_rate_mean": 0.5, "maker_share_mean": 0.95, "net_pnl_mean_usd": 0.0, "cvar95_mean_usd": -1.0, "win_ratio": 0.8}
    wf = {"symbol": "BTCUSDT", "metadata": {"generated_at_utc": now}, "champion": {"aggregates": ok_aggregates}, "audit": {"throttle_backoff_ms_max": 200, "throttle_events_in_window": {"total": 20}}}
    ok, reasons, metrics = evaluate(wf, GateThresholds())
    assert ok is False
    assert any("Throttle backoff too high" in r for r in reasons)
    assert any("Throttle events in window too high" in r for r in reasons)
    assert metrics.get('throttle_thresholds_used', {}).get('max_throttle_backoff_ms') == 100

    wf2 = {"symbol": "ETHUSDT", "metadata": {"generated_at_utc": now}, "champion": {"aggregates": ok_aggregates}, "audit": {"throttle_backoff_ms_max": 200, "throttle_events_in_window": {"total": 20}}}
    ok2, reasons2, metrics2 = evaluate(wf2, GateThresholds())
    assert ok2 is True


def test_gate_throttle_per_symbol_invalid_override():
    THROTTLE_PER_SYMBOL.clear()
    THROTTLE_PER_SYMBOL.update({"BAD": {"max_throttle_backoff_ms": -1}})
    wf = {"symbol": "BAD", "champion": {"aggregates": {}}, "audit": {"throttle_backoff_ms_max": 0, "throttle_events_in_window": {"total": 0}}}
    raised = False
    try:
        evaluate(wf, GateThresholds())
    except ValueError:
        raised = True
    assert raised


