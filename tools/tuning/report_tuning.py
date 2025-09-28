import json
import os


def main(argv=None) -> int:
    with open('artifacts/TUNING_REPORT.json', 'r', encoding='ascii') as f:
        rep = json.load(f)
    lines = []
    lines.append('TUNING REPORT\n')
    lines.append('\n')
    lines.append('| verdict | max_delta_ratio | impact_cap_ratio | min_interval_ms | tail_age_ms | net_before | net_after | p95_after |\n')
    lines.append('|---------|-----------------|------------------|------------------|-------------|------------|-----------|-----------|\n')
    for c in rep.get('candidates', []):
        p = c['params']; a = c['metrics_after']; b = c['metrics_before']
        lines.append('| ' + c['verdict'] + ' | ' + '%.6f' % p['max_delta_ratio'] + ' | ' + '%.6f' % p['impact_cap_ratio'] + ' | ' + '%.6f' % p['min_interval_ms'] + ' | ' + '%.6f' % p['tail_age_ms'] + ' | ' + '%.6f' % b['net_bps'] + ' | ' + '%.6f' % a['net_bps'] + ' | ' + '%.6f' % a['order_age_p95_ms'] + ' |\n')
    md = ''.join(lines)
    path = 'artifacts/TUNING_REPORT.md'
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
    print('TUNING WROTE artifacts/TUNING_REPORT.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


