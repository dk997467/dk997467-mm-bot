import json
import os
from pathlib import Path
import asyncio


async def _call_post(handler, body: dict):
    class Req:
        headers = {"X-Admin-Token": "t"}
        rel_url = type("U", (), {"query": {}})()
        method = 'POST'
        async def json(self):
            return body
    return await handler(Req())


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # minimal attrs used by handlers
    return srv


def test_canary_replay_happy_path(tmp_path):
    # Write canary.json (minimal fields)
    canary = {
        "symbol": "BTCUSDT",
        "rollout": {
            "fills_blue": 1000,
            "fills_green": 1000,
            "rejects_blue": 10,
            "rejects_green": 20,
            "latency_ms_avg_blue": 20.0,
            "latency_ms_avg_green": 90.0,
            "latency_ms_p95_blue": 25.0,
            "latency_ms_p95_green": 100.0,
            "latency_ms_p99_blue": 30.0,
            "latency_ms_p99_green": 180.0,
            "latency_samples_blue": 500,
            "latency_samples_green": 600,
        },
        "drift": {"alert": False},
        "killswitch": {"fired": False}
    }
    canary_path = tmp_path / 'canary.json'
    canary_path.write_text(json.dumps(canary, sort_keys=True, separators=(",", ":")), encoding='utf-8')
    # thresholds.yaml with tail caps
    thr_path = tmp_path / 'thr.yaml'
    thr_path.write_text("""
canary_gate:
  tail_min_sample: 200
  tail_p95_cap_ms: 50
  tail_p99_cap_ms: 100
    """.strip()+"\n", encoding='utf-8')

    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(_call_post(srv._admin_report_canary_replay, {"canary_path": str(canary_path), "thresholds_path": str(thr_path)}))
        assert res.status == 200
        data = json.loads(res.text)
        assert data.get('decision') in ('PASS','FAIL')
        assert isinstance(data.get('reasons', []), list)
        assert isinstance(data.get('used_thresholds', {}), dict)
        assert isinstance(data.get('thresholds_version_before'), int)
        assert isinstance(data.get('thresholds_version_after'), int)
        # ensure restored: version_after should not persist; call again with no-op to read before==after
        res2 = loop.run_until_complete(_call_post(srv._admin_report_canary_replay, {"canary_path": str(canary_path), "thresholds_path": str(thr_path)}))
        data2 = json.loads(res2.text)
        # previous run restored to a baseline; after on second run should be >= before, but immediate restoration keeps before stable across calls
        assert data2['thresholds_version_before'] == data.get('thresholds_version_before')
    finally:
        loop.close()


def test_canary_replay_negative_size(tmp_path):
    big = tmp_path / 'big.yaml'
    # >1MB
    big.write_text('a' * ((1<<20) + 10), encoding='ascii')
    canary = tmp_path / 'c.json'
    canary.write_text(json.dumps({"rollout": {}}, sort_keys=True, separators=(",", ":")), encoding='utf-8')
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(_call_post(srv._admin_report_canary_replay, {"canary_path": str(canary), "thresholds_path": str(big)}))
        assert res.status == 400
        data = json.loads(res.text)
        assert data.get('error') == 'file_too_large'
    finally:
        loop.close()


def test_canary_replay_invalid_yaml(tmp_path):
    bad = tmp_path / 'bad.yaml'
    bad.write_text("\x00\x01\x02", encoding='latin1', errors='ignore')
    canary = tmp_path / 'c.json'
    canary.write_text(json.dumps({"rollout": {}}, sort_keys=True, separators=(",", ":")), encoding='utf-8')
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(_call_post(srv._admin_report_canary_replay, {"canary_path": str(canary), "thresholds_path": str(bad)}))
        # our parser reads text but refresh will fail parsing due to structure
        assert res.status == 400
        data = json.loads(res.text)
        assert 'error' in data
    finally:
        loop.close()


def test_canary_replay_strict_fail(tmp_path, monkeypatch):
    # enable strict
    from src.deploy import thresholds as TH
    monkeypatch.setattr(TH, 'STRICT_THRESHOLDS', True, raising=False)
    thr = tmp_path / 'thr_bad.yaml'
    thr.write_text("""
canary_gate_per_symbol:
  BTCUSDT:
    tail_p95_cap_ms: -5
    """.strip()+"\n", encoding='utf-8')
    canary = tmp_path / 'c.json'
    canary.write_text(json.dumps({"symbol":"BTCUSDT","rollout": {}}, sort_keys=True, separators=(",", ":")), encoding='utf-8')
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(_call_post(srv._admin_report_canary_replay, {"canary_path": str(canary), "thresholds_path": str(thr)}))
        assert res.status == 400
    finally:
        loop.close()


