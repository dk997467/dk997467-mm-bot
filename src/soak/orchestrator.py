from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .report import SoakReport


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _read_journal_lines(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, 'r', encoding='ascii') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def _calc_metrics(journal: List[Dict[str, Any]], phases: List[str]) -> Tuple[int, int, int, float, Dict[str, float], bool]:
    warn = 0
    fail = 0
    rollback_steps = 0
    # MTTR: average time from first FAIL to next OK (CONTINUE) in seconds
    mttr_samples: List[float] = []
    last_fail_ts: float = -1.0
    phase_uptime: Dict[str, float] = {p: 0.0 for p in phases}

    for rec in journal:
        try:
            st = str(rec.get('status', ''))
            ac = str(rec.get('action', ''))
            ts_s = str(rec.get('ts', ''))
            ph = str(rec.get('phase', ''))
            # parse ts ~ YYYY-MM-DDTHH:MM:SSZ
            try:
                ts = datetime.strptime(ts_s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                ts = 0.0
            if st == 'WARN':
                warn += 1
            if st == 'FAIL':
                fail += 1
                if last_fail_ts < 0:
                    last_fail_ts = ts
            if ac in ('ROLLBACK_STEP', 'DISABLE_STRAT', 'REGION_STEP_DOWN'):
                rollback_steps += 1
            # naive uptime: sum 1.0 per record per phase (acts as a counter of ticks)
            if ph in phase_uptime:
                phase_uptime[ph] = phase_uptime.get(ph, 0.0) + 1.0
            # MTTR sample when we see recovery to CONTINUE after FAIL
            if last_fail_ts >= 0 and st == 'CONTINUE':
                dt = max(0.0, ts - last_fail_ts)
                mttr_samples.append(dt)
                last_fail_ts = -1.0
        except Exception:
            continue

    mttr = (sum(mttr_samples) / len(mttr_samples)) if mttr_samples else 0.0
    canary_passed = True
    for rec in journal:
        if str(rec.get('phase', '')) == 'canary' and str(rec.get('status', '')) == 'FAIL':
            canary_passed = False
            break
    return warn, fail, rollback_steps, mttr, phase_uptime, canary_passed


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--shadow-hours', type=float, default=0.0)
    ap.add_argument('--canary-hours', type=float, default=0.0)
    ap.add_argument('--live-hours', type=float, default=0.0)
    ap.add_argument('--tz', default='Europe/Berlin')
    ap.add_argument('--out', default=None)
    ap.add_argument('--journal', default='artifacts/SOAK_JOURNAL.jsonl')
    args = ap.parse_args(argv)

    phases: List[Tuple[str, float]] = [
        ('shadow', float(args.shadow_hours)),
        ('canary', float(args.canary_hours)),
        ('live-econ', float(args.live_hours)),
    ]

    # simulate/drive phases: we only wait minimal time to respect CLI; actual ticks are recorded by existing orchestrator
    for name, hours in phases:
        if hours <= 0:
            continue
        # minimal sleep to simulate phase boundary for smoke; long runs rely on external orchestrator
        time.sleep(0.0)

    journal = _read_journal_lines(str(args.journal))
    warn, fail, rollbacks, mttr, uptime, canary_ok = _calc_metrics(journal, [p for p, _ in phases])

    rep = SoakReport(
        warn_count=warn,
        fail_count=fail,
        rollback_steps=rollbacks,
        mttr_sec=mttr,
        phase_uptime=uptime,
        canary_passed=canary_ok,
    )

    out = args.out
    if not out:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')
        out = str(Path('artifacts') / 'soak_reports' / f'soak_{ts}.json')
    Path(os.path.dirname(out) or '.').mkdir(parents=True, exist_ok=True)
    rep.dump_json(out)
    print(json.dumps(rep.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


