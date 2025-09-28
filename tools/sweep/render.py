import json
import os


def main(argv=None) -> int:
    with open('artifacts/PARAM_SWEEP.json', 'r', encoding='ascii') as f:
        rep = json.load(f)
    lines = []
    lines.append('PARAM SWEEP REPORT\n')
    lines.append('\n')
    lines.append('| max_delta_ratio | impact_cap_ratio | min_interval_ms | tail_age_ms | net_bps | order_age_p95_ms | fill_rate | replace_rate_per_min | SAFE |\n')
    lines.append('|-----------------|------------------|------------------|-------------|---------|-------------------|-----------|----------------------|------|\n')
    for r in rep['results']:
        p = r['params']; m = r['metrics']
        safe = (m['order_age_p95_ms'] <= 350.0)
        lines.append('| %.6f | %.6f | %.6f | %.6f | %.6f | %.6f | %.6f | %.6f | %s |\n' % (
            p['max_delta_ratio'], p['impact_cap_ratio'], p['min_interval_ms'], p['tail_age_ms'], m['net_bps'], m['order_age_p95_ms'], m['fill_rate'], m['replace_rate_per_min'], 'SAFE' if safe else 'UNSAFE'))
    md = ''.join(lines)
    path = 'artifacts/PARAM_SWEEP.md'
    tmp = path + '.tmp'
    os.makedirs('artifacts', exist_ok=True)
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(md)
        if not md.endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)
    print('PARAM_SWEEP WROTE artifacts/PARAM_SWEEP.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


