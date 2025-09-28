import json
import asyncio
from types import SimpleNamespace


def _mk_srv(tmp_path):
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # seed metrics
    from tests.e2e._utils import make_metrics_ctx
    m = make_metrics_ctx()
    srv.metrics = m
    # attach helper to read file
    srv._safe_read_text_file = lambda p, limit_bytes=1<<20: open(p, 'rb').read().decode('utf-8')
    return srv


def test_replay_happy(tmp_path):
    srv = _mk_srv(tmp_path)
    path = tmp_path / "artifacts" / "exe_20250101.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # compose events
    lines = [
        json.dumps({"ts":1, "kind":"fill", "symbol":"BTC", "side":"Buy", "price":100.0, "qty":1.0, "cid":"c1", "color":"green"}),
        json.dumps({"ts":2, "kind":"reject", "symbol":"BTC", "side":"Sell", "price":101.0, "qty":2.0, "cid":"c2", "color":"blue"}),
        json.dumps({"ts":3, "kind":"order", "symbol":"BTC", "side":"Buy", "price":99.0, "qty":1.0, "cid":"c3", "color":"green"}),
    ]
    path.write_text("\n".join(lines)+"\n", encoding='utf-8')

    class Req:
        headers = {"X-Admin-Token":"t"}
        rel_url = SimpleNamespace(query={})
        method = "POST"
        async def json(self):
            return {"path": str(path), "speed": "1x"}

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(srv._admin_execution_replay(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        assert set(data.keys()) == {"events_total","fills","rejects","by_symbol"}
        assert data["events_total"] == 3
        assert data["fills"] == 1
        assert data["rejects"] == 1
        assert data["by_symbol"].get("BTC", {}).get("fills") == 1
    finally:
        loop.close()


def test_replay_limits_and_invalid(tmp_path):
    srv = _mk_srv(tmp_path)
    # invalid json
    class ReqBad:
        headers = {"X-Admin-Token":"t"}
        rel_url = SimpleNamespace(query={})
        method = "POST"
        async def json(self):
            return {"path": str(tmp_path/"missing.jsonl"), "speed": "1x"}

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(srv._admin_execution_replay(ReqBad()))
        assert res.status == 400
        data = json.loads(res.body.decode())
        assert "error" in data
    finally:
        loop.close()


