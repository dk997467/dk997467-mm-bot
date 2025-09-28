import threading
import time
import urllib.request
import json

from scripts.smoke_f2 import run_mock_server, STATE


def http_get_json(url):
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode('utf-8'))


def http_post_json(url, payload):
    data = json.dumps(payload, sort_keys=True).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode('utf-8'))


def test_smoke_guard_admin_roundtrip():
    port = 18081
    srv = run_mock_server(port)
    base = f"http://127.0.0.1:{port}"
    time.sleep(0.2)
    # default
    s = http_get_json(base + "/admin/guard")
    assert 'dry_run' in s and 'manual_override_pause' in s
    # set dry_run True
    r = http_post_json(base + "/admin/guard", {"dry_run": True})
    assert r['dry_run'] is True
    # verify reflected
    s2 = http_get_json(base + "/admin/guard")
    assert s2['dry_run'] is True

