# Grafana Dashboards для Soak Runner

## 📊 Доступные Dashboard

### `soak_runner_dashboard.json`

Мониторинг Continuous Soak Runner:
- **Heartbeat Age**: Время с последнего heartbeat (минуты)
- **Alert Debounce Status**: Логи debounce событий (ALERT_DEBOUNCED, ALERT_BYPASS_DEBOUNCE)
- **Export Status**: Redis export статусы (OK/SKIP)
- **Continuous Metrics**: Cycle metrics (verdict, windows, duration)
- **Alert Policy**: Активная политика алёртов по env

---

## 🔧 Установка

### Вариант A: Через Grafana UI

1. **Import Dashboard**:
   ```
   Settings → Data Sources → Import
   ```

2. **Upload JSON**:
   - Выбрать `soak_runner_dashboard.json`
   - Указать datasource (Prometheus + Loki)

3. **Variables**:
   - `$env`: окружение (dev/staging/prod)
   - `$exchange`: биржа (bybit/kucoin)

### Вариант B: Через API/Terraform

```bash
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @soak_runner_dashboard.json
```

---

## 📡 Datasource Requirements

### 1. **Prometheus** (для метрик)

**Heartbeat Age Panel требует Redis exporter:**

Если у вас уже есть [redis_exporter](https://github.com/oliver006/redis_exporter):
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
```

**Метрика для heartbeat:**
```promql
redis_key_timestamp{key=~".*:soak:runner:heartbeat"}
```

**Если Redis exporter недоступен:**
- Используйте **log-based мониторинг** (см. ниже)
- Heartbeat panel можно убрать или заменить на Text panel с инструкцией

### 2. **Loki** (для логов)

Все остальные panels используют Loki для анализа логов runner:

```yaml
# promtail.yml
scrape_configs:
  - job_name: soak-runner
    static_configs:
      - targets:
          - localhost
        labels:
          job: soak-runner
          __path__: /var/log/soak-runner/*.log
```

**Важные лог-паттерны:**
```
ALERT_DEBOUNCED level=CRIT ... remaining_min=73
ALERT_BYPASS_DEBOUNCE prev=WARN new=CRIT
EXPORT_STATUS summary=OK violations=SKIP
CONTINUOUS_METRICS verdict=CRIT windows=48
ALERT_POLICY env=prod min_severity=CRIT
```

---

## 🎯 Стратегии мониторинга

### Strategy A: Prometheus + Redis Exporter (Production)

**Pros:**
- Real-time heartbeat age metrics
- Grafana alerting на heartbeat TTL

**Setup:**
1. Deploy [redis_exporter](https://github.com/oliver006/redis_exporter)
2. Configure Prometheus scraping
3. Use `redis_key_timestamp` metric

**Alert Example (Prometheus rules):**
```yaml
groups:
  - name: soak-runner
    rules:
      - alert: SoakRunnerHeartbeatStale
        expr: (time() - redis_key_timestamp{key=~".*:soak:runner:heartbeat"}) > 600
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Soak runner heartbeat stale (>10 min)"
```

### Strategy B: Log-Based Monitoring (Minimal)

**Pros:**
- No additional exporters needed
- Works with existing Loki setup

**Setup:**
1. Ensure runner logs go to Loki (via Promtail or stdout→Loki)
2. Use log panels for all monitoring

**Heartbeat check (Loki query):**
```logql
{job="soak-runner"} |= "Heartbeat written"
```

**Alert via Loki ruler:**
```yaml
groups:
  - name: soak-runner-logs
    rules:
      - alert: SoakRunnerNoHeartbeat
        expr: |
          absent_over_time({job="soak-runner"} |= "Heartbeat written"[15m])
        for: 5m
        labels:
          severity: warning
```

---

## 🔍 Панели и интерпретация

### 1. **Runner Heartbeat Age**

**Цвета:**
- 🟢 Green (0-5 min): Healthy
- 🟡 Yellow (5-10 min): Degraded
- 🔴 Red (>10 min): Critical

**Troubleshooting:**
- Heartbeat >10 min → проверить runner process
- Metric отсутствует → проверить Redis exporter

### 2. **Alert Debounce Status**

**Ключевые логи:**
```
ALERT_DEBOUNCED ... remaining_min=73
```
→ Следующий алёрт возможен через 73 минуты

```
ALERT_BYPASS_DEBOUNCE prev=WARN new=CRIT
```
→ Severity усилился, debounce проигнорирован

**Действия:**
- Если `remaining_min` постоянно высокий → возможно застрял в CRIT
- Если много BYPASS → частые эскалации

### 3. **Export Status**

**Status values:**
- `summary=OK violations=OK` → всё в порядке
- `summary=SKIP reason=redis_unavailable` → Redis недоступен

**Действия:**
- SKIP с reason → проверить Redis connectivity
- Посмотреть `artifacts/state/last_export_status.json` для деталей

### 4. **Continuous Metrics**

**Verdict values:**
- `OK`: всё хорошо
- `WARN`: предупреждения
- `CRIT`: критические нарушения
- `UNCHANGED`: summary не изменился (skip export)
- `FAIL`: ошибка анализа

**Ключевые метрики:**
- `duration_ms`: время цикла (должно быть стабильным)
- `windows`: количество окон анализа
- `crit/warn/ok`: распределение статусов

### 5. **Alert Policy**

**Пример:**
```
ALERT_POLICY env=prod min_severity=CRIT source=alert-policy
```

**Интерпретация:**
- `source=alert-policy` → используется env-specific политика
- `source=alert-min-severity` → используется global fallback

---

## 🚀 Quick Start

**1. Local smoke test (without Grafana):**
```bash
# Generate fake CRIT summary
python -m tools.soak.generate_fake_summary --crit

# Run runner (logs to stdout)
make soak-alert-dry
```

**2. Check logs manually:**
```bash
# Heartbeat
grep "Heartbeat written" soak_runner.log

# Debounce ETA
grep "ALERT_DEBOUNCED" soak_runner.log

# Export status
grep "EXPORT_STATUS" soak_runner.log
```

**3. Import dashboard:**
- Open Grafana
- Import `soak_runner_dashboard.json`
- Select Prometheus + Loki datasources

---

## 📚 Дополнительные ресурсы

- **Redis Exporter**: https://github.com/oliver006/redis_exporter
- **Loki**: https://grafana.com/docs/loki/latest/
- **Promtail**: https://grafana.com/docs/loki/latest/clients/promtail/

**Questions?** See `SOAK_ANALYZER_GUIDE.md` for runner details.
