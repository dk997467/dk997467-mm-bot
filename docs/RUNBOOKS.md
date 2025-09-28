## Release Route: Shadow→Canary→Live

## Chaos Soak (Failover Drill)

Steps:
- Run shadow-mode drill: `python -m tools.chaos.soak_failover --ttl-ms 1500 --renew-ms 500 --kill-at-ms 3000 --window-ms 6000`
- PASS if: takeover ≤ TTL+200ms; no dual leadership; idempotency hits > 0 and no duplicates; alert-storm counter = 0
- Observe Grafana (leader_state, order events) and Alertmanager; inhibit rules must suppress storms

### Phase 1: Shadow (30-60 min)
- Enable metrics/logs collection
- NO live orders, observation only  
- Monitor: latency, fills, edge components
- Validate: all systems responding, data flowing

### Phase 2: Canary (2-4 hours)
- Route 5-10% of volume through new version
- Full order lifecycle active
- Enforce GO/NO-GO thresholds:
  - net_bps ≥ 2.5
  - order_age_p95_ms ≤ 350
  - taker_share_pct ≤ 15
- Monitor reconciliation deltas |Δ| ≤ 1e-8

### Phase 3: Promote/Rollback
- **GO**: Gradual ramp to 100% over 1-2 hours
- **NO-GO**: Immediate rollback to previous version
- Alert channels: #trading-alerts, PagerDuty
- Dashboards: Grafana trading overview, edge metrics

### Commands
```bash
# Readiness check
make verify-links
make go-nogo

# Shadow phase
python -m tools.release.run_shadow_canary

# Canary validation  
make edge
make finops
make region
make go-nogo
```

## Failover SOP (Blue/Green)

Наблюдение лидера:
- Grafana/Prometheus: `leader_state{service="mm-bot"}` по инстансам
- Логи: `grep "LEADER"` — события acquire/renew/release

Ручное снятие лидерства (пример, адаптируйте для вашей среды):
```
redis-cli DEL mm:quoter:leader
```

Безопасный рестарт:
- Поставить silence на алерты S2+ по компоненту
- Рестартовать follower, дождаться стабильного `leader_state`
- Переключиться на новый лидер при необходимости

Чек:
- После kill одного инстанса takeover ≤ TTL; алертов ≥ S2 нет
- `leader_elections_total` увеличился не более чем на 1 за сценарий
RUNBOOKS (ASCII-only)

Kill-switch
- Purpose: мгновенно остановить размещение ордеров.
- Actions:
  - Set env and run preflight:
    - python -m cli.preflight
  - Toggle runtime kill (если поддерживается):
    - amtool silence add --author mm-bot --comment "kill" \
      --expires 30m alertname=RCValidatorFailed  # пример документации
  - Verify orders stopped (метрики/логи):
    - promtool query instant http://prom:9090 'sum(orders_active)'

Promote canary→live
- Purpose: повысить канарейку в live при норме метрик.
- Preconditions:
  - python -m cli.preflight
  - promtool check rules monitoring/alerts/mm_bot.rules.yml
  - promtool query instant http://prom:9090 'increase(pos_skew_breach_total[10m]) == 0'
- Actions:
  - amtool silence add --author mm-bot --comment "promote" alertname=CanaryGate --expires 10m
  - python -m tools.edge_audit --dry-run
  - Apply promote (организационная команда) и подтвердить:
    - promtool query instant http://prom:9090 'sum(quotes_placed_total)'

Rollback
- Purpose: откат с live на предыдущий релиз.
- Actions:
  - amtool silence add --author mm-bot --comment "rollback" --expires 15m alertname=EffectiveFeeJump
  - Выполнить развертывание предыдущего артефакта (организационно)
  - Проверка после отката:
    - promtool query instant http://prom:9090 'increase(snapshot_integrity_fail_total[5m])'

Diagnose (где смотреть)
- Artifacts (локально/CI):
  - type artifacts\metrics.json
  - type artifacts\rc_validator.json
- Prometheus:
  - promtool query instant http://prom:9090 'effective_fee_bps_now'
  - promtool query instant http://prom:9090 'pos_skew_breach_total'
- Alerts:
  - amtool alerts --alertmanager.url=http://am:9093

Edge quick-view
- Dry-run аудит пограничных состояний без побочных эффектов:
  - python -m tools.edge_audit --dry-run

SLO/SLA
- Latency targets:
  - promtool query instant http://prom:9090 'latency_ms_bucket_total'
- Order freshness:
  - promtool query instant http://prom:9090 'order_age_ms_bucket_total'

Alert SOP
- Check rules syntax:
  - promtool check rules monitoring/alerts/mm_bot.rules.yml
- Check Alertmanager config:
  - amtool check-config monitoring/alerts/alertmanager.yml
- Silence during storm (time-boxed):
  - amtool silence add --author mm-bot --comment "storm" --expires 15m alertname=EffectiveFeeJump
- Remove silence by ID when resolved:
  - amtool silence expire <silence_id>
 - Recovery события подавляют breach-алерты (см. inhibit_rules в alertmanager.yml)

Incident matrix and escalation
- Severity levels:
  - S0: full outage / trading halted
  - S1: severe degradation / risk breach probable
  - S2: partial impact / elevated errors
  - S3: minor incident / observation only
- Escalation path:
  - S0/S1: on-call → immediately page lead
  - S2: on-call handles, inform lead
  - S3: on-call notes, no immediate escalation

Storm suppression SOP
- Silence noisy alerts during mitigation (time-boxed):
  - amtool silence add --author mm-bot --comment "storm-suppress" \
    --expires 15m alertname=EffectiveFeeJump
- After mitigation, remove silence and verify metrics: promtool query instant http://prom:9090 'sum(quotes_placed_total)'


