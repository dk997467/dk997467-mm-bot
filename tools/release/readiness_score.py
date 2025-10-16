import argparse
import glob
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure src/ is in path for imports
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


def read_version() -> str:
    """Read version from VERSION file, fallback to 0.1.0"""
    version_file = Path(_repo_root) / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.1.0"


def get_deterministic_runtime() -> Dict[str, str]:
    """
    Get runtime info with support for CI_FAKE_UTC deterministic testing.
    
    Priority:
    1. CI_FAKE_UTC (for this script's deterministic testing)
    2. MM_FREEZE_UTC_ISO (for common runtime.py compatibility)
    3. Real UTC time
    """
    utc = os.getenv("CI_FAKE_UTC") or os.getenv("MM_FREEZE_UTC_ISO")
    if not utc:
        utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    version = read_version()
    
    return {
        "utc": utc,
        "version": version
    }


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _median(xs: List[float]) -> float:
    ys = sorted(_finite(x) for x in xs)
    n = len(ys)
    if n == 0:
        return 0.0
    m = n // 2
    if n % 2 == 1:
        return ys[m]
    return (ys[m - 1] + ys[m]) / 2.0


def _read_reports(dir_path: str) -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(os.path.join(dir_path, 'REPORT_SOAK_*.json')))[:]
    # use the last 7 by name order
    paths = paths[-7:]
    out = []
    for p in paths:
        try:
            with open(p, 'r', encoding='ascii') as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def _section_scores(reports: List[Dict[str, Any]]) -> Tuple[Dict[str, float], float]:
    edge_list = [_finite(r.get('edge_net_bps', 0.0)) for r in reports]
    p95_list = [_finite(r.get('order_age_p95_ms', 0.0)) for r in reports]
    tak_list = [_finite(r.get('taker_share_pct', 0.0)) for r in reports]

    edge_med = _median(edge_list)
    p95_med = _median(p95_list)
    tak_med = _median(tak_list)

    # Edge: full 30 at >= 2.5, linear below
    edge_score = 30.0 * max(0.0, min(1.0, edge_med / 2.5))
    # Latency: full 25 at <= 350, otherwise 25 * (350 / p95)
    lat_score = 25.0 * (1.0 if p95_med <= 350.0 else max(0.0, min(1.0, 350.0 / p95_med)))
    # Taker: full 15 at <= 15, otherwise 15 * (15 / taker)
    tak_score = 15.0 * (1.0 if tak_med <= 15.0 else max(0.0, min(1.0, 15.0 / max(tak_med, 1e-9))))

    # Guards: per day no breach if reg_guard.reason == 'NONE' and (no drift or drift.reason in ['','NONE'])
    ok_days = 0
    for r in reports:
        reg = str(((r.get('reg_guard') or {}).get('reason', 'NONE')))
        drift_reason = ''
        try:
            drift = r.get('drift') or {}
            drift_reason = str(drift.get('reason', 'NONE'))
        except Exception:
            drift_reason = 'NONE'
        no_breach = (reg == 'NONE') and (drift_reason in ('', 'NONE'))
        if no_breach:
            ok_days += 1
    guards_score = 10.0 * (ok_days / 7.0)

    # Chaos: expect field 'chaos_result' == 'OK' for all days
    chaos_ok = all(str(r.get('chaos_result', 'OK')) == 'OK' for r in reports)
    chaos_score = 10.0 if chaos_ok else 0.0

    # Tests: expect field 'bug_bash' == 'OK' for all days
    tests_ok = all('OK' in str(r.get('bug_bash', 'OK')) for r in reports)
    tests_score = 10.0 if tests_ok else 0.0

    sections = {
        'chaos': round(chaos_score, 6),
        'edge': round(edge_score, 6),
        'guards': round(guards_score, 6),
        'latency': round(lat_score, 6),
        'taker': round(tak_score, 6),
        'tests': round(tests_score, 6),
    }
    total = sum(sections.values())
    return sections, total


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _write_text_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(content)
        if not content.endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='artifacts')
    ap.add_argument('--out-json', default='artifacts/READINESS_SCORE.json')
    args = ap.parse_args(argv)

    reports = _read_reports(args.dir)
    sections, total = _section_scores(reports)

    # Simplified verdict: GO if perfect score (100.0), otherwise HOLD
    verdict = 'GO' if total == 100.0 else 'HOLD'
    
    # Build deterministic payload
    payload = {
        "runtime": get_deterministic_runtime(),
        "score": round(total, 6),
        "sections": sections,
        "verdict": verdict
    }
    
    # Write to file (using existing atomic write)
    _write_json_atomic(args.out_json, payload)

    # Write markdown report
    md_path = os.path.splitext(args.out_json)[0] + '.md'
    lines: List[str] = []
    lines.append('READINESS SCORE\n')
    lines.append('\n')
    lines.append('Result: ' + verdict + '  Score: ' + ('%.6f' % payload['score']) + '\n')
    lines.append('\n')
    lines.append('| section | score |\n')
    lines.append('|---------|-------|\n')
    for sec in ['edge', 'latency', 'taker', 'guards', 'chaos', 'tests']:
        lines.append('| ' + sec + ' | ' + ('%.6f' % float(sections.get(sec, 0.0))) + ' |\n')
    _write_text_atomic(md_path, ''.join(lines))
    
    # Print deterministic JSON to stdout (no whitespace, sorted keys)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


