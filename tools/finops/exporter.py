import json
import csv
import os
from typing import Dict, Any, List, Tuple


def _finite(x: Any) -> float:
    try:
        import math
        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def load_artifacts(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        d = json.load(f)
    # Validate minimal top-level keys
    for k in ("fees", "intraday_caps", "position_skew", "runtime"):
        if k not in d:
            raise ValueError("E_FINOPS_ART:missing:" + k)
    return d


def _sorted_symbols(d: Dict[str, Any]) -> List[str]:
    return sorted([str(k) for k in d.keys()])


def export_pnl_csv(art: Dict[str, Any], out_path: str) -> None:
    pnl = art.get('pnl', {})
    nb = pnl.get('net_bps', {})
    ts = pnl.get('taker_share_pct', {})
    age = pnl.get('order_age_p95_ms', {})
    syms = sorted(set(list(nb.keys()) + list(ts.keys()) + list(age.keys())))
    rows: List[Tuple[str, float, float, float]] = []
    for s in syms:
        rows.append((
            s,
            _finite(nb.get(s, 0.0)),
            _finite(ts.get(s, 0.0)),
            _finite(age.get(s, 0.0)),
        ))
    # TOTAL averages
    if rows:
        avg = lambda idx: (sum(r[idx] for r in rows) / float(len(rows)))
        rows.append(("TOTAL", avg(1), avg(2), avg(3)))
    _write_csv(out_path, ["symbol", "net_bps", "taker_share_pct", "order_age_p95_ms"], rows)


def export_fees_csv(art: Dict[str, Any], out_path: str) -> None:
    per_sym = (art.get('fees', {}) or {}).get('per_symbol_bps', {})
    syms = _sorted_symbols(per_sym)
    rows: List[Tuple[str, float]] = [(s, _finite(per_sym.get(s, 0.0))) for s in syms]
    if rows:
        rows.append(("TOTAL", sum(v for _, v in rows) / float(len(rows))))
    _write_csv(out_path, ["symbol", "fees_bps"], rows)


def export_turnover_csv(art: Dict[str, Any], out_path: str) -> None:
    tov = art.get('turnover', {}) or {}
    per_sym = tov.get('usd', {}) or {}
    syms = _sorted_symbols(per_sym)
    rows: List[Tuple[str, float]] = [(s, _finite(per_sym.get(s, 0.0))) for s in syms]
    total = _finite(tov.get('total_usd', sum(v for _, v in rows)))
    rows.append(("TOTAL", total))
    _write_csv(out_path, ["symbol", "turnover_usd"], rows)


def export_latency_csv(art: Dict[str, Any], out_path: str) -> None:
    lat = art.get('latency', {}) or {}
    p95 = lat.get('p95_ms', {}) or {}
    rr = lat.get('replace_rate_per_min', {}) or {}
    cb = lat.get('cancel_batch_events_total', {}) or {}
    syms = sorted(set(list(p95.keys()) + list(rr.keys()) + list(cb.keys())))
    rows: List[Tuple[str, float, float, float]] = []
    for s in syms:
        rows.append((
            s,
            _finite(p95.get(s, 0.0)),
            _finite(rr.get(s, 0.0)),
            _finite(cb.get(s, 0.0)),
        ))
    if rows:
        avg = lambda idx: (sum(r[idx] for r in rows) / float(len(rows)))
        total_cancel = sum(r[3] for r in rows)
        rows.append(("TOTAL", avg(1), avg(2), total_cancel))
    _write_csv(out_path, ["symbol", "p95_ms", "replace_rate_per_min", "cancel_batch_events_total"], rows)


def export_edge_csv(art: Dict[str, Any], out_path: str) -> None:
    ed = art.get('edge', {}) or {}
    g = ed.get('gross_bps', {}) or {}
    f = ed.get('fees_bps', {}) or {}
    adv = ed.get('adverse_bps', {}) or {}
    sl = ed.get('slippage_bps', {}) or {}
    inv = ed.get('inventory_bps', {}) or {}
    syms = sorted(set(list(g.keys()) + list(f.keys()) + list(adv.keys()) + list(sl.keys()) + list(inv.keys())))
    rows: List[Tuple[str, float, float, float, float, float, float]] = []
    for s in syms:
        gg = _finite(g.get(s, 0.0))
        ff = _finite(f.get(s, 0.0))
        aa = _finite(adv.get(s, 0.0))
        ss = _finite(sl.get(s, 0.0))
        ii = _finite(inv.get(s, 0.0))
        net = gg - ff - aa - ss + ii
        rows.append((s, gg, ff, aa, ss, ii, net))
    if rows:
        avg = lambda idx: (sum(r[idx] for r in rows) / float(len(rows)))
        rows.append(("TOTAL", avg(1), avg(2), avg(3), avg(4), avg(5), avg(6)))
    _write_csv(out_path, ["symbol", "gross_bps", "fees_bps", "adverse_bps", "slippage_bps", "inventory_bps", "net_bps"], rows)


def _write_csv(path: str, headers: List[str], rows: List[Tuple]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='ascii', newline='') as f:
        w = csv.writer(f, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
        w.writerow(headers)
        for r in rows:
            w.writerow(list(r))


