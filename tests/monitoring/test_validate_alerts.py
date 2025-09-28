import shutil
from pathlib import Path
import subprocess
import sys


def _run_validator(tmp_path: Path):
    # Call via module path from repo root with --root pointing to tmp_path
    return subprocess.run([sys.executable, '-m', 'tools.monitoring.validate_alerts', '--root', str(tmp_path)], capture_output=True, text=True)


def test_validate_alerts_ok(tmp_path):
    root = Path('.').resolve()
    # copy files
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'monitoring' / 'alertmanager.yml', tmp_path / 'monitoring' / 'alertmanager.yml')
    shutil.copyfile(root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml', tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml')
    (tmp_path / 'docs' / 'runbooks').mkdir(parents=True, exist_ok=True)
    for n in ('circuit_gate.md','full_stack.md','kpi.md'):
        shutil.copyfile(root / 'docs' / 'runbooks' / n, tmp_path / 'docs' / 'runbooks' / n)
    r = _run_validator(tmp_path)
    assert r.returncode == 0
    assert 'event=alerts_validate status=OK' in r.stdout


def test_validate_alerts_missing_runbook_url(tmp_path):
    root = Path('.').resolve()
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    rm_path = tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml'
    content = (root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml').read_text(encoding='utf-8')
    # remove a runbook_url occurrence
    content = content.replace('runbook_url:', 'runbook_missing:')
    (tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml').write_text(content, encoding='utf-8')
    shutil.copyfile(root / 'monitoring' / 'alertmanager.yml', tmp_path / 'monitoring' / 'alertmanager.yml')
    (tmp_path / 'docs' / 'runbooks').mkdir(parents=True, exist_ok=True)
    for n in ('circuit_gate.md','full_stack.md','kpi.md'):
        shutil.copyfile(root / 'docs' / 'runbooks' / n, tmp_path / 'docs' / 'runbooks' / n)
    r = _run_validator(tmp_path)
    assert r.returncode == 1
    assert 'status=FAIL' in r.stdout


def test_validate_alerts_missing_inhibit(tmp_path):
    root = Path('.').resolve()
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    bad_am = (root / 'monitoring' / 'alertmanager.yml').read_text(encoding='utf-8').replace("CircuitTripped", "CircuitTripX")
    (tmp_path / 'monitoring' / 'alertmanager.yml').write_text(bad_am, encoding='utf-8')
    shutil.copyfile(root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml', tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml')
    (tmp_path / 'docs' / 'runbooks').mkdir(parents=True, exist_ok=True)
    for n in ('circuit_gate.md','full_stack.md','kpi.md'):
        shutil.copyfile(root / 'docs' / 'runbooks' / n, tmp_path / 'docs' / 'runbooks' / n)
    r = _run_validator(tmp_path)
    assert r.returncode == 1
    assert 'status=FAIL' in r.stdout

