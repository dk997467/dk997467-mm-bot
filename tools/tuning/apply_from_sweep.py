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


def _write_json_atomic(path: str, data: Any) -> None:
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


def _simulate(params: Dict[str, float]) -> Dict[str, float]:
    # Same deterministic model as sweep
    max_delta_ratio = _finite(params['max_delta_ratio'])
    impact_cap_ratio = _finite(params['impact_cap_ratio'])
    min_interval_ms = _finite(params['min_interval_ms'])
    tail_age_ms = _finite(params['tail_age_ms'])

    base_net = 3.0
    base_p95 = 320.0
    base_fill = 0.70
    base_replace = 300.0

    k_int = (min_interval_ms - 60.0) / 40.0
    replace = max(0.0, base_replace * (1.0 - 0.4 * k_int))
    p95 = max(0.0, base_p95 * (1.0 - 0.1 * k_int))
    net = base_net * (1.0 - 0.05 * k_int)

    k_tail = (800.0 - tail_age_ms) / 200.0
    p95 = max(0.0, p95 * (1.0 - 0.05 * k_tail))
    fill = min(1.0, base_fill * (1.0 + 0.05 * k_tail))

    k_imp = (0.10 - impact_cap_ratio) / 0.04
    net = net * (1.0 - 0.03 * k_imp)
    p95 = p95 * (1.0 - 0.02 * k_imp)

    k_delta = (0.15 - max_delta_ratio) / 0.05
    net = net * (1.0 - 0.04 * k_delta)
    p95 = p95 * (1.0 - 0.03 * k_delta)

    return {
        'net_bps': _finite(net),
        'order_age_p95_ms': _finite(p95),
        'fill_rate': _finite(fill),
        'replace_rate_per_min': _finite(replace),
    }


def main(argv=None) -> int:
    # Read sweep
    with open('artifacts/PARAM_SWEEP.json', 'r', encoding='ascii') as f:
        sweep = json.load(f)
    top = sweep.get('top3_by_net_bps_safe', [])
    if not top:
        print('TUNING no safe candidates')
        _write_json_atomic('artifacts/TUNING_REPORT.json', {'candidates': [], 'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'}})
        return 0

    # Baseline from first result
    baseline = (sweep.get('results') or [top[0]])[0]
    base_metrics = baseline.get('metrics', {})

    # Generate overlay YAML (single profile overlay_tune with first candidate)
    cand = top[0]['params']
    yaml_lines = [
        'profiles:\n',
        '  overlay_tune:\n',
        '    allocator:\n',
        '      smoothing:\n',
        f"        max_delta_ratio: {cand['max_delta_ratio']}\n",
        '    signals:\n',
        f"      impact_cap_ratio: {cand['impact_cap_ratio']}\n",
        '    latency_boost:\n',
        '      replace:\n',
        f"        min_interval_ms: {cand['min_interval_ms']}\n",
        '      tail_batch:\n',
        f"        tail_age_ms: {cand['tail_age_ms']}\n",
    ]
    os.makedirs('tools/tuning', exist_ok=True)
    with open('tools/tuning/overlay_profile.yaml', 'w', encoding='ascii', newline='') as f:
        for line in yaml_lines:
            f.write(line)
        if not yaml_lines[-1].endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())

    # Simulate short dry-run for each candidate
    candidates: List[Dict[str, Any]] = []
    for ent in top:
        params = ent['params']
        after = _simulate(params)
        before = base_metrics
        verdict = 'KEEP' if (after['order_age_p95_ms'] <= 350.0) else 'DROP'
        candidates.append({'params': params, 'metrics_after': after, 'metrics_before': before, 'verdict': verdict})

    rep = {
        'candidates': candidates,
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
    }
    _write_json_atomic('artifacts/TUNING_REPORT.json', rep)
    print('PATCH profile=overlay_tune')
    print('TUNING WROTE artifacts/TUNING_REPORT.json tools/tuning/overlay_profile.yaml')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


