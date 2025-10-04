import subprocess
import sys
from pathlib import Path


def test_repro_minimizer_e2e(tmp_path):
    src = Path('tests/fixtures/repro/full_case.jsonl').read_text(encoding='ascii')
    inp = tmp_path / 'case.jsonl'
    inp.write_text(src, encoding='ascii')
    out_jsonl = tmp_path / 'artifacts' / 'REPRO_MIN.jsonl'
    out_md = tmp_path / 'artifacts' / 'REPRO_MIN.md'
    r = subprocess.run([sys.executable, '-m', 'tools.debug.repro_minimizer', '--events', str(inp), '--out-jsonl', str(out_jsonl), '--out-md', str(out_md)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0
    got = out_jsonl.read_bytes()
    golden = Path('tests/golden/REPRO_MIN_case1.jsonl').read_bytes()
    assert got == golden
    got_md = out_md.read_bytes()
    golden_md = Path('tests/golden/REPRO_MIN_case1.md').read_bytes()
    assert got_md == golden_md


