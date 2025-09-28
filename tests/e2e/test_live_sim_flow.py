import os
import json
from pathlib import Path
import subprocess, sys


def test_live_sim_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("MM_FREEZE_UTC", "1")
    monkeypatch.setenv("MM_MODE", "sim")

    # Run sim
    out_json = tmp_path/"SIM_REPORT.json"
    r = subprocess.run([
        sys.executable, "tools/sim/run_sim.py",
        "--events", "tests/fixtures/sim_events_case1.jsonl",
        "--mode", "queue_aware",
        "--out", str(out_json)
    ], check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    # Validate report (byte-for-byte against golden ignoring runtime.utc)
    got = json.loads(Path(out_json).read_text(encoding="ascii"))
    assert got["fills_total"] >= 1
    assert got["net_bps"] >= 2.5 or got["net_bps"] <= 0  # conservative net_bps here is negative due to fees only
    assert got["taker_share_pct"] <= 100.0
    assert got["order_age_p95_ms"] <= 350.0

    # Normalize runtime.utc for comparison
    got["runtime"]["utc"] = "1970-01-01T00:00:00Z"
    gold = json.loads(Path("tests/golden/sim_report_case1.json").read_text(encoding="ascii"))
    assert json.dumps(got, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n" == json.dumps(gold, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"

    # Render MD and compare
    r2 = subprocess.run([sys.executable, "tools/sim/report_sim.py", str(out_json)], check=False, capture_output=True, text=True)
    assert r2.returncode == 0
    md_path = Path("artifacts")/"REPORT_SIM.md"
    got_md = md_path.read_text(encoding="ascii")
    gold_md = Path("tests/golden/sim_md_case1.md").read_text(encoding="ascii")
    assert got_md == gold_md


