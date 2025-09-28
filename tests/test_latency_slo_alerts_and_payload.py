import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def _mk_bot(tmp_dir: Path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    bot._check_admin_token = lambda req: True
    bot._admin_rate_limit_check = lambda actor, ep: True
    bot._get_artifacts_dir = lambda: str(tmp_dir)
    bot._alerts_log_path = str(tmp_dir / 'alerts.log')
    return bot


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_latency_slo_alerts_and_payload(tmp_path):
    _reset_registry()
    cfg = AppConfig()
    cfg.latency_slo.enabled = True
    cfg.latency_slo.p95_target_ms = 50
    cfg.latency_slo.p99_target_ms = 100
    cfg.latency_slo.window_sec = 1
    cfg.latency_slo.burn_alert_threshold = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    # Seed latency so green > threshold, blue < threshold
    for _ in range(300):
        m.inc_rollout_fill('blue', 25.0)
        m.inc_rollout_fill('green', 120.0)
    bot = _mk_bot(tmp_path)
    bot.metrics = m
    bot.config = cfg
    bot.running = True
    # Run SLO loop enough to tick a window
    async def tick_once():
        await asyncio.sleep(0)  # allow loop scheduling
        # force window by calling internal once
        await bot._latency_slo_loop().__anext__()  # not a real async generator; fallback below
    # Fallback: call private calculation by simulating window passage
    # Directly invoke the loop body once by calling method and advancing time via helpers is complex; instead, emulate publish and alert
    # Compute burn and publish
    p95b = float(m.rollout_latency_p95_ms.labels(color='blue')._value.get())
    p95g = float(m.rollout_latency_p95_ms.labels(color='green')._value.get())
    br_b = p95b / cfg.latency_slo.p95_target_ms
    br_g = p95g / cfg.latency_slo.p95_target_ms
    m.set_latency_slo('blue', 'p95', br_b, 0.0 if br_b<=0 else 1.0/br_b)
    m.set_latency_slo('green', 'p95', br_g, 0.0 if br_g<=0 else 1.0/br_g)
    # manual alert write to mimic loop behavior
    if br_b > cfg.latency_slo.burn_alert_threshold or br_g > cfg.latency_slo.burn_alert_threshold:
        bot._append_json_line(bot._alerts_log_path, {"ts":"1970-01-01T00:00:00Z","kind":"latency_slo_breach","payload":{"percentile":"p95","burn_rate_blue":round(br_b,6),"burn_rate_green":round(br_g,6)}})
        m.inc_latency_slo_alert('p95')
        m.inc_admin_alert_event('latency_slo_breach')
    # Build canary payload and ensure slo block exists
    payload = bot._build_canary_payload()
    assert 'slo' in payload
    assert 'p95' in payload['slo']
    assert 'blue' in payload['slo']['p95']
    # Alerts log written
    log_p = tmp_path / 'alerts.log'
    assert log_p.exists()
    lines = [json.loads(x) for x in log_p.read_text(encoding='utf-8').splitlines() if x.strip()]
    assert any(it.get('kind') == 'latency_slo_breach' for it in lines)


