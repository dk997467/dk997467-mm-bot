from src.deploy.gate import evaluate, GateThresholds


def test_slo_tail_min_sample_guard():
    thr = GateThresholds(min_hit_rate=0.0, min_maker_share=0.0, min_net_pnl_usd=0.0, max_cvar95_loss_usd=1e9, min_splits_win_ratio=0.0, max_report_age_hours=1e9)
    wf = {"symbol":"BTCUSDT","metadata":{"created_at_utc":"1970-01-01T00:00:00Z"},"canary":{
        "fills_blue":600,"fills_green":600,
        "rejects_blue":0,"rejects_green":0,
        "latency_ms_avg_blue":10.0,"latency_ms_avg_green":10.0,
        "latency_ms_p95_blue":40.0,"latency_ms_p95_green":200.0,
        "latency_ms_p99_blue":80.0,"latency_ms_p99_green":400.0,
        "latency_samples_blue":100,"latency_samples_green":100
    }}
    ok, reasons, metrics = evaluate(wf, thr)
    # With default slo_tail_min_sample=200, no slo_tail_* reasons should appear
    assert all(not r.endswith('slo_tail_p95_breach') and not r.endswith('slo_tail_p99_breach') for r in reasons)


