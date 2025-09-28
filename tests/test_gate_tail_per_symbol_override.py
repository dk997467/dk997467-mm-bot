import os
import tempfile

from src.deploy.thresholds import refresh_thresholds, GateThresholds
from src.deploy.gate import evaluate


def _write_yaml(tmp_path: str, content: str) -> str:
    p = os.path.join(tmp_path, "thr_tail.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_gate_tail_per_symbol_override_changes_outcome():
    d = tempfile.mkdtemp()
    try:
        yaml_text = (
            "canary_gate:\n"
            "  tail_min_sample: 200\n"
            "  tail_p95_cap_ms: 200\n"  # lenient globally
            "  tail_p99_cap_ms: 200\n"
            "canary_gate_per_symbol:\n"
            "  BTCUSDT:\n"
            "    tail_min_sample: 100\n"
            "    tail_p95_cap_ms: 50\n"  # strict for symbol
            "    tail_p99_cap_ms: 100\n"
        )
        path = _write_yaml(d, yaml_text)
        summary = refresh_thresholds(path)

        # Build canary with p95 delta 120ms and sufficient samples
        canary = {
            "killswitch_fired": False,
            "drift_alert": False,
            "fills_blue": 1000,
            "fills_green": 1000,
            "rejects_blue": 10,
            "rejects_green": 10,
            "latency_ms_avg_blue": 20.0,
            "latency_ms_avg_green": 25.0,
            "latency_ms_p95_blue": 25.0,
            "latency_ms_p95_green": 145.0,
            "latency_ms_p99_blue": 30.0,
            "latency_ms_p99_green": 80.0,
            "latency_samples_blue": 1000,
            "latency_samples_green": 1000,
        }
        ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
        cg = metrics.get("canary_gate_reasons", [])
        # Globally cap is 200; per-symbol 50 -> should fire p95 tail reason
        assert "latency_tail_p95_exceeds" in cg
        used = metrics.get("canary_gate_thresholds_used", {})
        assert used.get("tail_p95_cap_ms") == 50
        assert used.get("tail_min_sample") == 100
    finally:
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


