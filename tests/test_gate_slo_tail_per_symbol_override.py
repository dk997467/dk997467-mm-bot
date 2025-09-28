from src.deploy.gate import evaluate, GateThresholds
from src.deploy.thresholds import CANARY_GATE_PER_SYMBOL


def test_slo_tail_per_symbol_override_applies():
    CANARY_GATE_PER_SYMBOL['BTCUSDT'] = {
        'slo_tail_min_sample': 50,
        'slo_tail_p95_cap_ms': 10,
        'slo_tail_p99_cap_ms': 20,
    }
    thr = GateThresholds(min_hit_rate=0.0, min_maker_share=0.0, min_net_pnl_usd=0.0, max_cvar95_loss_usd=1e9, min_splits_win_ratio=0.0, max_report_age_hours=1e9)
    wf = {"symbol":"btcusdt","metadata":{"created_at_utc":"1970-01-01T00:00:00Z"},"canary":{
        "fills_blue":600,"fills_green":600,
        "rejects_blue":0,"rejects_green":0,
        "latency_ms_avg_blue":10.0,"latency_ms_avg_green":10.0,
        "latency_ms_p95_blue":9.0,"latency_ms_p95_green":15.0,
        "latency_ms_p99_blue":19.0,"latency_ms_p99_green":30.0,
        "latency_samples_blue":200,"latency_samples_green":200
    }}
    ok, reasons, _ = evaluate(wf, thr)
    assert ok is False
    # both slo_tail_p95 and p99 should breach under overrides
    assert any(r.endswith('slo_tail_p95_breach') for r in reasons)
    assert any(r.endswith('slo_tail_p99_breach') for r in reasons)


