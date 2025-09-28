import json
from pathlib import Path
import subprocess
import sys


def _write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='ascii', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")


def test_snapshot_on_fail(tmp_path):
    art = tmp_path / 'artifacts'
    (art / 'sub').mkdir(parents=True, exist_ok=True)
    (art / 'EDGE_REPORT.json').write_text('{"x":1}\n', encoding='ascii')
    (art / 'sub' / 'log.log').write_text('log\n', encoding='utf-8')
    j = art / 'SOAK_JOURNAL.jsonl'
    rows = [
        {"ts":"1970-01-01T00:00:00Z","status":"CONTINUE"},
        {"ts":"1970-01-01T01:00:00Z","status":"FAIL"}
    ]
    _write_jsonl(j, rows)
    r = subprocess.run([sys.executable, '-m', 'tools.ops.artifacts_snapshot_on_fail', '--journal', str(j), '--src', str(art), '--dst-root', str(tmp_path / 'fails')], capture_output=True, text=True)
    assert r.returncode == 0
    # find created dir
    out = r.stdout
    assert 'event=snapshot_on_fail status=FAIL' in out
    # There should be at least one copied file
    created = list((tmp_path / 'fails').rglob('*'))
    assert any(p.name == 'EDGE_REPORT.json' for p in created)


def test_snapshot_on_fail_skip(tmp_path):
    art = tmp_path / 'artifacts'
    j = art / 'SOAK_JOURNAL.jsonl'
    _write_jsonl(j, [{"ts":"1970-01-01T00:00:00Z","status":"CONTINUE"}])
    r = subprocess.run([sys.executable, '-m', 'tools.ops.artifacts_snapshot_on_fail', '--journal', str(j), '--src', str(art), '--dst-root', str(tmp_path / 'fails')], capture_output=True, text=True)
    assert r.returncode == 0
    assert 'event=snapshot_on_fail status=SKIP' in r.stdout

