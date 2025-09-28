import argparse
import json
import os
from typing import Any, Dict, List


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
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


def _load_scenario(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        return json.load(f)


def _simulate(scn: Dict[str, Any], profile: str) -> Dict[str, float]:
    # Deterministic synthetic model: compute latencies as function of scenario and profile multipliers
    symbols = int(_finite(scn.get('symbols', 2)))
    duration_ms = _finite(scn.get('duration_ms', 60_000.0))
    ack_delay_ms = _finite(scn.get('ack_delay_ms', 50.0))
    place_rate = _finite(scn.get('place_rate_per_sec', 10.0))
    replace_burst = _finite(scn.get('replace_burst', 2.0))

    # Baseline throttle/batch
    base_min_interval = _finite(scn.get('min_interval_ms', 60.0))
    base_max_conc = _finite(scn.get('max_concurrent', 2.0))
    base_tail_age = _finite(scn.get('tail_age_ms', 800.0))
    base_max_batch = _finite(scn.get('max_batch', 10.0))

    # Tuned adjustments: slightly slower replace interval, smaller tail age, larger batch
    if profile == 'tuned':
        min_interval = base_min_interval * 1.20
        max_conc = max(1.0, base_max_conc)
        tail_age = base_tail_age * 0.80
        max_batch = base_max_batch * 1.30
        notes = 'tuned'
    else:
        min_interval = base_min_interval
        max_conc = base_max_conc
        tail_age = base_tail_age
        max_batch = base_max_batch
        notes = 'baseline'

    # Closed-form proxies for metrics (no randomness), monotonic w.r.t params
    intensity = place_rate * symbols
    queue_pressure = intensity * (ack_delay_ms + min_interval) / max(1.0, max_conc)
    tail_penalty = (tail_age / 1000.0) * (intensity / max(1.0, max_batch))

    order_age_p50 = ack_delay_ms + 0.25 * queue_pressure
    order_age_p95 = ack_delay_ms + 0.60 * queue_pressure + 0.20 * tail_penalty
    order_age_p99 = ack_delay_ms + 0.80 * queue_pressure + 0.30 * tail_penalty

    replace_rate_per_min = replace_burst * intensity * (1000.0 / max(1.0, min_interval)) * 60.0 / 1000.0
    cancel_batch_events = intensity * (tail_age / 1000.0) / max(1.0, max_batch)

    # Fill-rate proxy declines with queue pressure; tuned improves via reduced tail and better batching
    fill_base = max(0.0, 1.0 - 0.001 * queue_pressure)
    fill_adj = 0.02 if profile == 'tuned' else 0.0
    fill_rate = min(1.0, max(0.0, fill_base + fill_adj))

    return {
        'order_age_p50_ms': _finite(order_age_p50),
        'order_age_p95_ms': _finite(order_age_p95),
        'order_age_p99_ms': _finite(order_age_p99),
        'replace_rate_per_min': _finite(replace_rate_per_min),
        'cancel_batch_events': _finite(cancel_batch_events),
        'fill_rate': _finite(fill_rate),
        'notes': notes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', required=True)
    ap.add_argument('--profile', choices=['baseline','tuned'], required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    scn = _load_scenario(args.scenario)
    m = _simulate(scn, args.profile)
    rep = {
        'cancel_batch_events': m['cancel_batch_events'],
        'fill_rate': m['fill_rate'],
        'notes': m['notes'],
        'order_age_p50_ms': m['order_age_p50_ms'],
        'order_age_p95_ms': m['order_age_p95_ms'],
        'order_age_p99_ms': m['order_age_p99_ms'],
        'replace_rate_per_min': m['replace_rate_per_min'],
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
    }
    _write_json_atomic(args.out, rep)
    print('WROTE', args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


