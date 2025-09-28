#!/usr/bin/env python3
"""
Backtest determinism and thresholds checker (stdlib-only).
"""

import os
import sys
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


def main() -> int:
    _set_env()
    root = Path(__file__).resolve().parents[2]
    ticks = root / "tests" / "fixtures" / "backtest_ticks_case1.jsonl"
    rep = root / "artifacts" / "BACKTEST_REPORT.json"
    rep_md = root / "artifacts" / "BACKTEST_REPORT.md"
    wf = root / "artifacts" / "BACKTEST_WF.json"
    rep.parent.mkdir(parents=True, exist_ok=True)

    cmd_run = [sys.executable, "-m", "tools.backtest.cli", "run", "--ticks", str(ticks), "--mode", "queue_aware", "--out", str(rep)]
    r1 = subprocess.run(cmd_run, check=False)
    if r1.returncode != 0:
        return 1
    b1_json = _readb(str(rep))
    b1_md = _readb(str(rep_md))
    r2 = subprocess.run(cmd_run, check=False)
    if r2.returncode != 0:
        return 1
    b2_json = _readb(str(rep))
    b2_md = _readb(str(rep_md))
    if b1_json != b2_json or b1_md != b2_md:
        return 1
    if not _ends_lf(str(rep)):
        return 1
    obj = json.loads(b1_json.decode("ascii"))
    if list(obj.keys()) != sorted(obj.keys()):
        return 1
    if not (obj.get("net_bps", -1) >= 2.5 and obj.get("taker_share_pct", 101.0) <= 15.0 and obj.get("order_age_p95_ms", 1e9) <= 350.0):
        return 1

    cmd_wf = [sys.executable, "-m", "tools.backtest.cli", "wf", "--ticks", str(ticks), "--mode", "queue_aware", "--train", "200", "--test", "100", "--out", str(wf)]
    w1 = subprocess.run(cmd_wf, check=False)
    if w1.returncode != 0:
        return 1
    wb1 = _readb(str(wf))
    w2 = subprocess.run(cmd_wf, check=False)
    if w2.returncode != 0:
        return 1
    wb2 = _readb(str(wf))
    if wb1 != wb2:
        return 1
    if not _ends_lf(str(wf)):
        return 1
    wfobj = json.loads(wb1.decode("ascii"))
    if list(wfobj.keys()) != sorted(wfobj.keys()):
        return 1
    if not isinstance(wfobj.get("windows", []), list):
        return 1

    print("[OK] BACKTEST_REPORT.json deterministic, thresholds passed")
    print("[OK] BACKTEST_WF.json deterministic, structure OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())


