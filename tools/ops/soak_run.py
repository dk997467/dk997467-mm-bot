#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--shadow-hours', type=float, default=0.0)
    ap.add_argument('--canary-hours', type=float, default=0.0)
    ap.add_argument('--live-hours', type=float, default=0.0)
    ap.add_argument('--tz', default='Europe/Berlin')
    ap.add_argument('--out', default=None)
    ap.add_argument('--journal', default='artifacts/SOAK_JOURNAL.jsonl')
    args = ap.parse_args(argv)

    # Reuse orchestrator logic
    from src.soak.orchestrator import main as run
    return run([
        '--shadow-hours', str(args.shadow_hours),
        '--canary-hours', str(args.canary_hours),
        '--live-hours', str(args.live_hours),
        '--tz', str(args.tz),
        '--journal', str(args.journal),
    ] + (['--out', str(args.out)] if args.out else []))


if __name__ == '__main__':
    raise SystemExit(main())


