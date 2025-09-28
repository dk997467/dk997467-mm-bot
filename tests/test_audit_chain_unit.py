import json
from src.audit.writer import append_record
from src.audit.schema import validate_chain_line


def test_chain_integrity(tmp_path):
    path = tmp_path / 'audit.jsonl'
    # append two records
    s1 = append_record(str(path), '1970-01-01T00:00:00Z', 'ALLOC', 'BTCUSDT', {'api_secret': 'secret', 'delta': 0.1})
    s2 = append_record(str(path), '1970-01-01T00:01:00Z', 'REPLACE', 'BTCUSDT', {'order_id': 'x', 'price': 1.0})
    lines = path.read_text(encoding='ascii').splitlines()
    # validate chain
    prev = 'GENESIS'
    for ln in lines:
        assert validate_chain_line(prev, ln)
        prev = json.loads(ln)['sha256']
    # tamper breaks chain
    bad = lines[-1].replace('REPLACE', 'CANCEL')
    assert not validate_chain_line(lines[-2] and json.loads(lines[-2])['sha256'], bad)


