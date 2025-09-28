import asyncio
import json
from types import SimpleNamespace


def _mk_bot(tmp_path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    # enable recorder
    bot._exec_recorder_enabled = True
    bot._exec_recorder_file = str(tmp_path/"artifacts"/"exe_20250101.jsonl")
    # minimal metrics
    from tests.e2e._utils import make_metrics_ctx
    bot.metrics = make_metrics_ctx()
    # helper for append already exists
    return bot


def test_record_lines_on_fill_and_reject(tmp_path):
    bot = _mk_bot(tmp_path)
    # simulate write on fill
    bot._record_execution_event({
        "ts": 1,
        "kind": "fill",
        "symbol": "BTC",
        "side": "Buy",
        "price": 100.0,
        "qty": 1.0,
        "cid": "c1",
        "color": "green",
    })
    bot._record_execution_event({
        "ts": 2,
        "kind": "reject",
        "symbol": "BTC",
        "side": "Sell",
        "price": 101.0,
        "qty": 2.0,
        "cid": "c2",
        "color": "blue",
    })
    p = tmp_path/"artifacts"/"exe_20250101.jsonl"
    txt = p.read_text(encoding='utf-8')
    lines = [ln for ln in txt.split('\n') if ln]
    assert len(lines) == 2
    for ln in lines:
        obj = json.loads(ln)
        assert set(obj.keys()) == {"ts","kind","symbol","side","price","qty","cid","color"}


