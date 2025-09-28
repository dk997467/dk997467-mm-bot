import os
import shutil
import tempfile
import pytest
import json
from types import SimpleNamespace


@pytest.fixture
def artifacts_tmpdir(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("ARTIFACTS_DIR", d)
    # fast test mode
    monkeypatch.setenv("CANARY_EXPORT_INTERVAL_SEC", "1")
    monkeypatch.setenv("PRUNE_INTERVAL_SEC", "2")
    monkeypatch.setenv("ROLLOUT_STEP_INTERVAL_SEC", "1")
    monkeypatch.setenv("SCHEDULER_RECOMPUTE_SEC", "0")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _cleanup_alerts_before_each_test(monkeypatch):
    # ensure alerts.log is empty between tests
    d = os.getenv("ARTIFACTS_DIR", "artifacts")
    try:
        p = os.path.join(d, "alerts.log")
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass


