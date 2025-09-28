import json
import os
import subprocess
from pathlib import Path


def read(path: str) -> str:
    with open(path, 'rb') as f:
        return f.read().decode('ascii')


def test_cli_run_and_wf(tmp_path):
    root = Path(__file__).resolve().parents[2]
    ticks = root / "tests" / "fixtures" / "backtest_ticks_case1.jsonl"
    out_json = tmp_path / "BACKTEST_REPORT.json"
    out_md = tmp_path / "BACKTEST_REPORT.md"

    # run
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
    r = subprocess.run(cmd, check=False)
    assert r.returncode == 0

    g_json = (root / "tests" / "golden" / "backtest_report_case1.json").read_bytes()
    got_json = out_json.read_bytes()
    assert got_json == g_json

    g_md = (root / "tests" / "golden" / "backtest_report_case1.md").read_text(encoding='ascii')
    got_md = (tmp_path / "BACKTEST_REPORT.md").read_text(encoding='ascii')
    assert got_md == g_md

    # wf
    out_wf = tmp_path / "BACKTEST_WF.json"
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
        str(out_wf),
    ]
    r = subprocess.run(cmd, check=False)
    assert r.returncode == 0

    g_wf = (root / "tests" / "golden" / "backtest_walkforward_case1.json").read_bytes()
    got_wf = out_wf.read_bytes()
    assert got_wf == g_wf

    # thresholds
    parsed = json.loads(read(str(out_json)))
    assert parsed["net_bps"] >= 2.5
    assert parsed["taker_share_pct"] <= 15.0
    assert parsed["order_age_p95_ms"] <= 350.0


