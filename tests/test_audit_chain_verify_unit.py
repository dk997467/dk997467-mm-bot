import json
from pathlib import Path


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_chain_ok_unit(tmp_path):
    # Build a small valid chain
    from src.audit.writer import append_record
    audit = tmp_path / 'audit.jsonl'
    append_record(str(audit), '1970-01-01T00:00:00Z', 'ALLOC', 'BTCUSDT', {'x': 1})
    append_record(str(audit), '1970-01-01T00:01:00Z', 'REPLACE', 'BTCUSDT', {'y': 2})

    from tools.audit.verify_chain import main
    out_json = tmp_path / 'artifacts' / 'AUDIT_CHAIN_VERIFY.json'
    out_md = tmp_path / 'artifacts' / 'AUDIT_CHAIN_VERIFY.md'
    rc = main(['--audit', str(audit), '--out-json', str(out_json), '--out-md', str(out_md)])
    assert rc == 0
    j = json.loads(out_json.read_text(encoding='ascii'))
    assert j['broken'] == 0
    assert j['checked'] == 2
    assert j['first_broken_lineno'] is None
    assert out_json.read_bytes().endswith(b"\n")
    assert out_md.read_bytes().endswith(b"\n")


def test_chain_broken_unit(tmp_path):
    # Build chain and then tamper last line
    from src.audit.writer import append_record
    audit = tmp_path / 'audit.jsonl'
    append_record(str(audit), '1970-01-01T00:00:00Z', 'ALLOC', 'BTCUSDT', {'x': 1})
    append_record(str(audit), '1970-01-01T00:01:00Z', 'REPLACE', 'BTCUSDT', {'y': 2})

    lines = audit.read_text(encoding='ascii').splitlines()
    lines[-1] = lines[-1].replace('REPLACE', 'CANCEL')
    audit.write_text('\n'.join(lines) + '\n', encoding='ascii', newline='\n')

    from tools.audit.verify_chain import main
    out_json = tmp_path / 'artifacts' / 'AUDIT_CHAIN_VERIFY.json'
    out_md = tmp_path / 'artifacts' / 'AUDIT_CHAIN_VERIFY.md'
    rc = main(['--audit', str(audit), '--out-json', str(out_json), '--out-md', str(out_md)])
    assert rc == 0
    j = json.loads(out_json.read_text(encoding='ascii'))
    assert j['broken'] == 1
    assert j['checked'] == 2
    assert j['first_broken_lineno'] == 2
    assert out_json.read_bytes().endswith(b"\n")
    assert out_md.read_bytes().endswith(b"\n")


