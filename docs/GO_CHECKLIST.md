GO-CHECKLIST (ASCII-only)

## FinOps Automation

## Region Canary

## Edge Audit

- One-shot CLI produces deterministic JSON/MD, TOTAL last in MD
- Math validated by unit tests; e2e matches goldens
- Report quickly highlights bottleneck component (gross/fees/adverse/slip/inventory)

## Release Wrap-up

- All reports fresh and within thresholds
- `make go-nogo` → VERDICT=GO
- `make verify-links` → [OK] all links valid
- Golden files unchanged since last validation
- Test suite passes: `make test-selected`

## Region Rollout

## Profiles

## Hardening

- ASCII logs lint passes
- Deterministic JSON writer lint passes
- Metrics labels low cardinality
- Invariants active (allocator/signals/throttle) and error codes one-line

- ECON profile active via ENV (`MM_PROFILE=econ_moderate`)
- E_CFG_* validation passes with profile applied
- Allocator smoothing deltas reduced (avg ratio ↓, p95 not worse)

- `REGION_COMPARE.json` fresh and deterministic
- Dry-run plan OK (all checks true), window matches
- Cooldown OK (`cooldown_ok=true`)
- Journal updated on apply and matches plan
- No side effects without `--apply`

## Soak Test

- Preflight OK (`python -m cli.preflight`)
- Soak runner executed (shadow/canary modes as needed)
- Daily soak report generated and deterministic
- Thresholds satisfied or verdict WARN/FAIL set appropriately
- Incidents S0–S1 = 0 during soak window

## Ops Week 1

- `tools.ops.daily_check` prints RESULT=OK on fresh artifacts
- `tools/ops/snapshot.sh` creates daily snapshot with all required files
- All outputs ASCII, deterministic JSON, LF termination

- Regions config parsed and validated (unique names, enabled is bool)
- Comparison outputs deterministic JSON/MD (byte-for-byte)
- Winner satisfies thresholds; tie by net_bps resolved by lower latency
- Switch script prints correct dry-run plan; --apply is no-op

- Export CSV/JSON are deterministic (repeat run => byte-for-byte identical)
- Reconcile passes on fixture (all deltas 0.0) or within tolerance (|delta| <= 1e-8)
- Artifacts under `dist/finops/<YYYYMMDD_Z>`; LF line endings

- [ ] Run RC preflight: python -m cli.preflight
- [ ] Check ENV: echo %MM_ENV% && echo %MM_CONFIG_PATH%
- [ ] Config parse: type %MM_CONFIG_PATH%
- [ ] Prom rules syntax: promtool check rules monitoring/alerts/mm_bot.rules.yml
- [ ] Alerts reachable: amtool alerts --alertmanager.url=http://am:9093
- [ ] Canary metrics healthy: promtool query instant http://prom:9090 'increase(pos_skew_breach_total[10m]) == 0'
- [ ] Caps inactive: promtool query instant http://prom:9090 'intraday_caps_breached == 0'
- [ ] Fees sane: promtool query instant http://prom:9090 'effective_fee_bps_now'
- [ ] Tier distance: promtool query instant http://prom:9090 'fee_tier_distance_usd'
- [ ] Edge audit dry-run: python -m tools.edge_audit --dry-run
- [ ] Artifacts present: type artifacts\metrics.json
- [ ] RC report present: type artifacts\rc_validator.json
- [ ] Canary gate open: promtool query instant http://prom:9090 'canary_gate_open == 1'
- [ ] Orders not stuck: promtool query instant http://prom:9090 'sum(order_age_ms_bucket_total)'
- [ ] Fill-rate OK: promtool query instant http://prom:9090 'cost_fillrate_ewma'
- [ ] Latency SLO: promtool query instant http://prom:9090 'latency_ms_p95_blue'
- [ ] No alerts firing: amtool alerts --alertmanager.url=http://am:9093 | findstr firing
- [ ] Budget available: promtool query instant http://prom:9090 'portfolio_budget_available_usd'
- [ ] HWM updated: promtool query instant http://prom:9090 'allocator_hwm_equity_usd'
- [ ] Promote command staged: amtool silence add --author mm-bot --comment "promote" alertname=CanaryGate --expires 10m
- [ ] Rollback plan staged: amtool silence add --author mm-bot --comment "rollback" alertname=EffectiveFeeJump --expires 15m
- [ ] Final preflight: python -m cli.preflight
- [ ] Promote now (org step), then verify quotes: promtool query instant http://prom:9090 'sum(quotes_placed_total)'


Snapshot and archive (deterministic)
- [ ] Create prom snapshot (ASCII-only):
  python - <<'PY'
import sys
import urllib.request
url = 'http://prom:9090/api/v1/targets'
data = urllib.request.urlopen(url, timeout=5).read().decode('utf-8')
open('prom_snapshot.txt','w',encoding='utf-8',newline='\n').write(data)
print('ok')
PY
- [ ] Archive artifacts to dist/canary_<ts>.tar.gz:
  python - <<'PY'
import os, tarfile, time
ts = int(time.time())
os.makedirs('dist', exist_ok=True)
name = f'dist/canary_{ts}.tar.gz'
with tarfile.open(name, 'w:gz') as tar:
    for p in ['artifacts/metrics.json','artifacts/rc_validator.json','prom_snapshot.txt','REPORT_CANARY.md']:
        if os.path.exists(p):
            tar.add(p, arcname=os.path.basename(p))
print(name)
PY

- [ ] Atomic writer check: python tools/ci/check_atomic_writer.py
- [ ] Monitoring sanity: убедиться, что экспортируемые метрики не содержат NaN/Inf
- [ ] Sizing trace стабильна: std(|delta_capped|) < std(|delta_raw|) и snapshot == golden (tests/e2e/test_sizing_trace.py). Числа формата ^-?\d+\.\d{6}$, файл ASCII, заканчивается \n.

Backtest Pipe
- [ ] Backtest: отчёты JSON/MD детерминированы (ASCII, sort_keys, compact), атомарная запись
- [ ] Backtest: повторный запуск cli run/wf на одинаковых входах → байт-в-байт отчёты
- [ ] Backtest: фикстурные пороги выдержаны (net_bps ≥ 2.5, taker_share_pct ≤ 15, order_age_p95_ms ≤ 350)

Micro Signals
- [ ] markout улучшился или adverse снизился на фикстуре, при том же риске
- [ ] impact cap соблюдён (≤ 10% per-tick)
- [ ] snapshot `tests/golden/micro_effect_case1.out` совпадает байт-в-байт

HA Failover
- [ ] leader_elections_total не прыгает > 1 за сценарий
- [ ] нет одновременных двух лидеров
- [ ] order_idem_hits_total > 0 на повторных операциях (smoke)

Investor Package
- [ ] Экспорты CSV/JSON детерминированы (ASCII, \n), TOTAL последней строкой
- [ ] Deck/SOP воспроизводимы байт-в-байт
- [ ] Поля и ключи согласованы с artifacts

Finalize artifacts
- [ ] Unified metrics export: python -m tools.artifacts.dump_metrics_json успешно создал файл
- [ ] Детерминизм: повторный запуск даёт байт-в-байт идентичный результат (git diff пуст)
- [ ] Ключи payload в алфавитном порядке; runtime.utc без миллисекунд (YYYY-MM-DDTHH:MM:SSZ)

Config hygiene
- [ ] cfg.describe() даёт стабильный дамп (байт-в-байт на одинаковом конфиге)
- [ ] Нет legacy-ключей в prod-конфигах (bias_cap, fee_bias_cap, fee_bias_cap_bps)

Multi-Strategy Mux
- [ ] MUX: hysteresis 60s держит режим; golden snapshot совпадает; суммы весов = 1; caps соблюдены; детерминизм на одинаковом входе



- Latency e2e:
  - P95_AFTER ≤ 350ms and ≤ P95_BEFORE
  - Fill-rate AFTER ≥ BEFORE
  - Golden snapshot `tests/golden/latency_queue_case1.out` matches byte-for-byte
  - replace_allowed < replace_attempts

- Live Sim:
  - net_bps ≥ 2.5
  - taker_share_pct ≤ 15
  - order_age_p95_ms ≤ 350
  - JSON/MD deterministic and match goldens
