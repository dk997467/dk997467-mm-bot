import subprocess
import sys
from pathlib import Path


def test_smoke_tree_missing_docs(tmp_path):
    # no docs/INDEX.md → FAIL
    (tmp_path / 'docs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml').write_text('groups:\n- name: g\n  rules:\n  - alert: X\n', encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'tools.ci.smoke_tree', '--root', str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1
    assert 'SMOKE=FAIL' in r.stdout


def test_smoke_tree_ok(tmp_path):
    # valid docs and yml-ish file
    (tmp_path / 'docs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'docs' / 'INDEX.md').write_text('# Title\n', encoding='utf-8')
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml').write_text('groups:\n- name: g\n  rules:\n  - alert: X\n    expr: up == 1\n', encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'tools.ci.smoke_tree', '--root', str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0
    assert 'SMOKE=OK' in r.stdout


def test_smoke_tree_bad_yaml(tmp_path):
    (tmp_path / 'docs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'docs' / 'INDEX.md').write_text('# Title\n', encoding='utf-8')
    (tmp_path / 'monitoring' / 'alerts').mkdir(parents=True, exist_ok=True)
    # missing ':' in critical line
    (tmp_path / 'monitoring' / 'alerts' / 'mm_bot.rules.yml').write_text('groups\n- name g\n  rules\n  - alert X\n', encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'tools.ci.smoke_tree', '--root', str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1
    assert 'SMOKE=FAIL' in r.stdout


