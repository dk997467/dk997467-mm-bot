import os
from tempfile import NamedTemporaryFile
from datetime import datetime, timezone

from src.deploy.thresholds import THROTTLE_GLOBAL, THROTTLE_PER_SYMBOL, refresh_thresholds, get_throttle_thresholds
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def _nowz():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_thresholds_hot_reload_yaml_and_gate_usage():
    THROTTLE_GLOBAL.clear()
    THROTTLE_GLOBAL.update({"max_throttle_backoff_ms": 5000, "max_throttle_events_in_window_total": 1000})
    THROTTLE_PER_SYMBOL.clear()

    yaml_text = (
        "throttle:\n"
        "  global:\n"
        "    max_throttle_backoff_ms: 111\n"
        "    max_throttle_events_in_window_total: 22\n"
        "  per_symbol:\n"
        "    ETHUSDT:\n"
        "      max_throttle_backoff_ms: 10\n"
        "      max_throttle_events_in_window_total: 5\n"
    )

    with NamedTemporaryFile("w", delete=False, suffix=".yaml") as f:
        f.write(yaml_text)
        path = f.name

    try:
        # Before reload, ETHUSDT should use global values (5000/1000)
        before = get_throttle_thresholds("ETHUSDT")
        assert before["max_throttle_backoff_ms"] != 10
        assert before["max_throttle_events_in_window_total"] != 5

        summary = refresh_thresholds(path)
        assert isinstance(summary, dict)
        assert summary.get("global_keys") == 2
        assert summary.get("per_symbol_count") == 1
        assert "ETHUSDT" in summary.get("symbols", [])

        after = get_throttle_thresholds("ETHUSDT")
        assert after["max_throttle_backoff_ms"] == 10
        assert after["max_throttle_events_in_window_total"] == 5

        # Gate should now use the refreshed thresholds and fail on both
        ok_aggregates = {"hit_rate_mean": 0.5, "maker_share_mean": 0.95, "net_pnl_mean_usd": 0.0, "cvar95_mean_usd": -1.0, "win_ratio": 0.8}
        wf = {
            "symbol": "ETHUSDT",
            "metadata": {"generated_at_utc": _nowz()},
            "champion": {"aggregates": ok_aggregates},
            "audit": {
                "throttle_backoff_ms_max": 15,
                "throttle_events_in_window": {"total": 6},
                "autopolicy_level": 0,
            },
        }
        ok, reasons, metrics = evaluate(wf, GateThresholds())
        assert ok is False
        assert any("Throttle backoff too high" in r for r in reasons)
        assert any("Throttle events in window too high" in r for r in reasons)
        assert metrics.get("throttle_thresholds_used", {}).get("max_throttle_backoff_ms") == 10
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass

