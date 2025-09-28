import os
import subprocess
import sys


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main() -> int:
    env = os.environ.copy()
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    env['TZ'] = 'UTC'
    env['LC_ALL'] = 'C'

    results = []
    tasks = [
        (['python', 'tools/ci/lint_ascii_logs.py'], 'ascii_logs'),
        (['python', 'tools/ci/lint_json_writer.py'], 'json_writer'),
        (['python', 'tools/ci/lint_metrics_labels.py'], 'metrics_labels'),
        (['python', 'tools/ci/run_selected.py'], 'tests_whitelist'),
    ]
    overall_ok = True
    for cmd, name in tasks:
        code, out = run(cmd)
        ok = (code == 0)
        overall_ok = overall_ok and ok
        print(('[OK] ' if ok else '[FAIL] ') + name)
    print('RESULT=' + ('OK' if overall_ok else 'FAIL'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


