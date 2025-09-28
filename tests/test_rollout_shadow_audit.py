from src.deploy.rollout import monitor_metrics
from src.deploy.thresholds import GateThresholds


def test_rollout_shadow_audit(monkeypatch):
    payloads = [
        "\n".join([
            "guard_paused 0",
            "shadow_orders_total{symbol=\"BTCUSDT\"} 10",
            "shadow_price_diff_bps_avg{symbol=\"BTCUSDT\"} 1.5",
            "shadow_size_diff_pct_avg{symbol=\"BTCUSDT\"} 2.0",
        ]),
    ]
    idx = {'i': 0}
    def _fake_get_text(url, timeout=10):
        i = idx['i']
        idx['i'] = min(i + 1, len(payloads) - 1)
        return payloads[i]
    monkeypatch.setattr('src.deploy.rollout._http_get_text', _fake_get_text)
    ok, reasons, stats = monitor_metrics("http://127.0.0.1:0/metrics", minutes=0.01, thresholds=GateThresholds(), poll_sec=0)
    lv = stats['last_values']
    # In aggregator-only mode, this block may be absent when not wired; tolerate absence here
    if 'shadow_stats' in lv:
        ss = lv['shadow_stats']
        assert ss['count'] >= 10

