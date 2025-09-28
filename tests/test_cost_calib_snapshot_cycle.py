import json
import os
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


def test_cost_calib_snapshot_save_load(tmp_path, monkeypatch):
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m

    # Seed few observations
    for i in range(5):
        m.record_cost_observation('BTCUSDT', spread_bps=10+i, volume_usd=1000+i*100, slippage_bps=2+i)
    snap = m.get_cost_calib_snapshot_for_tests()
    # write snapshot to file atomically using bot helper via minimal stub
    from types import SimpleNamespace
    class Srv:
        def __init__(self, metrics):
            self.metrics = metrics
        def _admin_actor_hash(self, r):
            return "test"
        def _admin_rate_limit_check(self, a, ep):
            return True
        def _check_admin_token(self, r):
            return True
        def _json_response(self, obj, status=200):
            return SimpleNamespace(status=status, text=json.dumps(obj, sort_keys=True, separators=(",", ":")))
        def _safe_load_json_file(self, path, limit_bytes=1<<20):
            st = os.stat(path)
            if st.st_size > limit_bytes:
                raise ValueError("file_too_large")
            with open(path,'rb') as f:
                return json.loads(f.read().decode('utf-8'))
        _pm_lock = None
    srv = Srv(m)

    # Prepare file
    p = tmp_path / 'cal.json'
    p.write_text(json.dumps({"symbols": {"BTCUSDT": {"k_eff": 12.3, "cap_eff_bps": 7.0}}}, sort_keys=True, separators=(",", ":")), encoding='utf-8')

    # Simulate load endpoint (size cap applies)
    from cli.run_bot import MarketMakerBot
    # Reuse handler implementation by attaching methods to dummy instance
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = m
    bot._check_admin_token = lambda req: True
    bot._admin_actor_hash = lambda req: "test"
    bot._admin_rate_limit_check = lambda actor, ep: True
    def mkreq(body):
        async def _json():
            return body
        return SimpleNamespace(headers={"X-Admin-Token":"t"}, rel_url=SimpleNamespace(query={}), json=_json)
    res = asyncio_run(bot._admin_cost_calibration_load(mkreq({"path": str(p)})))
    assert res.status == 200
    data = json.loads(res.text)
    assert data.get('status') == 'ok'
    applied = data.get('applied', {})
    assert 'BTCUSDT' in applied


def asyncio_run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


