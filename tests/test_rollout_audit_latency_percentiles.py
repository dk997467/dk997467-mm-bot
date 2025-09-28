from types import SimpleNamespace
import asyncio
import json
from prometheus_client import REGISTRY
from cli.run_bot import MarketMakerBot
from src.metrics.exporter import Metrics


class _Req:
    def __init__(self):
        self.headers = {"X-Admin-Token": "t"}
        self.rel_url = SimpleNamespace(path="/admin/report/canary", query={})


def _reset_registry():
    try:
        collectors = list(REGISTRY._collector_to_names.keys())  # type: ignore[attr-defined]
        for col in collectors:
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


async def _build_canary(bot):
    req = _Req()
    return await bot._admin_report_canary(req)


def test_rollout_audit_latency_percentiles_present():
    _reset_registry()
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._check_admin_token = lambda _req: True  # bypass auth
    bot.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=50, salt="s", blue={}, green={}), rollout_ramp=SimpleNamespace(enabled=True))
    bot._build_time_iso = "2024-01-01T00:00:00Z"
    # metrics with some latencies
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                levels_per_side=1,
                min_time_in_book_ms=0,
                k_vola_spread=0.0,
                skew_coeff=0.0,
                imbalance_cutoff=0.0,
            ),
            limits=SimpleNamespace(max_create_per_sec=0, max_cancel_per_sec=0),
        )
    )
    m = Metrics(ctx)
    m.test_reset_rollout()
    m.test_reset_latency()
    # seed fills with latency
    for v in [10.0, 15.0, 20.0, 25.0, 30.0]:
        m.inc_rollout_fill('blue', v)
        m.inc_rollout_fill('green', v + 5.0)
    bot.metrics = m

    async def go():
        resp = await _build_canary(bot)
        data = json.loads(resp.body.decode())
        r = data.get("rollout", {})
        assert "latency_ms_p95_blue" in r and "latency_ms_p99_blue" in r
        assert "latency_ms_p95_green" in r and "latency_ms_p99_green" in r
        # sanity values non-negative
        assert r["latency_ms_p95_blue"] >= 0.0 and r["latency_ms_p99_green"] >= 0.0
    asyncio.run(go())
