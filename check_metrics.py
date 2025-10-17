#!/usr/bin/env python3
import json

snap = json.load(open('artifacts/soak/latest/POST_SOAK_SNAPSHOT.json'))
kpi = snap['kpi_last8']

print('=== Last 8 KPIs ===')
print(f'risk_ratio.mean: {kpi["risk_ratio"]["mean"]:.4f} (target: <=0.40)')
print(f'maker_taker_ratio.mean: {kpi["maker_taker_ratio"]["mean"]:.4f} (target: >=0.80)')
print(f'net_bps.mean: {kpi["net_bps"]["mean"]:.2f} (target: >=2.9)')
print(f'p95_latency_ms.mean: {kpi["p95_latency_ms"]["mean"]:.1f} (target: <=340)')
print()
print(f'verdict: {snap["verdict"]}')
print(f'freeze_ready: {snap["freeze_ready"]}')
print(f'pass_count_last8: {snap["pass_count_last8"]}')
print()
print('=== Success Bar Check ===')
success = {
    'risk <= 0.40': kpi["risk_ratio"]["mean"] <= 0.40,
    'maker_taker >= 0.80': kpi["maker_taker_ratio"]["mean"] >= 0.80,
    'net_bps >= 2.9': kpi["net_bps"]["mean"] >= 2.9,
    'p95_latency <= 340': kpi["p95_latency_ms"]["mean"] <= 340,
}

for check, passed in success.items():
    status = '[OK]' if passed else '[FAIL]'
    print(f'{status} {check}')

all_passed = all(success.values())
print()
if all_passed:
    print('[OK] ALL SUCCESS BAR CHECKS PASSED')
else:
    print('[FAIL] Some checks failed')

