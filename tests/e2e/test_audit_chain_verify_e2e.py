import json
import subprocess
import sys
from pathlib import Path


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def test_audit_chain_verify_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path
    (work / 'artifacts').mkdir(parents=True, exist_ok=True)

    # Use provided fixtures
    ok_src = root / 'tests' / 'fixtures' / 'audit' / 'chain_ok.jsonl'
    bad_src = root / 'tests' / 'fixtures' / 'audit' / 'chain_broken.jsonl'

    # OK case
    ok_dst = work / 'artifacts' / 'audit.jsonl'
    ok_dst.write_bytes(ok_src.read_bytes())
    out_json = work / 'artifacts' / 'AUDIT_CHAIN_VERIFY.json'
    out_md = work / 'artifacts' / 'AUDIT_CHAIN_VERIFY.md'
    r = subprocess.run([sys.executable, '-m', 'tools.audit.verify_chain', '--audit', str(ok_dst), '--utc-date', '1970-01-01', '--out-json', str(out_json), '--out-md', str(out_md)], cwd=str(root), capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.strip().endswith('AUDIT_VERIFY=OK')
    got_j = _read_bytes(out_json)
    got_m = _read_bytes(out_md)
    gdir = root / 'tests' / 'golden'
    exp_j = (gdir / 'AUDIT_CHAIN_VERIFY_case1.json').read_bytes()
    exp_m = (gdir / 'AUDIT_CHAIN_VERIFY_case1.md').read_bytes()
    assert got_j == exp_j
    assert got_m == exp_m

    # BROKEN case
    bad_dst = work / 'artifacts' / 'audit.jsonl'
    bad_dst.write_bytes(bad_src.read_bytes())
    out_json2 = work / 'artifacts' / 'AUDIT_CHAIN_VERIFY.json'
    out_md2 = work / 'artifacts' / 'AUDIT_CHAIN_VERIFY.md'
    r2 = subprocess.run([sys.executable, '-m', 'tools.audit.verify_chain', '--audit', str(bad_dst), '--utc-date', '1970-01-01', '--out-json', str(out_json2), '--out-md', str(out_md2)], cwd=str(root), capture_output=True, text=True)
    assert r2.returncode == 0
    assert r2.stdout.strip().endswith('AUDIT_VERIFY=BROKEN')
    # For broken case we only assert endswith LF and presence of nonzero broken
    j2 = json.loads(out_json2.read_text(encoding='ascii'))
    assert j2['broken'] > 0
    assert out_json2.read_bytes().endswith(b"\n")
    assert out_md2.read_bytes().endswith(b"\n")


