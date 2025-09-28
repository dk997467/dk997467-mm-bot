from src.deploy.gate import evaluate, GateThresholds
from src.deploy.thresholds import CANARY_GATE


def test_slo_tail_p99_breach_triggers_last_reason():
    CANARY_GATE['slo_tail_min_sample'] = 50
    CANARY_GATE['slo_tail_p99_cap_ms'] = 150
    thr = GateThresholds(min_hit_rate=0.0, min_maker_share=0.0, min_net_pnl_usd=0.0, max_cvar95_loss_usd=1e9, min_splits_win_ratio=0.0, max_report_age_hours=1e9)
    wf = {"symbol":"BTCUSDT","metadata":{"created_at_utc":"1970-01-01T00:00:00Z"},"canary":{
        "fills_blue":600,"fills_green":600,
        "rejects_blue":0,"rejects_green":0,
        "latency_ms_avg_blue":10.0,"latency_ms_avg_green":10.0,
        "latency_ms_p95_blue":20.0,"latency_ms_p95_green":25.0,
        "latency_ms_p99_blue":140.0,"latency_ms_p99_green":200.0,
        "latency_samples_blue":200,"latency_samples_green":200
    }}
    ok, reasons, _ = evaluate(wf, thr)
    assert ok is False
    assert reasons[-1].endswith('slo_tail_p99_breach')


