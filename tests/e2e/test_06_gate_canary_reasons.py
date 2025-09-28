"""
E2E-06: Gate Canary Reasons — детерминированные причины, без фоновых циклов/рандома
"""

import json
import pytest

from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


def _eval_canary(canary: dict, symbol: str = "BTCUSDT"):
    wf = {"symbol": symbol, "canary": canary}
    ok, reasons, metrics = evaluate(wf_report=wf, thresholds=GateThresholds())
    return ok, reasons, metrics


@pytest.mark.asyncio
async def test_gate_reason_killswitch_fired():
    canary = {
        "killswitch_fired": True,
        "drift_alert": False,
        "fills_blue": 2000,
        "fills_green": 1000,
        "rejects_blue": 20,
        "rejects_green": 20,
        "latency_ms_avg_blue": 25.0,
        "latency_ms_avg_green": 25.0,
    }
    ok, reasons, metrics = _eval_canary(canary)
    assert ok is False
    assert metrics.get("canary_gate_reasons", [None])[0] == "killswitch_fired"


@pytest.mark.asyncio
async def test_gate_reason_rollout_drift():
    canary = {
        "killswitch_fired": False,
        "drift_alert": True,
        "fills_blue": 1500,
        "fills_green": 1500,
        "rejects_blue": 15,
        "rejects_green": 15,
        "latency_ms_avg_blue": 25.0,
        "latency_ms_avg_green": 25.0,
    }
    ok, reasons, metrics = _eval_canary(canary)
    assert ok is False
    assert metrics.get("canary_gate_reasons", [None])[0] == "rollout_drift"


@pytest.mark.asyncio
async def test_gate_reason_reject_delta_exceeds():
    # Blue: 2000 fills, 20 rejects → ~0.0099; Green: 700 fills, 140 rejects → ~0.166
    canary = {
        "killswitch_fired": False,
        "drift_alert": False,
        "fills_blue": 2000,
        "fills_green": 700,
        "rejects_blue": 20,
        "rejects_green": 140,
        "latency_ms_avg_blue": 25.0,
        "latency_ms_avg_green": 25.0,
    }
    ok, reasons, metrics = _eval_canary(canary)
    assert ok is False
    assert metrics.get("canary_gate_reasons", [None])[0] == "reject_delta_exceeds"


@pytest.mark.asyncio
async def test_gate_reason_latency_delta_exceeds():
    canary = {
        "killswitch_fired": False,
        "drift_alert": False,
        "fills_blue": 1000,
        "fills_green": 1000,
        "rejects_blue": 10,
        "rejects_green": 10,
        "latency_ms_avg_blue": 20.0,
        "latency_ms_avg_green": 180.0,
    }
    ok, reasons, metrics = _eval_canary(canary)
    assert ok is False
    assert metrics.get("canary_gate_reasons", [None])[0] == "latency_delta_exceeds"