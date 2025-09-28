from __future__ import annotations

import json
from pathlib import Path

from src.soak.orchestrator import _calc_metrics


def _rec(ts: str, phase: str, status: str, action: str = "NONE"):
    return {"ts": ts, "phase": phase, "status": status, "action": action}


def test_soak_report_aggregation_mttr_and_canary_flag(tmp_path):
    # Synthetic journal: FAIL then CONTINUE in canary, WARN in shadow, rollback actions
    journal = [
        _rec("2025-01-01T00:00:00Z", "shadow", "WARN"),
        _rec("2025-01-01T01:00:00Z", "canary", "FAIL", "ROLLBACK_STEP"),
        _rec("2025-01-01T02:00:00Z", "canary", "CONTINUE"),
        _rec("2025-01-01T03:00:00Z", "live-econ", "CONTINUE"),
    ]
    warn, fail, rollbacks, mttr, uptime, canary_ok = _calc_metrics(journal, ["shadow","canary","live-econ"])
    assert warn == 1
    assert fail == 1
    assert rollbacks == 1
    assert mttr > 0.0
    assert uptime.get("shadow", 0.0) >= 1.0
    assert uptime.get("canary", 0.0) >= 2.0
    assert canary_ok is False

    # If no FAIL in canary window, canary_passed True
    journal2 = [
        _rec("2025-01-02T00:00:00Z", "shadow", "CONTINUE"),
        _rec("2025-01-02T01:00:00Z", "canary", "WARN"),
        _rec("2025-01-02T02:00:00Z", "canary", "CONTINUE"),
    ]
    *_, canary_ok2 = _calc_metrics(journal2, ["shadow","canary","live-econ"])
    assert canary_ok2 is True


