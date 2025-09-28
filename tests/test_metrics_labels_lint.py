import subprocess
import sys


def test_metrics_labels_lint():
    r = subprocess.run([sys.executable, '-m', 'tools.ci.lint_metrics_labels'], capture_output=True, text=True)
    assert r.returncode == 0
    assert 'OK' in r.stdout


