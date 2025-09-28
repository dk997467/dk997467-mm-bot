import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _read_json_safe(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


def _check_metrics(data: Optional[Dict[str, Any]]) -> List[str]:
    issues = []
    if not data:
        issues.append('metrics.json missing or invalid')
        return issues
    
    # Check edge net_bps from total
    edge = data.get('edge', {})
    net_bps = _finite(edge.get('net_bps', 0.0))
    if net_bps < 2.5:
        issues.append(f'net_bps {net_bps:.3f} < 2.5')
    
    # Check latency
    lat = data.get('latency', {})
    p95_ms = _finite(lat.get('p95_ms_avg', 0.0))
    if p95_ms > 350:
        issues.append(f'order_age_p95_ms {p95_ms:.1f} > 350')
    
    # Check taker share
    pnl = data.get('pnl', {})
    taker_pct = _finite(pnl.get('total_taker_share_pct', 0.0))
    if taker_pct > 15:
        issues.append(f'taker_share_pct {taker_pct:.1f} > 15')
    
    return issues


def _check_edge_report(data: Optional[Dict[str, Any]]) -> List[str]:
    issues = []
    if not data:
        issues.append('EDGE_REPORT.json missing or invalid')
        return issues
    
    total = data.get('total', {})
    net_bps = _finite(total.get('net_bps', 0.0))
    if net_bps < 2.5:
        issues.append(f'edge total net_bps {net_bps:.3f} < 2.5')
    
    return issues


def _check_reconcile(data: Optional[Dict[str, Any]]) -> List[str]:
    issues = []
    if not data:
        return []  # Optional
    
    totals = data.get('totals', {})
    for k in ['pnl_delta', 'fees_bps_delta', 'turnover_delta_usd']:
        delta = abs(_finite(totals.get(k, 0.0)))
        if delta > 1e-8:
            issues.append(f'reconcile {k} |{delta:.2e}| > 1e-8')
    
    return issues


def _check_region(data: Optional[Dict[str, Any]]) -> List[str]:
    issues = []
    if not data:
        return []  # Optional
    
    winner = data.get('winner', {})
    if not winner.get('region'):
        return []
    
    windows = data.get('windows', {})
    win_window = winner.get('window', '')
    if win_window not in windows:
        issues.append('region winner window not found')
        return issues
    
    m = windows[win_window]
    if _finite(m.get('net_bps', 0.0)) < 2.5:
        issues.append(f'region winner net_bps {m.get("net_bps", 0.0):.3f} < 2.5')
    if _finite(m.get('order_age_p95_ms', 0.0)) > 350:
        issues.append(f'region winner latency {m.get("order_age_p95_ms", 0.0):.1f} > 350')
    if _finite(m.get('taker_share_pct', 0.0)) > 15:
        issues.append(f'region winner taker_share {m.get("taker_share_pct", 0.0):.1f} > 15')
    
    return issues


def _find_latest_reconcile() -> Optional[str]:
    # Look for dist/finops/*/reconcile_report.json
    base = Path('dist/finops')
    if not base.exists():
        return None
    candidates = []
    for d in base.iterdir():
        if d.is_dir():
            rpt = d / 'reconcile_report.json'
            if rpt.exists():
                candidates.append(str(rpt))
    return candidates[-1] if candidates else None


def main() -> int:
    print('GO/NO-GO Assessment')
    print('===================')
    
    all_issues = []
    
    # Check metrics.json
    metrics = _read_json_safe('artifacts/metrics.json')
    issues = _check_metrics(metrics)
    if issues:
        print('METRICS:', ', '.join(issues))
        all_issues.extend(issues)
    else:
        print('METRICS: OK')
    
    # Check EDGE_REPORT.json
    edge = _read_json_safe('artifacts/EDGE_REPORT.json')
    issues = _check_edge_report(edge)
    if issues:
        print('EDGE:', ', '.join(issues))
        all_issues.extend(issues)
    else:
        print('EDGE: OK')
    
    # Check reconcile (optional)
    reconcile_path = _find_latest_reconcile()
    if reconcile_path:
        reconcile = _read_json_safe(reconcile_path)
        issues = _check_reconcile(reconcile)
        if issues:
            print('RECONCILE:', ', '.join(issues))
            all_issues.extend(issues)
        else:
            print('RECONCILE: OK')
    else:
        print('RECONCILE: n/a')
    
    # Check region (optional)
    region = _read_json_safe('artifacts/REGION_COMPARE.json')
    issues = _check_region(region)
    if issues:
        print('REGION:', ', '.join(issues))
        all_issues.extend(issues)
    elif region:
        print('REGION: OK')
    else:
        print('REGION: n/a')
    
    print()
    if all_issues:
        print('Issues found:', len(all_issues))
        for i in all_issues:
            print(' -', i)
        print('VERDICT=NO-GO')
    else:
        print('All checks passed')
        print('VERDICT=GO')
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
