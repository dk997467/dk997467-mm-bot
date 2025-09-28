def test_gate_canary_deltas_fail():
    from src.deploy.gate import evaluate
    from src.deploy.thresholds import GateThresholds
    # reject delta
    wf = {
        "champion": {"aggregates": {"hit_rate_mean": 1.0, "maker_share_mean": 1.0, "net_pnl_mean_usd": 1.0, "cvar95_mean_usd": -1.0, "win_ratio": 1.0}},
        "metadata": {"created_at_utc": "2024-01-01T00:00:00Z"},
        "canary": {"killswitch_fired": False, "drift_alert": False, "fills_blue": 1000, "fills_green": 1000, "rejects_blue": 0, "rejects_green": 50, "latency_ms_avg_blue": 10.0, "latency_ms_avg_green": 10.0}
    }
    ok, reasons, metrics = evaluate(wf, GateThresholds())
    assert ok is False
    assert any('canary:reject_delta_exceeds' in r for r in reasons)
    # latency delta
    wf['canary'].update({"rejects_green": 0, "latency_ms_avg_blue": 10.0, "latency_ms_avg_green": 200.0})
    ok, reasons, metrics = evaluate(wf, GateThresholds())
    assert ok is False
    assert any('canary:latency_delta_exceeds' in r for r in reasons)

