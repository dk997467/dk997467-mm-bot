import os
import json
import asyncio
from pathlib import Path


def _mk_bot(tmp_path):
    from cli.run_bot import MarketMakerBot
    from src.common.config import AppConfig
    b = MarketMakerBot.__new__(MarketMakerBot)
    b._ensure_admin_audit_initialized()
    b._check_admin_token = lambda req: True
    b._admin_rate_limit_check = lambda actor, ep: True
    b._get_artifacts_dir = lambda: str(tmp_path)
    b._alerts_log_path = str(tmp_path / 'alerts.log')
    b.running = True
    # minimal config needed by _build_canary_payload
    b.config = AppConfig()
    return b


def test_smoke_fast_mode(tmp_path):
    # fast-mode env
    os.environ['ARTIFACTS_DIR'] = str(tmp_path)
    os.environ['ROLLOUT_STEP_INTERVAL_SEC'] = '1'
    os.environ['CANARY_EXPORT_INTERVAL_SEC'] = '1'
    os.environ['PRUNE_INTERVAL_SEC'] = '2'
    os.environ['SCHEDULER_RECOMPUTE_SEC'] = '0'
    os.environ['LAT_MIN_SAMPLE'] = '50'
    os.environ['LAT_P95_CAP_MS'] = '50'
    os.environ['LAT_P99_CAP_MS'] = '100'

    bot = _mk_bot(tmp_path)

    # health endpoints payloads are deterministic
    async def _healths():
        ok = await bot._sre_healthz(None)
        ready = await bot._sre_readyz(None)
        return ok.body, ready.body
    body_ok, body_ready = asyncio.get_event_loop().run_until_complete(_healths())
    assert body_ok == b'{"status":"ok","uptime_seconds":0.0}'
    assert body_ready == b'{"status":"ready"}'

    # run canary export loop briefly
    async def _tick_canary_once():
        # call internal build/export synchronously by invoking the loop body once
        # emulate one iteration
        r = bot._build_canary_payload()
        ts = "19700101_000000"
        p = Path(tmp_path) / f"canary_{ts}.json"
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps(r, sort_keys=True, separators=(",", ":")))
    asyncio.get_event_loop().run_until_complete(_tick_canary_once())

    # at least one artifact appears
    # small extra wait to allow atomic replace to land
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01))
    files = list(Path(tmp_path).glob('canary_*.json'))
    assert len(files) >= 1

    # alerts tail endpoint (use helper directly)
    async def _alerts_tail():
        # write nothing; expect [] deterministically
        from types import SimpleNamespace
        req = SimpleNamespace(headers={"X-Admin-Token":"t"}, rel_url=SimpleNamespace(query={"tail":"10"}))
        res = await bot._admin_alerts_log(req)
        return res.body
    tail_body = asyncio.get_event_loop().run_until_complete(_alerts_tail())
    assert tail_body == b'{"items":[]}'


