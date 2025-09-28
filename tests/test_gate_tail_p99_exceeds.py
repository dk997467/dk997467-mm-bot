from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def test_gate_tail_p99_exceeds_triggers_reason():
    canary = {
        "killswitch_fired": False,
        "drift_alert": False,
        "fills_blue": 1000,
        "fills_green": 1000,
        "rejects_blue": 10,
        "rejects_green": 10,
        "latency_ms_avg_blue": 20.0,
        "latency_ms_avg_green": 30.0,
        "latency_ms_p95_blue": 25.0,
        "latency_ms_p95_green": 40.0,
        "latency_ms_p99_blue": 30.0,
        "latency_ms_p99_green": 150.0,  # delta 120 > 100 cap
        "latency_samples_blue": 500,
        "latency_samples_green": 500,
    }
    ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
    cg = metrics.get("canary_gate_reasons", [])
    assert "latency_tail_p99_exceeds" in cg


