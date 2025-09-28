import os
import json
import asyncio
from types import SimpleNamespace


async def _get_perf_snapshot(bot, headers):
    class Req:
        def __init__(self):
            self.headers = headers
            self.rel_url = SimpleNamespace(query={})
    res = await bot._admin_perf_snapshot(Req())
    assert res.status == 200
    return json.loads(res.body.decode())


def _median_from_buckets(bmap):
    # assume keys are bucket upper bounds as strings; pick 50% rank by cumulative
    try:
        items = sorted(((float(k if k != '+Inf' else '1e12'), int(v)) for k, v in bmap.items()), key=lambda x: x[0])
    except Exception:
        return 0.0
    total = sum(v for _, v in items)
    if total <= 0:
        return 0.0
    cum = 0
    half = (total + 1) // 2
    for ub, cnt in items:
        cum += cnt
        if cum >= half:
            return float(ub)
    return float(items[-1][0])


def test_perf_guardrails_fast_mode(monkeypatch):
    from cli.run_bot import MarketMakerBot
    # fast-mode envs
    os.environ['CANARY_EXPORT_INTERVAL_SEC'] = '1'
    os.environ['PRUNE_INTERVAL_SEC'] = '2'
    os.environ['ROLLOUT_STEP_INTERVAL_SEC'] = '1'

    # minimal bot stub with metrics and admin
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    # token ok, rate-limit ok
    bot._check_admin_token = lambda req: True
    bot._admin_rate_limit_check = lambda actor, ep: True
    from tests.e2e._utils import make_metrics_ctx
    m = make_metrics_ctx()
    bot.metrics = m

    loop = asyncio.new_event_loop()
    try:
        # simulate few ticks: record loop ticks for loops ramp/export/prune/slo
        for _ in range(4):
            for ln in ('ramp','export','prune','slo'):
                m.record_loop_tick(ln, 5.0)
        snap = loop.run_until_complete(_get_perf_snapshot(bot, {"X-Admin-Token":"t"}))
    finally:
        loop.close()

    # load baseline
    with open('tests/ci/perf_baseline.json','r',encoding='utf-8') as f:
        base = json.load(f)

    # guard 1: p95 loop ticks not worse than +25%
    problems = []
    for ln in ('ramp','export','prune','slo'):
        p95 = float(snap.get('loops',{}).get(ln,{}).get('p95_ms', 0.0))
        thr = float(base.get('loops',{}).get(ln,{}).get('p95_ms', 0.0)) * 1.25
        if p95 > thr:
            problems.append(f"loop {ln} p95_ms={p95:.3f} > thr={thr:.3f}")

    # guard 2: admin latency median not worse than +25%
    # pick '/admin/perf/snapshot' if present
    cur_b = snap.get('admin_latency_buckets',{}).get('/admin/perf/snapshot',{})
    base_b = base.get('admin_latency_buckets',{}).get('/admin/perf/snapshot',{})
    cur_med = _median_from_buckets(cur_b)
    base_med = _median_from_buckets(base_b)
    if cur_med > base_med * 1.25:
        problems.append(f"admin median={cur_med:.3f} > thr={base_med*1.25:.3f}")

    if problems:
        print("Perf guardrails failed:\n" + "\n".join(problems))
        assert False

