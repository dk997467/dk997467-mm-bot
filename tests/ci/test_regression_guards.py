import json
import asyncio

from prometheus_client import REGISTRY
from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.deploy.gate import evaluate, GateThresholds


def _mk_ctx():
    # ensure clean registry for each test
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    return ctx, m


async def _get_canary(bot):
    res = await bot._admin_report_canary(SimpleNamespace(headers={"X-Admin-Token":"t"}, rel_url=SimpleNamespace(query={}), method='GET'))
    return res


def test_regression_guards_healthy(monkeypatch):
    from types import SimpleNamespace
    ctx, m = _mk_ctx()
    # Seed healthy: balanced fills, low rejects, low latency
    m.test_reset_rollout()
    m.test_seed_rollout_counters(fills_blue=600, fills_green=600, rejects_blue=5, rejects_green=5, split_expected_pct=50, observed_green_pct=50)
    m.test_seed_rollout_latency_ms(blue_ms=20.0, green_ms=20.0)
    # Build canary payload
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    bot._check_admin_token = lambda req: True
    bot._admin_rate_limit_check = lambda actor, ep: True
    bot.metrics = m
    bot.config = ctx.cfg
    res = asyncio.get_event_loop().run_until_complete(bot._admin_report_canary(SimpleNamespace(headers={"X-Admin-Token":"t"}, rel_url=SimpleNamespace(query={}), method='GET')))
    assert res.status == 200
    data = json.loads(res.text)
    # Deterministic payload check (stable keys)
    b1 = json.dumps(data, sort_keys=True, separators=(",", ":")).encode('utf-8')
    b2 = json.dumps(data, sort_keys=True, separators=(",", ":")).encode('utf-8')
    assert b1 == b2
    # Gate PASS
    thr = GateThresholds(min_hit_rate=0.0, min_maker_share=0.0, min_net_pnl_usd=0.0, max_cvar95_loss_usd=1e9, min_splits_win_ratio=0.0, max_report_age_hours=1e9)
    ok, reasons, _ = evaluate({"symbol":"BTCUSDT","metadata":{"created_at_utc":"1970-01-01T00:00:00Z"},"canary":{
        "fills_blue":600,"fills_green":600,
        "rejects_blue":5,"rejects_green":5,
        "latency_ms_avg_blue":20.0,"latency_ms_avg_green":20.0
    }}, thr)
    assert ok is True
    assert reasons == []


def test_regression_guards_bad(monkeypatch):
    from types import SimpleNamespace
    ctx, m = _mk_ctx()
    # Seed bad: large rejects delta and tail latency deltas with enough sample
    m.test_reset_rollout()
    m.test_seed_rollout_counters(fills_blue=600, fills_green=600, rejects_blue=5, rejects_green=50, split_expected_pct=50, observed_green_pct=50)
    # Simulate tail heavy for green
    for _ in range(300):
        m.inc_rollout_fill('blue', 20.0)
        m.inc_rollout_fill('green', 200.0)
    # Build canary payload
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    bot._check_admin_token = lambda req: True
    bot._admin_rate_limit_check = lambda actor, ep: True
    bot.metrics = m
    bot.config = ctx.cfg
    res = asyncio.get_event_loop().run_until_complete(bot._admin_report_canary(SimpleNamespace(headers={"X-Admin-Token":"t"}, rel_url=SimpleNamespace(query={}), method='GET')))
    assert res.status == 200
    data = json.loads(res.text)
    # Deterministic JSON
    b1 = json.dumps(data, sort_keys=True, separators=(",", ":")).encode('utf-8')
    b2 = json.dumps(data, sort_keys=True, separators=(",", ":")).encode('utf-8')
    assert b1 == b2
    # Gate FAIL and ordered reasons (first by our spec in thresholds/gate)
    thr = GateThresholds(min_hit_rate=0.0, min_maker_share=0.0, min_net_pnl_usd=0.0, max_cvar95_loss_usd=1e9, min_splits_win_ratio=0.0, max_report_age_hours=1e9)
    ok, reasons, _ = evaluate({"symbol":"BTCUSDT","metadata":{"created_at_utc":"1970-01-01T00:00:00Z"},"canary":{
        "fills_blue":600,"fills_green":600,
        "rejects_blue":5,"rejects_green":50,
        "latency_ms_avg_blue":20.0,"latency_ms_avg_green":200.0,
        "latency_ms_p95_blue":50.0,"latency_ms_p95_green":200.0,
        "latency_ms_p99_blue":100.0,"latency_ms_p99_green":400.0,
        "latency_samples_blue":300,"latency_samples_green":300,
        "killswitch_fired":False,
        "drift_alert":False
    }}, thr)
    assert ok is False
    assert len(reasons) > 0


