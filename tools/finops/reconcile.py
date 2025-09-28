import csv
import json
import os
import sys
from typing import Dict, Any, Tuple


def _finite(x: Any) -> float:
    try:
        import math
        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def _read_exchange_csv(path: str) -> Dict[str, Dict[str, float]]:
    data: Dict[str, Dict[str, float]] = {}
    with open(path, 'r', encoding='ascii', newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            sym = str(row.get('symbol', '')).strip()
            if not sym:
                continue
            if sym.upper() == 'TOTAL':
                # Skip aggregate rows; totals are computed from by-symbol deltas
                continue
            sym_d = data.setdefault(sym, {})
            sym_d['pnl'] = _finite(row.get('pnl', 0.0))
            sym_d['fees_bps'] = _finite(row.get('fees_bps', 0.0))
            sym_d['turnover_usd'] = _finite(row.get('turnover_usd', 0.0))
    return data


def _load_artifacts(artifacts_path: str) -> Dict[str, Any]:
    with open(artifacts_path, 'r', encoding='ascii') as f:
        art = json.load(f)
    return art


def _artifacts_totals_by_symbol(art: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    # Map to exchange fields: pnl -> pnl from edge.net_bps, fees_bps from fees.per_symbol_bps, turnover_usd from turnover.usd
    pnl_map = (art.get('edge', {}) or {}).get('net_bps', {}) or {}
    fees_map = (art.get('fees', {}) or {}).get('per_symbol_bps', {}) or {}
    tov_map = (art.get('turnover', {}) or {}).get('usd', {}) or {}
    syms = set(list(pnl_map.keys()) + list(fees_map.keys()) + list(tov_map.keys()))
    out: Dict[str, Dict[str, float]] = {}
    for s in syms:
        out[s] = {
            'pnl': _finite(pnl_map.get(s, 0.0)),
            'fees_bps': _finite(fees_map.get(s, 0.0)),
            'turnover_usd': _finite(tov_map.get(s, 0.0)),
        }
    return out


def _merge_symbols(a: Dict[str, Dict[str, float]], b: Dict[str, Dict[str, float]]) -> Tuple[Dict[str, Dict[str, float]], list]:
    syms = sorted(set(list(a.keys()) + list(b.keys())))
    return {s: {
        'a_pnl': _finite(a.get(s, {}).get('pnl', 0.0)),
        'b_pnl': _finite(b.get(s, {}).get('pnl', 0.0)),
        'a_fees_bps': _finite(a.get(s, {}).get('fees_bps', 0.0)),
        'b_fees_bps': _finite(b.get(s, {}).get('fees_bps', 0.0)),
        'a_turnover_usd': _finite(a.get(s, {}).get('turnover_usd', 0.0)),
        'b_turnover_usd': _finite(b.get(s, {}).get('turnover_usd', 0.0)),
    } for s in syms}, syms


def _compute_deltas(merged: Dict[str, Dict[str, float]], syms: list) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    by_symbol: Dict[str, Dict[str, float]] = {}
    totals = {'pnl_delta': 0.0, 'fees_bps_delta': 0.0, 'turnover_delta_usd': 0.0}
    for s in syms:
        d = merged[s]
        pnl_delta = _finite(d['a_pnl'] - d['b_pnl'])
        fees_delta = _finite(d['a_fees_bps'] - d['b_fees_bps'])
        tov_delta = _finite(d['a_turnover_usd'] - d['b_turnover_usd'])
        by_symbol[s] = {
            'fees_bps_delta': fees_delta,
            'pnl_delta': pnl_delta,
            'turnover_delta_usd': tov_delta,
        }
        totals['pnl_delta'] = _finite(totals['pnl_delta'] + pnl_delta)
        totals['fees_bps_delta'] = _finite(totals['fees_bps_delta'] + fees_delta)
        totals['turnover_delta_usd'] = _finite(totals['turnover_delta_usd'] + tov_delta)
    return by_symbol, totals


def _runtime_meta(art: Dict[str, Any]) -> Dict[str, str]:
    rt = (art.get('runtime') or {})
    utc = str(rt.get('utc', ''))
    version = str(rt.get('version', ''))
    return {'utc': utc, 'version': version}


def reconcile(artifacts_path: str, exchange_dir: str) -> Dict[str, Any]:
    art = _load_artifacts(artifacts_path)
    exh_path = os.path.join(exchange_dir, 'combined.csv')
    # The exchange_dir may provide split files; attempt to combine from fees.csv/pnl.csv/turnover.csv if combined not found.
    data: Dict[str, Dict[str, float]]
    if os.path.exists(exh_path):
        data = _read_exchange_csv(exh_path)
    else:
        # Try merge from separate files
        data = {}
        for fname in ('pnl.csv', 'fees.csv', 'turnover.csv'):
            p = os.path.join(exchange_dir, fname)
            if not os.path.exists(p):
                continue
            part = _read_exchange_csv(p)
            for s, vals in part.items():
                d = data.setdefault(s, {})
                for k, v in vals.items():
                    # Keep latest occurrence, fields missing default to 0.0
                    d[k] = _finite(v)
        # Normalize missing fields
        for s in list(data.keys()):
            d = data[s]
            d['pnl'] = _finite(d.get('pnl', 0.0))
            d['fees_bps'] = _finite(d.get('fees_bps', 0.0))
            d['turnover_usd'] = _finite(d.get('turnover_usd', 0.0))

    art_map = _artifacts_totals_by_symbol(art)
    merged, syms = _merge_symbols(art_map, data)
    by_symbol, totals = _compute_deltas(merged, syms)
    # Sort by_symbol keys
    by_symbol_sorted = {k: by_symbol[k] for k in sorted(by_symbol.keys())}
    report: Dict[str, Any] = {
        'by_symbol': by_symbol_sorted,
        'runtime': _runtime_meta(art),
        'totals': totals,
    }
    return report


def render_reconcile_md(report: Dict[str, Any]) -> str:
    # Fixed ASCII table
    lines = []
    lines.append('Reconcile Report\n')
    lines.append('\n')
    lines.append('| symbol | pnl_delta | fees_bps_delta | turnover_delta_usd |\n')
    lines.append('|--------|-----------|----------------|--------------------|\n')
    for sym in sorted(report.get('by_symbol', {}).keys()):
        d = report['by_symbol'][sym]
        lines.append('| ' + sym + ' | ' + _fmt(d.get('pnl_delta')) + ' | ' + _fmt(d.get('fees_bps_delta')) + ' | ' + _fmt(d.get('turnover_delta_usd')) + ' |\n')
    lines.append('| TOTAL | ' + _fmt(report.get('totals', {}).get('pnl_delta')) + ' | ' + _fmt(report.get('totals', {}).get('fees_bps_delta')) + ' | ' + _fmt(report.get('totals', {}).get('turnover_delta_usd')) + ' |\n')
    return ''.join(lines)


def _fmt(x: Any) -> str:
    v = _finite(x)
    # Deterministic formatting with 6 decimals
    return ('%.6f' % v)


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)



