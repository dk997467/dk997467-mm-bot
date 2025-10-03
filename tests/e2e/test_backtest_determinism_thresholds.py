import os
import json
import subprocess
from pathlib import Path


def _set_env():
    os.environ.setdefault("MM_FREEZE_UTC", "1")
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("TZ", "UTC")
    os.environ.setdefault("LC_ALL", "C")
    os.environ.setdefault("LANG", "C")


def _readb(p: str) -> bytes:
    return Path(p).read_bytes()


def _ends_lf(p: str) -> bool:
    b = _readb(p)
    return len(b) > 0 and b[-1:] == b"\n"


def test_report_and_md_determinism():
    _set_env()
    root = Path(__file__).resolve().parents[2]
    ticks = root / "tests" / "fixtures" / "backtest_ticks_case1.jsonl"
    out_json = root / "artifacts" / "BACKTEST_REPORT.json"
    out_md = root / "artifacts" / "BACKTEST_REPORT.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        os.sys.executable,
        "-m",
        "tools.backtest.cli",
        "run",
        "--ticks",
        str(ticks),
        "--mode",
        "queue_aware",
        "--out",
        str(out_json),
    ]

    r1 = subprocess.run(cmd, check=False, timeout=300)
    assert r1.returncode == 0
    b1_json = _readb(str(out_json))
    b1_md = _readb(str(out_md))

    r2 = subprocess.run(cmd, check=False, timeout=300)
    assert r2.returncode == 0
    b2_json = _readb(str(out_json))
    b2_md = _readb(str(out_md))

    assert b1_json == b2_json
    assert b1_md == b2_md

    assert _ends_lf(str(out_json))
    assert _ends_lf(str(out_md))

    obj = json.loads(b1_json.decode("ascii"))
    assert list(obj.keys()) == sorted(obj.keys())
    assert obj["net_bps"] >= 2.5
    assert obj["taker_share_pct"] <= 15.0
    assert obj["order_age_p95_ms"] <= 350.0


def test_walkforward_determinism_and_thresholds():
    _set_env()
    root = Path(__file__).resolve().parents[2]
    ticks = root / "tests" / "fixtures" / "backtest_ticks_case1.jsonl"
    out_json = root / "artifacts" / "BACKTEST_WF.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        os.sys.executable,
        "-m",
        "tools.backtest.cli",
        "wf",
        "--ticks",
        str(ticks),
        "--mode",
        "queue_aware",
        "--train",
        "200",
        "--test",
        "100",
        "--out",
        str(out_json),
    ]

    r1 = subprocess.run(cmd, check=False, timeout=300)
    assert r1.returncode == 0
    b1 = _readb(str(out_json))

    r2 = subprocess.run(cmd, check=False, timeout=300)
    assert r2.returncode == 0
    b2 = _readb(str(out_json))

    assert b1 == b2
    assert _ends_lf(str(out_json))

    obj = json.loads(b1.decode("ascii"))
    assert list(obj.keys()) == sorted(obj.keys())
    assert isinstance(obj.get("windows", []), list)
    # mean/median present
    assert "mean" in obj and "median" in obj


