# Live-Prep Checklist (P0.3)

## Цель
Переход от shadow-режима к testnet и далее к canary live с минимальным риском.

## Pre-Deployment: Code & Tests

### Code Review
- [ ] Все PR для P0.3 прошли review (минимум 2 approvals)
- [ ] Нет открытых критических/блокирующих issues в Jira/GitHub
- [ ] Все linter warnings устранены (`pylint`, `mypy`, `ruff`)
- [ ] Coverage >= 15% (target gate), никаких регрессий

### Maker-Only Policy
- [ ] `maker_policy.py` покрыт unit-тестами (20+ кейсов)
- [ ] `calc_post_only_price()` корректно применяет offset и округление
- [ ] `check_price_crosses_market()` блокирует пересечения
- [ ] `round_qty()` и `check_min_qty()` работают для всех символов

### Execution Loop
- [ ] `execution_loop.py` применяет maker-only проверки перед отправкой ордеров
- [ ] Блокированные ордера логируются с `reason` (cross_price, min_qty, risk_limit)
- [ ] Метрики `mm_orders_blocked_total` инкрементируются
- [ ] Freeze drill → cancel_all идемпотентно

### Exchange Client
- [ ] `exchange_bybit.py` поддерживает `testnet=True` режим
- [ ] `get_symbol_filters()` возвращает детерминированные фильтры для shadow/testnet
- [ ] Все секреты маскируются в логах

### Secrets & ENV
- [ ] `EXCHANGE_ENV` правильно маппится на secret environments (shadow→dev, testnet→testnet, live→prod)
- [ ] `whoami` команда корректно отображает backend/secret_env
- [ ] Секреты для testnet загружены в SecretManager (или memory store для тестов)

### Observability
- [ ] Новые метрики `mm_orders_blocked_total{reason}`, `mm_post_only_adjustments_total`, `mm_maker_only_enabled` доступны в `/metrics`
- [ ] Структурные логи содержат `order_blocked` события с reason
- [ ] Health/ready endpoints отвечают корректно

### Tests
- [ ] **Unit**: 20+ тестов для maker_policy, secrets_env (все зелёные)
- [ ] **Integration**: testnet-режим, post-only проверки, freeze drill
- [ ] **E2E**: shadow и testnet-sim сценарии, byte-stable отчёты

---

## Testnet Smoke Tests

### Pre-requisites
- [ ] Testnet API keys настроены в SecretManager (`mm-bot/testnet/bybit`)
- [ ] `EXCHANGE_ENV=testnet` установлена
- [ ] Observability server запущен (`--obs --obs-port 8080`)

### Run Testnet Smoke
```bash
# Shadow mode (финальная проверка перед testnet)
python -m tools.live.exec_demo \
  --shadow \
  --symbols BTCUSDT \
  --iterations 20 \
  --maker-only \
  --post-only-offset-bps 1.5 \
  --obs --obs-port 8080

# Testnet mode (сухой запуск с фильтрами, но без реальных ордеров)
export EXCHANGE_ENV=testnet
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --network --testnet \
  --symbols BTCUSDT \
  --iterations 10 \
  --maker-only \
  --obs --obs-port 8080
```

### Verify Metrics (testnet smoke)
```bash
curl http://localhost:8080/metrics | grep mm_orders_blocked_total
curl http://localhost:8080/metrics | grep mm_maker_only_enabled
curl http://localhost:8080/metrics | grep mm_post_only_adjustments_total
```

### Acceptance Criteria (Testnet Smoke)
- [ ] Нет исключений/crashes
- [ ] Все ордера блокируются maker-only политикой (если spread узкий)
- [ ] `mm_orders_blocked_total{reason="cross_price"}` > 0 или `mm_orders_blocked_total{reason="min_qty"}` > 0
- [ ] `mm_maker_only_enabled == 1.0`
- [ ] Логи содержат `order_blocked` события с `reason`
- [ ] Freeze drill работает (если edge падает)

---

## Canary Live (Micro-Lots)

### Pre-requisites
- [ ] Testnet smoke успешен (все чеклисты выше пройдены)
- [ ] Канарейка деплоится в отдельный pod/namespace
- [ ] Live API keys настроены (`mm-bot/live/bybit`), доступны только для canary role
- [ ] `EXCHANGE_ENV=live` установлена
- [ ] `--maker-only=True` по умолчанию
- [ ] Алерты настроены в Prometheus/Alertmanager

### Canary Config
```bash
export EXCHANGE_ENV=live
export SECRETS_BACKEND=aws  # or memory for testing

python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --network \
  --symbols BTCUSDT \
  --iterations 100 \
  --maker-only \
  --post-only-offset-bps 2.0 \  # более консервативный оффсет
  --min-qty-pad 1.2 \             # более консервативный padding
  --max-inv 500 \                 # микролоты: $500 макс на символ
  --max-total 2000 \
  --obs --obs-port 8080
```

### Monitoring (First 24h)
- [ ] No crashes/exceptions в первые 30 минут
- [ ] `mm_orders_blocked_total` растёт (ордера блокируются корректно)
- [ ] `mm_orders_placed_total` > 0 (хотя бы несколько ордеров прошли)
- [ ] `mm_orders_filled_total` > 0 (хотя бы одна fill)
- [ ] `mm_freeze_events_total` == 0 (нет незапланированных заморозок)
- [ ] PnL в пределах ожидаемого (микролоты, поэтому PnL мал)
- [ ] Latency `mm_order_latency_ms` < 500ms (p99)

### Alerts (должны быть настроены до canary)
```yaml
# Example Prometheus alerts
- alert: MMHighOrderBlockRate
  expr: rate(mm_orders_blocked_total[5m]) > 0.5
  for: 10m
  annotations:
    summary: "High order block rate (maker-only rejections)"

- alert: MMUnexpectedFreeze
  expr: increase(mm_freeze_events_total[1h]) > 0
  annotations:
    summary: "Unexpected freeze event"

- alert: MMNoOrdersPlaced
  expr: rate(mm_orders_placed_total[10m]) == 0
  for: 30m
  annotations:
    summary: "No orders placed in 30 minutes"
```

### Go/No-Go Decision (24h Canary)
**Go Criteria:**
- [ ] Нет критических ошибок/crashes
- [ ] Freeze events == 0 (или только запланированные drills)
- [ ] Filled orders > 10
- [ ] PnL не ниже -$50 (микролоты)
- [ ] Latency p99 < 500ms
- [ ] Блокировки `cross_price`/`min_qty` работают корректно

**No-Go Criteria (rollback):**
- [ ] Crash/exception в production
- [ ] Неконтролируемый freeze (не drill)
- [ ] PnL ниже -$100 (для микролотов это критично)
- [ ] Latency p99 > 1000ms
- [ ] Ордера пересекают рынок (maker-only не работает)

---

## Soak Test (48h)

### Pre-requisites
- [ ] Canary 24h успешен
- [ ] Все алерты зелёные
- [ ] Логи не содержат errors/warnings

### Soak Config
- Увеличить `--max-inv` до $2000
- Увеличить `--max-total` до $10000
- Добавить больше символов (`--symbols BTCUSDT,ETHUSDT`)

### Monitoring (48h)
- [ ] Нет memory leaks (RSS stable)
- [ ] Нет connection leaks (проверить `/ready` endpoint)
- [ ] PnL стабилен (микропрофит или около нуля)
- [ ] Freeze drills работают корректно
- [ ] Filled orders > 100

### Go/No-Go Decision (48h Soak)
**Go:**
- [ ] Все метрики стабильны
- [ ] PnL >= -$200 (за 48h)
- [ ] Нет crashes/exceptions
- [ ] Готовность к масштабированию

**No-Go:**
- [ ] Любые критические ошибки
- [ ] PnL < -$500
- [ ] Latency деградирует со временем

---

## Rollout Plan

1. **Shadow (baseline):** 1 неделя, только мониторинг
2. **Testnet:** 3-5 дней, проверка фильтров и freeze drills
3. **Canary live (micro-lots):** 24h, $500/symbol, maker-only
4. **Soak (micro-lots):** 48h, $2000/symbol, 2-3 символа
5. **Scale-up (gradual):** +20% inventory каждые 2 дня, до production limits

---

## Rollback Plan

### Trigger Rollback If:
- Crash/exception в canary
- Freeze не отменяет ордера
- Ордера пересекают рынок (maker-only сломан)
- PnL < -$500 за 24h (для микролотов)

### Rollback Steps:
1. **Stop canary pod** (kubectl scale --replicas=0)
2. **Cancel all open orders** (через exchange UI или API)
3. **Verify positions closed** (flatten all positions if needed)
4. **Post-mortem:** анализ логов, метрик, причин
5. **Fix code → re-test shadow/testnet → re-deploy**

---

## KPI Targets (после rollout)

- **Uptime:** >= 99.5%
- **Latency (p99):** < 500ms
- **Fill rate:** >= 60% (для maker-only ордеров)
- **PnL (daily):** >= -0.1% от notional
- **Freeze events:** только запланированные drills
- **Order block rate:** < 10% от попыток (maker-only должен блокировать только при необходимости)

---

## Sign-Off

**Date:** _________

**Shadow Tests:** ☐ Pass  
**Testnet Smoke:** ☐ Pass  
**Canary 24h:** ☐ Pass  
**Soak 48h:** ☐ Pass  

**Approvals:**
- [ ] Quant Lead: ______________
- [ ] SRE Lead: ______________
- [ ] Risk Manager: ______________

**Final Go/No-Go:** ☐ Go ☐ No-Go

---

## Notes / Issues

_Записывайте любые наблюдения, инциденты, уроки здесь._

