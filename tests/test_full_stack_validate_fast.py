import os, sys, subprocess


def _run(cmd, env=None, timeout=120):
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout, env=env
    )


def test_fast_mode_by_flag():
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    p = _run([sys.executable, "tools/ci/full_stack_validate.py", "--fast"], env=env)
    assert p.returncode == 0, p.stdout
    assert "FULL STACK VALIDATION FAST: OK" in p.stdout, p.stdout
    assert "Running tests whitelist..." not in p.stdout, p.stdout


def test_fast_mode_by_env():
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["CI_FAST"] = "1"
    p = _run([sys.executable, "tools/ci/full_stack_validate.py"], env=env)
    assert p.returncode == 0, p.stdout
    assert "FULL STACK VALIDATION FAST: OK" in p.stdout, p.stdout
    assert "Running tests whitelist..." not in p.stdout, p.stdout

