# Observability (P0.9)

## Обзор

P0.9 реализует **полную observability** для MM-Bot с использованием **stdlib-only** подхода:

- **Структурные JSON-логи** с детерминизмом и маскированием секретов
- **Health & Ready HTTP endpoints** для liveness/readiness проверок
- **Prometheus-compatible метрики** (Counter, Gauge, Histogram)
- **Интеграция** во все ключевые компоненты (ExecutionLoop, RiskMonitor)

---

## Компоненты

### 1. Structured JSON Logs (`tools/obs/jsonlog.py`)

**Формат:** Одна строка JSON на лог-запись.

**Поля:**
- `ts_utc`: Timestamp в ISO 8601 (UTC)
- `lvl`: Уровень лога (DEBUG, INFO, WARN, ERROR, CRITICAL)
- `name`: Имя логгера (e.g. `mm.execution`)
- `event`: Событие (e.g. `order_placed`)
- `**kwargs`: Дополнительные контекстные поля

**Детерминизм:**
- Sorted keys (алфавитный порядок)
- Компактные сепараторы (`,`, `:` без пробелов)
- Поддержка `MM_FREEZE_UTC_ISO` env var для фиксации времени

**Маскирование:**
- Поля `*key*`, `*secret*`, `token`, `password` → `abc*****`

**Пример:**

```json
{"component":"execution_loop","event":"order_placed","lvl":"INFO","name":"mm.execution","price":50000,"qty":0.001,"symbol":"BTCUSDT","ts_utc":"2025-10-27T10:00:00.000000Z"}
```

**API:**

```python
from tools.obs import jsonlog

logger = jsonlog.get_logger("mm.execution", default_ctx={"env": "prod"})
logger.info("order_placed", symbol="BTCUSDT", qty=0.001, price=50000)
logger.warning("freeze_triggered", reason="edge_below_threshold")
logger.error("order_placement_error", error="timeout")
```

---

### 2. Health & Ready Server (`tools/obs/health_server.py`)

**HTTP Endpoints:**

| Endpoint   | Status    | Description                          |
|------------|-----------|--------------------------------------|
| `/health`  | 200 OK    | Liveness check (process alive)       |
| `/ready`   | 200 / 503 | Readiness check (aggregated checks)  |
| `/metrics` | 200       | Prometheus metrics                   |

**Readiness Checks:**
- `state`: State layer ready
- `risk`: Risk monitor not frozen
- `exchange`: Exchange client ready

**Examples:**

```bash
# Health (always 200)
curl http://127.0.0.1:8080/health
# {"status":"ok"}

# Ready (200 if all OK, 503 if any fail)
curl http://127.0.0.1:8080/ready
# {"checks":{"exchange":true,"risk":true,"state":true},"status":"ok"}

# Metrics (Prometheus format)
curl http://127.0.0.1:8080/metrics
# # HELP mm_orders_placed_total Total number of orders placed
# # TYPE mm_orders_placed_total counter
# mm_orders_placed_total{symbol="BTCUSDT"} 42
```

**API:**

```python
from tools.obs import health_server

class MyHealthProviders:
    def state_ready(self) -> bool:
        return True
    def risk_ready(self) -> bool:
        return not risk_monitor.is_frozen()
    def exchange_ready(self) -> bool:
        return True

providers = MyHealthProviders()
server = health_server.start_server(
    host="127.0.0.1",
    port=8080,
    providers=providers,
    metrics_renderer=metrics.render_prometheus,
)

# ... do work ...

server.stop()
```

---

### 3. Metrics (`tools/obs/metrics.py`)

**Types:**
- **Counter**: Monotonically increasing (e.g. total orders)
- **Gauge**: Value that can go up/down (e.g. current edge)
- **Histogram**: Observations with buckets (e.g. latency distribution)

**Pre-registered Global Metrics:**

| Metric                        | Type      | Labels    | Description                            |
|-------------------------------|-----------|-----------|----------------------------------------|
| `mm_orders_placed_total`      | Counter   | `symbol`  | Total orders placed                    |
| `mm_orders_filled_total`      | Counter   | `symbol`  | Total orders filled                    |
| `mm_orders_rejected_total`    | Counter   | `symbol`  | Total orders rejected                  |
| `mm_order_latency_ms`         | Histogram | `symbol`  | Order placement latency (ms)           |
| `mm_edge_bps`                 | Gauge     | `symbol`  | Current edge in basis points           |
| `mm_risk_ratio`               | Gauge     | none      | Risk ratio (inventory / max_inventory) |
| `mm_freeze_events_total`      | Counter   | none      | Total freeze events                    |

**API:**

```python
from tools.obs import metrics

# Use pre-registered metrics
metrics.ORDERS_PLACED.inc(symbol="BTCUSDT")
metrics.ORDER_LATENCY.observe(12.5, symbol="BTCUSDT")
metrics.EDGE_BPS.set(2.5, symbol="ETHUSDT")
metrics.FREEZE_EVENTS.inc()

# Render all metrics
output = metrics.render_prometheus()
print(output)
```

**Histogram Buckets:**
- `mm_order_latency_ms`: `(1, 5, 10, 25, 50, 100, 250, 500)` ms

---

## Integration

### ExecutionLoop

Emits structured logs and metrics for:
- `order_placed`: Symbol, qty, price, latency
- `order_filled`: Symbol, qty, price
- `order_rejected`: Symbol, reason
- `freeze_triggered`: Symbol, edge, threshold
- `cancel_all_done`: Canceled count, trigger

### RiskMonitor

Emits structured logs and metrics for:
- `risk_freeze`: Reason, symbol, freezes_total

### CLI (`exec_demo.py`)

New flags:
- `--obs`: Enable observability server
- `--obs-host HOST`: Bind host (default: `127.0.0.1`)
- `--obs-port PORT`: Port (default: `8080`)

**Example:**

```bash
python -m tools.live.exec_demo \
  --shadow \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 100 \
  --obs \
  --obs-port 8080
```

**Output (stderr):**
```
[OBS] Server started: http://127.0.0.1:8080
[OBS] Endpoints: /health /ready /metrics
...
[OBS] Server stopped
```

---

## Operational Use Cases

### 1. Health Checks (Kubernetes/Docker)

**Liveness Probe:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
```

**Readiness Probe:**
```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
```

### 2. Prometheus Scraping

**prometheus.yml:**
```yaml
scrape_configs:
  - job_name: 'mm-bot'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### 3. Freeze Detection

**Alert on freeze:**
```promql
# Alert if frozen for > 1 minute
mm_freeze_events_total > 0 AND
time() - mm_last_order_placed_timestamp_seconds > 60
```

**Check ready status:**
```bash
# Returns 503 if frozen
curl -f http://127.0.0.1:8080/ready || echo "NOT READY"
```

### 4. Performance Monitoring

**Query latency percentiles:**
```promql
# P50 latency
histogram_quantile(0.50, rate(mm_order_latency_ms_bucket[5m]))

# P99 latency
histogram_quantile(0.99, rate(mm_order_latency_ms_bucket[5m]))
```

**Query fill rate:**
```promql
# Fill rate per symbol
rate(mm_orders_filled_total[5m]) / rate(mm_orders_placed_total[5m])
```

---

## Troubleshooting

### Common Scenarios

#### 1. System Frozen

**Symptoms:**
- `/ready` returns 503
- `mm_freeze_events_total` incremented

**Checks:**
```bash
curl http://127.0.0.1:8080/ready
# {"checks":{"exchange":true,"risk":false,"state":true},"status":"fail"}

curl http://127.0.0.1:8080/metrics | grep freeze
# mm_freeze_events_total 1
```

**Actions:**
1. Check structured logs for `freeze_triggered` event
2. Identify symbol/reason (edge degradation?)
3. Adjust edge_freeze_threshold or investigate market conditions

#### 2. High Latency

**Symptoms:**
- `mm_order_latency_ms` P99 > 500ms

**Checks:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep latency_ms_bucket
```

**Actions:**
1. Check network latency to exchange
2. Review structured logs for `order_placement_error`
3. Scale out or optimize exchange client

#### 3. No Orders Placed

**Symptoms:**
- `mm_orders_placed_total` stagnant

**Checks:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep orders_placed_total
# mm_orders_placed_total{symbol="BTCUSDT"} 0
```

**Actions:**
1. Check `/ready` (risk frozen?)
2. Review structured logs for `risk_freeze` or `order_rejected`
3. Verify symbols and inventory limits

---

## Testing

### Unit Tests
- `tests/unit/test_jsonlog_unit.py` — JSONLogger
- `tests/unit/test_metrics_unit.py` — Counter/Gauge/Histogram
- `tests/unit/test_health_server_unit.py` — Health/Ready endpoints

### Integration Tests
- `tests/integration/test_exec_obs_integration.py` — E2E with observability

### E2E Tests
- `tests/e2e/test_exec_shadow_e2e.py::test_scenario_6_observability_freeze_ready`

**Run all observability tests:**
```bash
pytest tests/unit/test_jsonlog_unit.py \
       tests/unit/test_metrics_unit.py \
       tests/unit/test_health_server_unit.py \
       tests/integration/test_exec_obs_integration.py \
       -v
```

---

## Performance

### Overhead

**Structured Logging:**
- ~5-10 μs per log entry (stdlib JSON encoder)
- Async I/O not implemented (future optimization)

**Metrics:**
- ~1-2 μs per counter increment (thread-safe)
- ~2-3 μs per histogram observation (bucket lookup)

**Health Server:**
- ~100-200 μs per HTTP request
- Non-blocking (background thread)

### Best Practices

1. **Log Sampling:** For high-frequency events (fills), sample or aggregate
2. **Metric Cardinality:** Limit label values (avoid user IDs, use symbols only)
3. **Health Endpoint Caching:** Cache `/ready` response for 1-2s to reduce overhead

---

## Future Enhancements (Post-P0.9)

1. **Async Logging:** Use asyncio for non-blocking log writes
2. **Log Rotation:** Implement size-based rotation for local files
3. **Tracing:** OpenTelemetry integration for distributed tracing
4. **Custom Metrics:** Allow user-defined metrics via config
5. **Alerting:** Built-in alerting rules (freeze → Slack/Telegram)

---

## References

- [Prometheus Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
- [12-Factor App: Logs as Event Streams](https://12factor.net/logs)
- [Kubernetes Liveness/Readiness Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

---

**Version:** P0.9  
**Last Updated:** 2025-10-27  
**Status:** ✅ Production Ready

