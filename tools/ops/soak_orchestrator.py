#!/usr/bin/env python3
"""
Soak Orchestrator (shadow → canary → live-econ), stdlib-only.

- Hourly ticks for a configured number of hours
- Reads KPI/EDGE artifacts, evaluates status (CONTINUE/WARN/FAIL)
- Writes JSONL journal with hash-chain: {ts, phase, region, status, action, reason, prev_hash, hash}
- ASCII one-line log per tick with fixed key order
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from src.deploy.thresholds import get_phase_caps


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return {}


def _canon_dumps(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _compute_hash(rec_no_hash: Dict[str, Any]) -> str:
    payload = _canon_dumps(rec_no_hash).encode('ascii')
    return hashlib.sha256(payload).hexdigest()


def _read_last_hash(journal_path: str) -> str:
    try:
        with open(journal_path, 'rb') as f:
            last = b''
            for line in f:
                if line:
                    last = line
            if last:
                try:
                    rec = json.loads(last.decode('ascii', 'ignore'))
                    return str(rec.get('hash', 'GENESIS'))
                except Exception:
                    return 'GENESIS'
    except FileNotFoundError:
        return 'GENESIS'
    return 'GENESIS'


def _append_journal(journal_path: str, rec: Dict[str, Any]) -> None:
    # atomic append: write a single line; fsync file
    line = _canon_dumps(rec) + "\n"
    os.makedirs(os.path.dirname(journal_path), exist_ok=True)
    with open(journal_path, 'ab', buffering=0) as f:
        f.write(line.encode('ascii'))
        f.flush(); os.fsync(f.fileno())
    # best-effort dir fsync
    try:
        dfd = os.open(os.path.dirname(journal_path) or '.', os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass


def _eval_status(kpi: Dict[str, Any], edge: Dict[str, Any]) -> Tuple[str, str]:
    # Extract metrics with tolerant shapes
    readiness = kpi.get('readiness', 100.0)
    try:
        r = float(readiness)
        if 0.0 <= r <= 1.0:
            r *= 100.0
    except Exception:
        r = 100.0

    # edge metrics: root or total
    src = edge.get('total', edge)
    net_bps = float(src.get('net_bps', 3.0))
    taker = float(src.get('taker_ratio', src.get('taker_share_pct', 0.0)))
    lat = edge.get('latency', {}) if src is edge else {}
    p95 = float(lat.get('p95', 300.0))
    p99 = float(lat.get('p99', 400.0))

    # FAIL conditions (strict)
    if taker > 0.15:
        return 'FAIL', 'taker_ratio_gt_0.15'
    if p95 > 350.0:
        return 'FAIL', 'p95_gt_350ms'
    if p99 > 1.5 * max(1.0, p95):
        return 'FAIL', 'p99_gt_1.5x_p95'
    if r < 85.0:
        return 'FAIL', 'readiness_lt_85'

    # WARN conditions
    if net_bps < 2.0:
        return 'FAIL', 'net_bps_below_2.0'
    if 2.0 <= net_bps < 2.5:
        return 'WARN', 'net_bps_in_[2.0,2.5)'

    return 'CONTINUE', 'ok'


def _make_recommendation(status: str, reason: str) -> str:
    st = str(status)
    rs = str(reason)
    if st == 'WARN':
        if rs.startswith('net_bps_in_') or 'net_bps' in rs:
            return 'run TUNE_DRY: reduce impact_cap by 20% (see docs/runbooks/kpi.md#degrade)'
        return 'run TUNE_DRY (see docs/runbooks/kpi.md#degrade)'
    if st == 'FAIL':
        if rs == 'phase_taker_ceiling_exceeded' or 'taker_ratio' in rs:
            return 'rollback step: lower taker caps; disable strat if persists (see docs/runbooks/circuit_gate.md#triage)'
        if rs.startswith('p95_') or rs.startswith('p99_'):
            return 'rollback step: increase backoff; cancel tails (see docs/runbooks/full_stack.md#triage)'
        return 'rollback step: apply prev overlay (see docs/runbooks/full_stack.md#triage)'
    return ''


def _reason_code(status: str, reason: str) -> str:
    st = str(status)
    rs = str(reason)
    if st in ('CONTINUE', 'OK'):
        return 'OK'
    if st == 'WARN':
        if rs.startswith('net_bps_in_') or 'net_bps' in rs:
            return 'NET_BPS_LOW'
        return 'GEN_WARN'
    if st == 'FAIL':
        if rs == 'phase_taker_ceiling_exceeded' or 'taker_ratio' in rs:
            return 'TAKER_CEIL'
        if rs.startswith('p95_') or rs.startswith('p99_'):
            return 'P95_SPIKE'
        if rs == 'readiness_lt_85':
            return 'READINESS_LOW'
        return 'GEN_FAIL'
    return 'GEN'


def _consecutive_fails(journal_path: str, phase: str, region: str) -> int:
    cnt = 0
    try:
        with open(journal_path, 'r', encoding='ascii') as f:
            lines = f.read().splitlines()
    except Exception:
        lines = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            break
        if rec.get('phase') != phase or rec.get('region') != region:
            continue
        if rec.get('status') == 'FAIL':
            cnt += 1
        else:
            break
    return cnt


def _decide_action(status: str, journal_path: str, phase: str, region: str) -> str:
    if status == 'CONTINUE':
        return 'NONE'
    if status == 'WARN':
        return 'TUNE_DRY'
    # FAIL cascade
    prev = _consecutive_fails(journal_path, phase, region)
    if prev == 0:
        return 'ROLLBACK_STEP'
    if prev == 1:
        return 'DISABLE_STRAT'
    return 'REGION_STEP_DOWN'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', required=True, choices=['shadow','canary','live-econ'])
    ap.add_argument('--region', required=False, default='eu-west-1')
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--kpi-gate', default='artifacts/KPI_GATE.json')
    ap.add_argument('--edge-report', default='artifacts/EDGE_REPORT.json')
    ap.add_argument('--full-accept', action='store_true')
    ap.add_argument('--journal', default='artifacts/SOAK_JOURNAL.jsonl')
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args(argv)

    if args.full_accept:
        try:
            subprocess.run([sys.executable, 'tools/ci/full_stack_validate.py', '--accept', '--artifacts-dir', 'artifacts'], check=False)
        except Exception:
            pass

    for _tick in range(int(args.hours)):
        kpi = _read_json(args.kpi_gate)
        edge = _read_json(args.edge_report)
        status, reason = _eval_status(kpi, edge)
        # Phase caps
        caps = get_phase_caps(args.phase)
        caps_share = float(caps.get('order_share_ratio', 0.0))
        caps_capital = int(caps.get('capital_usd', 0))
        caps_taker = float(caps.get('taker_ceiling_ratio', 0.15))
        # Enforce phase taker ceiling (stricter than global)
        try:
            taker_cur = float(edge.get('taker_ratio', edge.get('taker_share_pct', 0.0)))
        except Exception:
            taker_cur = 0.0
        if taker_cur > caps_taker:
            status = 'FAIL'
            reason = 'phase_taker_ceiling_exceeded'
        action = _decide_action(status, args.journal, args.phase, args.region)

        # Optional action hooks (dry only)
        if args.dry and action == 'TUNE_DRY':
            try:
                subprocess.run([sys.executable, 'tools/tuning/apply_overlay.py', '--dry'], check=False)
            except Exception:
                pass

        prev = _read_last_hash(args.journal)
        recmd = _make_recommendation(status, reason)
        rcode = _reason_code(status, reason)
        base = {
            'action': action,
            'phase': str(args.phase),
            'prev_hash': str(prev),
            'reason': str(reason),
            'reason_code': str(rcode),
            'region': str(args.region),
            'status': str(status),
            'ts': _now_iso(),
            'caps': {'share': caps_share, 'capital_usd': caps_capital, 'taker_ceiling': caps_taker},
            'recommendation': recmd,
        }
        sha = _compute_hash({k: base[k] for k in base if k != 'hash'})
        rec = dict(base)
        rec['hash'] = sha
        _append_journal(args.journal, rec)

        now_int = int(datetime.now(timezone.utc).timestamp())
        # short recommendation in log with underscores
        short_rec = (recmd or '').replace(' ', '_')
        print(f"event=soak_tick phase={args.phase} status={status} action={action} reason_code={rcode} reason={reason} caps_share={caps_share:.6f} caps_capital={caps_capital} recommendation={short_rec} now={now_int}")

        # Best-effort snapshot on FAIL
        if status == 'FAIL':
            try:
                import subprocess
                r = subprocess.run(
                    [sys.executable, '-m', 'tools.ops.artifacts_snapshot_on_fail', '--fast'],
                    stdout=sys.stdout, stderr=sys.stderr, timeout=20, check=False
                )
                ok = (r.returncode == 0)
                snap_line = (r.stdout or '').strip().splitlines()[-1] if r.stdout else ''
                print(f"event=soak_fail_snapshot status={'OK' if ok else 'ERR'} info={snap_line}")
            except Exception:
                print("event=soak_fail_snapshot status=ERR info=exception")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())


