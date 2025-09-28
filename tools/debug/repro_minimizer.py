import argparse
import json
import os
from typing import Any, Dict, Iterable, List, Set, Tuple

from .repro_runner import run_case


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _write_jsonl_atomic(path: str, events: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        for ev in events:
            s = json.dumps(ev, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
            f.write(s)
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _time_bounds(events: List[Dict[str, Any]]) -> Tuple[int, int]:
    ts = [int(ev.get('ts_ms', 0)) for ev in events if 'ts_ms' in ev]
    if not ts:
        return 0, 0
    ts.sort()
    return ts[0], ts[-1]


def _filter_time(events: List[Dict[str, Any]], t0: int, t1: int) -> List[Dict[str, Any]]:
    out = []
    for ev in events:
        v = int(ev.get('ts_ms', 0))
        if t0 <= v <= t1:
            out.append(ev)
    return out


def _symbols(events: List[Dict[str, Any]]) -> List[str]:
    s: Set[str] = set()
    for ev in events:
        sym = ev.get('symbol')
        if isinstance(sym, str) and sym:
            s.add(sym)
    return sorted(s)


def _filter_symbols(events: List[Dict[str, Any]], keep: Set[str]) -> List[Dict[str, Any]]:
    out = []
    for ev in events:
        sym = ev.get('symbol')
        if not isinstance(sym, str) or sym in keep or sym == '':
            out.append(ev)
    return out


def _event_types(events: List[Dict[str, Any]]) -> List[str]:
    s: Set[str] = set()
    for ev in events:
        t = ev.get('type')
        if isinstance(t, str) and t:
            s.add(t)
    return sorted(s)


def _filter_types(events: List[Dict[str, Any]], keep_types: Set[str]) -> List[Dict[str, Any]]:
    out = []
    for ev in events:
        t = ev.get('type')
        if not isinstance(t, str) or t in keep_types or t == '':
            out.append(ev)
    return out


def minimize(events_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    steps: List[str] = []
    base = _read_jsonl(events_path)
    baseline = run_case(events_path)
    if not baseline.get('fail'):
        # nothing to do
        steps.append('no-fail: baseline passes')
        return base, steps

    want_reason = baseline.get('reason', 'NONE')
    steps.append('baseline: fail=' + str(baseline.get('fail')) + ' reason=' + str(want_reason))

    # 1) Binary search by time window
    t0, t1 = _time_bounds(base)
    lo, hi = t0, t1
    best = base
    while lo < hi:
        mid = (lo + hi) // 2
        left = _filter_time(base, lo, mid)
        right = _filter_time(base, mid + 1, hi)
        # prefer narrower successful slice
        for label, candidate in (('left', left), ('right', right)):
            if not candidate:
                continue
            tmp_path = events_path + '.tmp.jsonl'
            _write_jsonl_atomic(tmp_path, candidate)
            r = run_case(tmp_path)
            if r.get('fail') and r.get('reason') == want_reason:
                steps.append('time-slice: kept ' + label + ' [' + str(lo if label=='left' else mid+1) + ',' + str(mid if label=='left' else hi) + ']')
                best = candidate
                if label == 'left':
                    hi = mid
                else:
                    lo = mid + 1
                break
        else:
            # cannot narrow further
            break

    # 2) Drop symbols
    keep_syms = set(_symbols(best))
    for sym in list(keep_syms):
        trial_keep = set(keep_syms)
        trial_keep.discard(sym)
        candidate = _filter_symbols(best, trial_keep)
        tmp_path = events_path + '.tmp.jsonl'
        _write_jsonl_atomic(tmp_path, candidate)
        r = run_case(tmp_path)
        if r.get('fail') and r.get('reason') == want_reason:
            steps.append('drop-symbol: ' + sym)
            keep_syms = trial_keep
            best = candidate

    # 3) Drop event types (cancel/replace/quote/trade etc.)
    keep_types = set(_event_types(best))
    for et in list(keep_types):
        trial_keep = set(keep_types)
        trial_keep.discard(et)
        candidate = _filter_types(best, trial_keep)
        tmp_path = events_path + '.tmp.jsonl'
        _write_jsonl_atomic(tmp_path, candidate)
        r = run_case(tmp_path)
        if r.get('fail') and r.get('reason') == want_reason:
            steps.append('drop-type: ' + et)
            keep_types = trial_keep
            best = candidate

    return best, steps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--events', required=True)
    ap.add_argument('--out-jsonl', default='artifacts/REPRO_MIN.jsonl')
    ap.add_argument('--out-md', default='artifacts/REPRO_MIN.md')
    args = ap.parse_args(argv)

    minimal, steps = minimize(args.events)
    _write_jsonl_atomic(args.out_jsonl, minimal)

    # Render MD
    lines = []
    lines.append('REPRO MINIMIZER\n')
    lines.append('\n')
    lines.append('Steps:\n')
    for s in steps:
        lines.append('- ' + s + '\n')
    lines.append('\n')
    lines.append('Result: events=' + str(len(minimal)) + '\n')
    # atomic write
    tmp = args.out_md + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(''.join(lines))
        if not lines or not ''.join(lines).endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(args.out_md):
        os.replace(tmp, args.out_md)
    else:
        os.rename(tmp, args.out_md)

    print('REPRO_MIN', args.out_jsonl)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


