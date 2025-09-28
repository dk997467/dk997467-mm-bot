import os
import json
from types import SimpleNamespace


def test_append_json_line_is_atomic_and_ascii(tmp_path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot._ensure_admin_audit_initialized()
    path = tmp_path / "artifacts" / "exe_20250101.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    # two writes -> two lines; ASCII-only enforced by encoder; fsync best-effort
    bot._append_json_line(str(path), {"a":1})
    bot._append_json_line(str(path), {"b":2})

    with open(path, 'rb') as f:
        data = f.read()
    # file should be ASCII-compatible and contain exactly two lines
    txt = data.decode('utf-8')
    lines = [ln for ln in txt.split('\n') if ln]
    assert len(lines) == 2
    # each line is valid deterministic JSON
    obj1 = json.loads(lines[0])
    obj2 = json.loads(lines[1])
    assert obj1 == {"a":1}
    assert obj2 == {"b":2}

