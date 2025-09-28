#!/usr/bin/env python3
"""
Auto rebuild trigger based on stamp age.
Exit 10 if rebuild is needed, 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3)
    ap.add_argument('--stamp', default='artifacts/RELEASE_STAMP.json')
    args = ap.parse_args(argv)

    if not os.path.exists(args.stamp):
        print('NEED_REBUILD=1')
        return 10
    try:
        with open(args.stamp, 'r', encoding='ascii') as f:
            data = json.load(f)
        ts = int(data.get('ts', 0))
    except Exception:
        ts = 0
    now = _now_ts()
    need = (now - ts) >= int(args.days) * 86400
    print(f"NEED_REBUILD={'1' if need else '0'}")
    return 10 if need else 0


if __name__ == '__main__':
    raise SystemExit(main())


