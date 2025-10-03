import os
from pathlib import Path
import subprocess


def test_investor_package_end2end(tmp_path):
    root = Path(__file__).resolve().parents[2]
    art = root / "tests" / "fixtures" / "artifacts_sample" / "metrics.json"
    env = os.environ.copy()
    env["MM_FREEZE_UTC"] = "1"
    # First run
    r1 = subprocess.run([os.sys.executable, "-m", "tools.finops.assemble_investor_pkg", str(art, timeout=300)], check=False, env=env)
    assert r1.returncode == 0
    # Second run
    r2 = subprocess.run([os.sys.executable, "-m", "tools.finops.assemble_investor_pkg", str(art, timeout=300)], check=False, env=env)
    assert r2.returncode == 0
    # Compare docs
    got_deck = (root / "docs" / "INVESTOR_DECK.md").read_bytes()
    got_sop = (root / "docs" / "SOP_CAPITAL.md").read_bytes()
    exp_deck = (root / "tests" / "golden" / "investor" / "INVESTOR_DECK.md").read_bytes()
    exp_sop = (root / "tests" / "golden" / "investor" / "SOP_CAPITAL.md").read_bytes()
    assert got_deck == exp_deck
    assert got_sop == exp_sop
    # Locate last dist dir (deterministic ts with freeze)
    distdir = root / "dist" / "investor"
    dirs = sorted([p for p in distdir.iterdir() if p.is_dir()])
    assert dirs, "dist empty"
    d = dirs[-1]
    gdir = root / "tests" / "golden" / "finops_exports"
    for name in ("pnl.csv","fees.csv","turnover.csv","latency.csv","edge.csv"):
        got = (d / name).read_bytes()
        exp = (gdir / name).read_bytes()
        assert got.endswith(b"\n")
        assert got == exp


