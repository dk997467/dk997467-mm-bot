from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def test_autopolicy_gate_fail():
    wf = {
        "champion": {"aggregates": {}},
        "metadata": {"report_utc": "2025-01-01T00:00:00Z"},
        "audit": {"autopolicy_level": 2}
    }
    thr = GateThresholds(max_autopolicy_level_on_promote=1)
    ok, reasons, metrics = evaluate(wf, thr)
    assert ok is False
    assert any("Autopolicy level too high" in r for r in reasons)

