import os
import tempfile

from src.deploy.thresholds import refresh_thresholds, GateThresholds
from src.deploy.gate import evaluate


def _write_yaml(tmp_path: str, content: str) -> str:
    p = os.path.join(tmp_path, "thresholds.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_canary_thresholds_symbol_override_applied():
    d = tempfile.mkdtemp()
    try:
        yaml_text = (
            "canary_gate:\n"
            "  max_reject_delta: 0.02\n"
            "  max_latency_delta_ms: 50\n"
            "  min_sample_fills: 200\n"
            "  drift_cap_pct: 5\n"
            "canary_gate_per_symbol:\n"
            "  BTCUSDT:\n"
            "    max_reject_delta: 0.01\n"
            "    max_latency_delta_ms: 30\n"
            "    min_sample_fills: 300\n"
            "    drift_cap_pct: 3\n"
        )
        path = _write_yaml(d, yaml_text)
        summary = refresh_thresholds(path)
        assert summary["canary_gate"]["max_latency_delta_ms"] == 50
        assert summary["canary_gate_per_symbol"]["BTCUSDT"]["max_latency_delta_ms"] == 30

        # Build minimal canary report and evaluate for btcusdt (lowercase to test normalization)
        canary = {
            "killswitch_fired": False,
            "drift_alert": False,
            "fills_blue": 300,
            "fills_green": 300,
            "rejects_blue": 0,
            "rejects_green": 0,
            "latency_ms_avg_blue": 0.0,
            "latency_ms_avg_green": 0.0,
        }
        ok, reasons, metrics = evaluate(wf_report={"symbol": "btcusdt", "canary": canary}, thresholds=GateThresholds())
        used = metrics.get("canary_gate_thresholds_used", {})
        assert used.get("max_reject_delta") == 0.01
        assert used.get("max_latency_delta_ms") == 30
        assert used.get("min_sample_fills") == 300
        assert used.get("drift_cap_pct") == 3.0
    finally:
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


