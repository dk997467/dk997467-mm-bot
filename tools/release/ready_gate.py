#!/usr/bin/env python3
"""
READY-gate: block release if readiness below threshold.

Usage:
  python tools/release/ready_gate.py --kpi artifacts/KPI_GATE.json --min-readiness 85
"""

from __future__ import annotations

import argparse
import json
import sys


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--kpi', required=True)
    ap.add_argument('--min-readiness', type=float, default=85.0)
    args = ap.parse_args(argv)

    data = _read_json(args.kpi) or {}
    rd = data.get('readiness', 0)
    try:
        r = float(rd)
    except Exception:
        r = 0.0
    # Accept 0..1 scale too
    if 0.0 <= r <= 1.0:
        r = r * 100.0
    r_int = int(r)
    min_req = int(args.min_readiness)
    status = 'PASS' if r >= float(min_req) else 'FAIL'
    print(f'event=ready_gate readiness={r_int} min={min_req} status={status}')
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())


