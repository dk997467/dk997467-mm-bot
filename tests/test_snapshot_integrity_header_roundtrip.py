import json
import asyncio


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    return srv


def test_snapshot_integrity_header_roundtrip(tmp_path):
    srv = _mk_srv()
    # allocator
    alloc_path = tmp_path / 'allocator_hwm.json'
    srv._atomic_snapshot_write(str(alloc_path), {"version":1,"hwm_equity_usd":123.0}, version=1)
    data = json.loads(alloc_path.read_text(encoding='utf-8'))
    assert set(data.keys()) == {"version","sha256","payload"}
    inner = json.dumps(data['payload'], sort_keys=True, separators=(",", ":")).encode('utf-8')
    import hashlib
    assert hashlib.sha256(inner).hexdigest() == data['sha256']

    # throttle
    thr_path = tmp_path / 'throttle_snapshot.json'
    srv._atomic_snapshot_write(str(thr_path), {"version":2,"window_since":"t","events_total":0}, version=2)
    data2 = json.loads(thr_path.read_text(encoding='utf-8'))
    assert set(data2.keys()) == {"version","sha256","payload"}
    inner2 = json.dumps(data2['payload'], sort_keys=True, separators=(",", ":")).encode('utf-8')
    assert hashlib.sha256(inner2).hexdigest() == data2['sha256']


