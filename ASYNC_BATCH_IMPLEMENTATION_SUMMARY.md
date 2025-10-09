# Async Batch Implementation Summary

**Дата**: 2025-01-08
**Цель**: Параллелизация + коалесинг команд для достижения P95(tick) < 200ms.

---

## ✅ Что реализовано

### 1. Command Bus (коалесинг)
- **Файл**: `src/execution/command_bus.py`
- **Функции**:
  - Коалесинг N cancel → 1 batch-cancel
  - Коалесинг M place → ≤2 batch-place (chunks по 20)
  - Feature flag: `async_batch.enabled`
  - Статистика: `total_commands`, `coalesce_stats`
- **Тесты**: `tests/unit/test_command_bus.py`

### 2. Batch API в Bybit Connector
- **Файл**: `src/connectors/bybit_rest.py`
- **API**:
  - `batch_cancel_orders(symbol, order_ids, client_order_ids)` → batch cancel
  - `batch_place_orders(symbol, orders)` → batch place
  - Fallback: если batch API недоступен, падает на sequential
- **Limits**: до 20 ордеров на batch (Bybit API limit)

### 3. Async Tick Orchestrator
- **Файл**: `src/strategy/async_tick_orchestrator.py`
- **Функции**:
  - Параллельная обработка символов (`asyncio.gather`)
  - Коалесинг команд через CommandBus
  - Метрики: `mm_tick_duration_ms`, `mm_cmd_coalesced_total`, `mm_exchange_req_ms`
  - Feature flag rollback: `async_batch.enabled=false` → sequential mode
- **Режимы**:
  - **Parallel**: до `max_parallel_symbols` символов одновременно
  - **Sequential**: старый последовательный режим (rollback)

### 4. Config и Feature Flag
- **Файлы**: `src/common/config.py`, `config.yaml`
- **Config Section**: `async_batch`
  - `enabled: true` - включить async batch
  - `max_parallel_symbols: 10` - max параллельных символов
  - `coalesce_cancel: true` - коалесинг cancel
  - `coalesce_place: true` - коалесинг place
  - `max_batch_size: 20` - max ордеров в batch
  - `tick_deadline_ms: 200` - целевой P95 tick duration

### 5. Metrics (Prometheus-ready)
- **mm_tick_duration_ms** (Histogram): продолжительность tick
- **mm_cmd_coalesced_total{op}** (Counter): число коалесированных команд
- **mm_exchange_req_ms{verb,api}** (Histogram): latency exchange requests

---

## 🧪 Тесты

### Performance Tests
**Файл**: `tests/perf/test_async_batch_performance.py`
- ✅ `test_async_batch_vs_sequential_performance` - async быстрее sequential
- ✅ `test_async_batch_p99_under_250ms` - P95<200ms, P99<250ms
- ✅ `test_network_calls_reduction` - ≥40% снижение сетевых вызовов
- ✅ `test_rollback_to_sequential` - rollback работает

### Unit Tests
**Файл**: `tests/unit/test_command_bus.py`
- ✅ `test_command_bus_coalesce_cancel` - N cancel → 1 batch
- ✅ `test_command_bus_coalesce_place` - M place → ≤2 batch
- ✅ `test_command_bus_legacy_mode` - legacy mode без коалесинга
- ✅ `test_command_bus_idempotency` - повторный flush не дублирует
- ✅ `test_command_bus_stats` - статистика коалесинга
- ✅ `test_command_bus_multi_symbol` - multi-symbol коалесинг

### Idempotency Tests
**Файл**: `tests/integration/test_idempotency_3x.py`
- ✅ `test_idempotency_3x_same_result` - 3 повтора дают одинаковый результат
- ✅ `test_idempotency_3x_no_flakiness` - 3 повтора без флаки
- ✅ `test_idempotency_3x_deterministic_order` - детерминированный порядок

---

## 📊 Acceptance Criteria

### Performance
- ✅ P95(tick_total) < 200 ms
- ✅ P99(tick_total) < 250 ms

### Network Efficiency
- ✅ Сетевые вызовы в тике уменьшены на ≥40%
- ✅ В одном тике: ≤1 batch-cancel и ≤2 batch-place на символ

### Reliability
- ✅ Все тесты зелёные ×3 (idempotency)
- ✅ Rollback: `async_batch.enabled=false` возвращает sequential

---

## 🚀 Как использовать

### 1. Enable Async Batch
```yaml
# config.yaml
async_batch:
  enabled: true
  max_parallel_symbols: 10
  coalesce_cancel: true
  coalesce_place: true
  tick_deadline_ms: 200
```

### 2. Интеграция в Runtime
```python
from src.strategy.async_tick_orchestrator import AsyncTickOrchestrator

# Initialize
orch = AsyncTickOrchestrator(ctx, connector, metrics)

# Process tick
result = await orch.process_tick(symbols, orderbooks)

# Check stats
stats = orch.get_stats()
print(f"P95 tick: {stats['p95_tick_ms']:.2f}ms")
```

### 3. Rollback (если нужно)
```yaml
# config.yaml
async_batch:
  enabled: false  # Rollback to sequential mode
```

---

## 🔧 Tuning

### Если P95 > 200ms:
1. Увеличить `max_parallel_symbols` (default: 10 → 20)
2. Уменьшить `tick_deadline_ms` (default: 200 → 150)
3. Проверить latency exchange API (`mm_exchange_req_ms`)

### Если сетевые вызовы не снижаются:
1. Проверить `coalesce_cancel` и `coalesce_place` (должны быть `true`)
2. Проверить `max_batch_size` (default: 20, не увеличивать - Bybit limit)

---

## 📈 Ожидаемое улучшение

### Before (Sequential):
- P95(tick): ~400-500ms (4+ символов)
- Сетевые вызовы: 4 symbols × (10 cancel + 10 place) = **80 calls**

### After (Async Batch):
- P95(tick): **~150-200ms** (speedup 2-3x)
- Сетевые вызовы: 4 batch-cancel + 4 batch-place = **8 calls** (90% reduction)

---

## ✅ Готово к production

Все acceptance criteria выполнены. Можно деплоить с `async_batch.enabled=true`.

При возникновении проблем: rollback через `async_batch.enabled=false`.

