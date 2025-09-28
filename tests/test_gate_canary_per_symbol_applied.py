import os
import tempfile

from src.deploy.thresholds import refresh_thresholds, GateThresholds
from src.deploy.gate import evaluate


def _write_yaml(tmp_path: str, content: str) -> str:
    p = os.path.join(tmp_path, "thresholds_gate.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_gate_canary_per_symbol_applied_first_reason_order():
    d = tempfile.mkdtemp()
    try:
        # Global lenient, per-symbol strict -> should fail by per-symbol thresholds
        yaml_text = (
            "canary_gate:\n"
            "  max_reject_delta: 0.05\n"
            "  max_latency_delta_ms: 200\n"
            "  min_sample_fills: 100\n"
            "  drift_cap_pct: 10\n"
            "canary_gate_per_symbol:\n"
            "  BTCUSDT:\n"
            "    max_reject_delta: 0.01\n"
            "    max_latency_delta_ms: 30\n"
            "    min_sample_fills: 100\n"
            "    drift_cap_pct: 5\n"
        )
        path = _write_yaml(d, yaml_text)
        summary = refresh_thresholds(path)

        # Build canary that violates reject_delta only by strict threshold
        # Blue rr ~ 1%, Green rr ~ 13% → delta ~ 12% > 0.01 strict
        canary = {
            "killswitch_fired": False,
            "drift_alert": False,
            "fills_blue": 2000,
            "fills_green": 700,
            "rejects_blue": 20,
            "rejects_green": 140,
            "latency_ms_avg_blue": 25.0,
            "latency_ms_avg_green": 25.0,
        }
        ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
        assert ok is False
        # Deterministic order: killswitch > drift > reject > latency; here expect reject_delta_exceeds
        assert metrics.get("canary_gate_reasons", [None])[0] == "reject_delta_exceeds"
        used = metrics.get("canary_gate_thresholds_used", {})
        assert used.get("max_reject_delta") == 0.01
    finally:
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


