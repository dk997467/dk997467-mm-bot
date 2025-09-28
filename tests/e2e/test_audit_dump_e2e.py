import json
from pathlib import Path

from src.audit.writer import append_record


def test_audit_dump_e2e(tmp_path):
    audit_path = tmp_path / 'artifacts' / 'audit.jsonl'
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    # Seed from fixtures
    data = json.loads(Path('tests/fixtures/audit/day_events.json').read_text(encoding='ascii'))
    prev = None
    for ev in data:
        prev = append_record(str(audit_path), ev['ts'], ev['kind'], ev['symbol'], ev['fields'])
    # Dump day
    from tools.audit.dump_day import main as dump_main
    dump_main(['--audit', str(audit_path), '--utc-date', '1970-01-01', '--out', str(tmp_path / 'artifacts' / 'AUDIT_DUMP.jsonl')])
    got = (tmp_path / 'artifacts' / 'AUDIT_DUMP.jsonl').read_bytes()
    gold = Path('tests/golden/AUDIT_DUMP_case1.jsonl').read_bytes()
    assert got == gold


