from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds, refresh_thresholds


def test_gate_tail_min_sample_guard_no_tail_reasons():
    # global thresholds default tail_min_sample=200; provide small samples
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
        "latency_ms_p95_green": 120.0,  # large delta but samples small
        "latency_ms_p99_blue": 30.0,
        "latency_ms_p99_green": 200.0,
        "latency_samples_blue": 50,
        "latency_samples_green": 60,
    }
    ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
    cg = metrics.get("canary_gate_reasons", [])
    # Tail reasons should be absent due to min-sample guard
    assert "latency_tail_p95_exceeds" not in cg
    assert "latency_tail_p99_exceeds" not in cg


