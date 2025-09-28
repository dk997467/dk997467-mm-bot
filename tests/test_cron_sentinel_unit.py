import json
import os
import time
from pathlib import Path


def test_cron_sentinel_ok_unit(tmp_path):
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)

    today = '1970-01-01'
    ymd = today.replace('-', '')

    # REPORT_SOAK_today.json
    (artifacts / f'Report_Soak_{ymd}.json')
    p_soak = artifacts / f'RePORT_SOAK_{ymd}.json'
    # ensure correct case
    p_soak = artifacts / f'REPORT_SOAK_{ymd}.json'
    p_soak.write_text('{"verdict":"OK"}\n', encoding='ascii', newline='\n')

    # FULL_STACK_VALIDATION.md
    p_full = artifacts / 'FULL_STACK_VALIDATION.md'
    p_full.write_text('RESULT=OK\n', encoding='ascii', newline='\n')

    # DAILY_DIGEST.md
    p_digest = artifacts / 'DAILY_DIGEST.md'
    p_digest.write_text('daily ok\n', encoding='ascii', newline='\n')

    # AUDIT_CHAIN_VERIFY.json
    p_audit = artifacts / 'AUDIT_CHAIN_VERIFY.json'
    p_audit.write_text('{"broken":0}\n', encoding='ascii', newline='\n')

    # Fresh mtimes within window
    now = time.time()
    recent = now - 60
    for p in (p_full, p_digest, p_audit):
        os.utime(str(p), (recent, recent))

    from tools.ops.cron_sentinel import main
    out_json = artifacts / 'CRON_SENTINEL.json'
    out_md = artifacts / 'CRON_SENTINEL.md'

    rc = main(['--window-hours', '24', '--artifacts-dir', str(artifacts), '--utc-today', today, '--out-json', str(out_json), '--out-md', str(out_md)])
    assert rc == 0
    j = json.loads(out_json.read_text(encoding='ascii'))
    assert j['result'] == 'OK'
    assert out_json.read_bytes().endswith(b'\n')
    assert out_md.read_bytes().endswith(b'\n')


