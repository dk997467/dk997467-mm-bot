#!/usr/bin/env python3
import os, sys, argparse, json
from pathlib import Path

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD","1")
os.environ.setdefault("TZ","UTC")
os.environ.setdefault("LC_ALL","C")
os.environ.setdefault("LANG","C")

from src.sim.execution import run_sim


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True)
    p.add_argument("--mode", default=os.environ.get("MM_SIM_MODE", "queue_aware"))
    p.add_argument("--out", default=str(Path("artifacts")/"SIM_REPORT.json"))
    args = p.parse_args(argv)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    params = {
        "queue": {
            "initial_qpos_ratio": 0.50,
            "queue_penalty_bps": 0.8,
            "adverse_fill_prob": 0.0,
        }
    }
    rep = run_sim(args.events, args.mode, params, args.out)
    fp = Path(args.out)
    print(f"SIM_REPORT path={fp} size={fp.stat().st_size}")
    return 0 if rep else 1


if __name__ == "__main__":
    raise SystemExit(main())


