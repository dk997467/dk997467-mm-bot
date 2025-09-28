import json
import hashlib
import asyncio


def _write_wrapper(path, payload, *, sha_override=None, extra_keys=None):
    pj = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sha = hashlib.sha256(pj).hexdigest()
    obj = {"version": 1, "sha256": sha if sha_override is None else sha_override, "payload": payload}
    if isinstance(extra_keys, dict):
        obj.update(extra_keys)
    path.write_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _write_non_ascii(path):
    # ensure non-ASCII bytes present; keep valid JSON
    txt = json.dumps({"version": 1, "sha256": "00", "payload": {"k": "я"}}, ensure_ascii=False, separators=(",", ":"))
    path.write_bytes(txt.encode("utf-8"))


def _mk_srv(monkeypatch):
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # minimal ctx stubs so success path (not used here) would not explode
    class _Alloc:
        def load_snapshot(self, snap):
            return None
        def to_snapshot(self):
            return {"version": 1}
    class _Throttle:
        def load_snapshot(self, snap):
            return None
        def to_snapshot(self):
            return {"version": 1}
    srv.ctx = type("Ctx", (), {"allocator": _Alloc(), "throttle": _Throttle()})()

    # metrics stub capturing increments
    class _Counter:
        def __init__(self, store):
            self._store = store
        def labels(self, kind):
            k = str(kind)
            return type("L", (), {"inc": lambda self_l: _inc(self._store, k)})()

    def _inc(store, key):
        store[key] = int(store.get(key, 0)) + 1

    class M:
        def __init__(self):
            self._loads_failed = {"allocator": 0, "throttle": 0, "rollout_state": 0, "rollout_ramp": 0, "cost_calib": 0}
            self._integrity = {}
        # loads counters
        def inc_allocator_snapshot_load(self, ok, ts):
            if not ok:
                self._loads_failed["allocator"] += 1
        def inc_throttle_snapshot_load(self, ok, ts):
            if not ok:
                self._loads_failed["throttle"] += 1
        def inc_rollout_state_snapshot_load(self, ok, ts):
            if not ok:
                self._loads_failed["rollout_state"] += 1
        def inc_ramp_snapshot_load(self, ok, ts):
            if not ok:
                self._loads_failed["rollout_ramp"] += 1
        def inc_cost_calib_snapshot_load(self, ok, ts):
            if not ok:
                self._loads_failed["cost_calib"] += 1
        # integrity counter with labels(kind)
        @property
        def snapshot_integrity_fail_total(self):
            return _Counter(self._integrity)
        # misc no-ops
        def inc_admin_request(self, e):
            return None
        def inc_admin_unauthorized(self, e):
            return None
        def inc_admin_rate_limited(self, e):
            return None

    srv.metrics = M()
    return srv


def _mk_req(path, ep):
    class Req:
        def __init__(self, p, endpoint):
            self._body = {"path": str(p)}
            self.headers = {"X-Admin-Token": "TOK"}
            self.rel_url = type("U", (), {"query": {}})()
            self.path = endpoint
        async def json(self):
            return dict(self._body)
    return Req(path, ep)


def _get_loader(srv, endpoint):
    return getattr(srv, {
        "/admin/allocator/load": "_admin_allocator_load",
        "/admin/throttle/load": "_admin_throttle_load",
        "/admin/rollout/ramp/load": "_admin_rollout_ramp_load",
        "/admin/rollout/state/load": "_admin_rollout_state_load",
        "/admin/allocator/cost_calibration/load": "_admin_cost_calibration_load",
    }[endpoint])


def _kind(endpoint):
    return {
        "/admin/allocator/load": "allocator",
        "/admin/throttle/load": "throttle",
        "/admin/rollout/ramp/load": "rollout_ramp",
        "/admin/rollout/state/load": "rollout_state",
        "/admin/allocator/cost_calibration/load": "cost_calib",
    }[endpoint]


def _get_err(resp):
    try:
        body = json.loads(resp.body.decode())
    except Exception:
        body = {}
    return body.get("error")


def test_fuzz_invalid_structures(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot  # ensure import
    srv = _mk_srv(monkeypatch)
    endpoints = [
        "/admin/allocator/load",
        "/admin/throttle/load",
        "/admin/rollout/ramp/load",
        "/admin/rollout/state/load",
        "/admin/allocator/cost_calibration/load",
    ]
    loop = asyncio.new_event_loop()
    try:
        # 1) missing keys
        for miss in ("version", "sha256", "payload"):
            p = tmp_path / f"miss_{miss}.json"
            obj = {"version": 1, "sha256": "00", "payload": {}}
            del obj[miss]
            p.write_bytes(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
            for ep in endpoints:
                fn = _get_loader(srv, ep)
                resp = loop.run_until_complete(fn(_mk_req(p, ep)))
                assert resp.status == 400
                assert _get_err(resp) == "invalid_structure"
                assert srv.metrics._loads_failed[_kind(ep)] >= 1
                assert srv.metrics._integrity.get(_kind(ep), 0) >= 1

        # 2) extra keys and wrong types
        p_extra = tmp_path / "extra_keys.json"
        _write_wrapper(p_extra, {"ok": True}, extra_keys={"extra": 1})
        for ep in endpoints:
            fn = _get_loader(srv, ep)
            resp = loop.run_until_complete(fn(_mk_req(p_extra, ep)))
            assert resp.status == 400
            assert _get_err(resp) == "invalid_structure"
            assert srv.metrics._loads_failed[_kind(ep)] >= 1
            assert srv.metrics._integrity.get(_kind(ep), 0) >= 1

        p_types = tmp_path / "wrong_types.json"
        p_types.write_bytes(json.dumps({"version": "1", "sha256": 10, "payload": []}, separators=(",", ":")).encode("utf-8"))
        for ep in endpoints:
            fn = _get_loader(srv, ep)
            resp = loop.run_until_complete(fn(_mk_req(p_types, ep)))
            assert resp.status == 400
            assert _get_err(resp) == "invalid_structure"
            assert srv.metrics._loads_failed[_kind(ep)] >= 1
            assert srv.metrics._integrity.get(_kind(ep), 0) >= 1

        # 3) checksum mismatch
        p_bad = tmp_path / "bad_checksum.json"
        _write_wrapper(p_bad, {"a": 1}, sha_override="00")
        for ep in endpoints:
            fn = _get_loader(srv, ep)
            resp = loop.run_until_complete(fn(_mk_req(p_bad, ep)))
            assert resp.status == 400
            assert _get_err(resp) == "bad_checksum"
            assert srv.metrics._loads_failed[_kind(ep)] >= 1
            assert srv.metrics._integrity.get(_kind(ep), 0) >= 1

        # 4) non-ASCII bytes in file
        p_na = tmp_path / "non_ascii.json"
        _write_non_ascii(p_na)
        for ep in endpoints:
            fn = _get_loader(srv, ep)
            resp = loop.run_until_complete(fn(_mk_req(p_na, ep)))
            assert resp.status == 400
            assert _get_err(resp) == "non_ascii"
            assert srv.metrics._loads_failed[_kind(ep)] >= 1
            assert srv.metrics._integrity.get(_kind(ep), 0) >= 1

        # 5) file > 1MB
        big = tmp_path / "big.json"
        payload = {"blob": "A" * (1024 * 1024)}
        _write_wrapper(big, payload)
        # inflate over 1MB by appending spaces (still valid JSON if inside string)
        # Instead, ensure size > 1MB by writing raw payload larger than limit
        big.write_bytes((b"{" + b"\"payload\":" + b"\"" + (b"A" * (1024 * 1024 + 10)) + b"\",\"version\":1,\"sha256\":\"00\"}") )
        for ep in endpoints:
            fn = _get_loader(srv, ep)
            resp = loop.run_until_complete(fn(_mk_req(big, ep)))
            assert resp.status == 400
            assert _get_err(resp) == "file_too_large"
            assert srv.metrics._loads_failed[_kind(ep)] >= 1
            assert srv.metrics._integrity.get(_kind(ep), 0) >= 1
    finally:
        loop.close()


