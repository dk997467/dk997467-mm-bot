from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def test_gate_tail_p95_exceeds_triggers_reason():
    # sufficient samples and p95 delta above cap
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
        "latency_ms_p95_green": 150.0,  # delta 125 > 50 cap
        "latency_ms_p99_blue": 30.0,
        "latency_ms_p99_green": 60.0,
        "latency_samples_blue": 500,
        "latency_samples_green": 500,
    }
    ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
    cg = metrics.get("canary_gate_reasons", [])
    # Order: existing reasons first; we only check presence of tail p95 reason
    assert "latency_tail_p95_exceeds" in cg


