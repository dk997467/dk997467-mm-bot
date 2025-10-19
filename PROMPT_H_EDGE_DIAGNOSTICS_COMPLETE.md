# PROMPT H — Диагностика «минусового edge» в отчёте — COMPLETE

## Цель
Добавить диагностическую информацию в `EDGE_REPORT.json`, чтобы быстро понимать причины отрицательного `net_bps` и анализировать блокировки.

## Реализация

### 1. Component Breakdown (`tools/reports/edge_metrics.py`)

Добавлена функция `compute_component_breakdown()` для расчёта компонент net_bps:

```python
def compute_component_breakdown(totals: Dict[str, Any]) -> Dict[str, float]:
    """
    Compute component breakdown of net_bps.
    
    Formula (approximate):
        net_bps = gross_bps - fees_eff_bps - slippage_bps - adverse_bps - inventory_bps
    
    Returns:
        Dict with all component values (gross, fees, slippage, adverse, inventory, net)
    """
```

**Компоненты:**
- `gross_bps`: Валовая доходность
- `fees_eff_bps`: Эффективные комиссии
- `slippage_bps`: Проскальзывание
- `adverse_bps`: Неблагоприятный отбор
- `inventory_bps`: Инвентарный риск
- `net_bps`: Чистая доходность

### 2. Negative Edge Drivers (`tools/reports/edge_metrics.py`)

Добавлена функция `compute_neg_edge_drivers()` для идентификации топ-2 компонент, вносящих наибольший вклад в отрицательный net_bps:

```python
def compute_neg_edge_drivers(component_breakdown: Dict[str, float]) -> List[str]:
    """
    Identify top-2 components contributing to negative net_bps.
    
    Returns list of component names sorted by absolute contribution (descending).
    Only returns if net_bps is negative.
    """
```

**Логика:**
- Активируется только при `net_bps < 0`
- Сортирует негативные компоненты (fees, slippage, adverse, inventory) по абсолютному значению
- Возвращает топ-2 драйвера убытков

**Пример:**
```json
{
  "net_bps": -2.5,
  "neg_edge_drivers": ["slippage_bps", "adverse_bps"]
}
```

### 3. Block Reasons Statistics (`tools/reports/edge_metrics.py`)

Добавлена функция `compute_block_reasons()` для анализа блокировок из `audit.jsonl`:

```python
def compute_block_reasons(audit_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Compute block reasons statistics from audit.jsonl.
    
    Returns dict with structure:
        {
            "min_interval": {"count": N, "ratio": r},
            "concurrency": {"count": N, "ratio": r},
            "risk": {"count": N, "ratio": r},
            "throttle": {"count": N, "ratio": r}
        }
    """
```

**Метрики:**
- `count`: Количество блокировок по каждой причине
- `ratio`: Доля блокировок от общего числа

**Пример:**
```json
{
  "block_reasons": {
    "min_interval": {"count": 3, "ratio": 0.6},
    "concurrency": {"count": 1, "ratio": 0.2},
    "risk": {"count": 1, "ratio": 0.2},
    "throttle": {"count": 0, "ratio": 0.0}
  }
}
```

### 4. Updated EDGE_REPORT Structure

Расширена структура `totals` в `EDGE_REPORT.json`:

```json
{
  "totals": {
    "net_bps": -2.5,
    "gross_bps": 5.0,
    "fees_eff_bps": 2.0,
    // ... (existing fields) ...
    
    // PROMPT H: Diagnostics
    "component_breakdown": {
      "gross_bps": 5.0,
      "fees_eff_bps": 2.0,
      "slippage_bps": 3.5,
      "adverse_bps": 2.5,
      "inventory_bps": 0.5,
      "net_bps": -2.5
    },
    "neg_edge_drivers": ["slippage_bps", "adverse_bps"],
    "block_reasons": {
      "min_interval": {"count": 3, "ratio": 0.6},
      "concurrency": {"count": 1, "ratio": 0.2},
      "risk": {"count": 1, "ratio": 0.2},
      "throttle": {"count": 0, "ratio": 0.0}
    }
  }
}
```

### 5. Updated Marker (`tools/reports/edge_report.py`)

Изменён маркер для CI/CD мониторинга:

```python
# До:
print("\n| edge_report | OK | FIELDS=extended |", file=sys.stderr)

# После:
print("\n| edge_report | OK | FIELDS=diagnostics |", file=sys.stderr)
```

### 6. Tests

#### Unit Tests (`tests/unit/test_edge_diagnostics.py`)

- `test_component_breakdown`: Проверка расчёта компонент
- `test_component_breakdown_missing_fields`: Обработка отсутствующих полей
- `test_neg_edge_drivers_positive_net_bps`: Пустой список для положительного net_bps
- `test_neg_edge_drivers_negative_net_bps`: Правильная идентификация топ-2 драйверов
- `test_neg_edge_drivers_equal_contributors`: Обработка равных значений
- `test_block_reasons_no_audit_data`: Нулевые значения при отсутствии данных
- `test_block_reasons_with_audit_data`: Правильный подсчёт counts и ratios
- `test_block_reasons_only_min_interval`: 100% одной причины
- `test_block_reasons_unknown_reason_ignored`: Игнорирование неизвестных причин

**Результат:** 9/9 unit тестов прошли

#### E2E Tests (`tests/e2e/test_edge_report_kpi_gate.py`)

Обновлены существующие тесты:
- `test_edge_report_generation`: Проверка нового маркера `FIELDS=diagnostics` и новых полей

Добавлены новые тесты:
- `test_edge_report_negative_net_bps`: Проверка `neg_edge_drivers` при отрицательном net_bps
- `test_edge_report_with_block_reasons`: Проверка `block_reasons` из audit.jsonl

**Результат:** 6/6 E2E тестов прошли

## Acceptance Criteria

✅ **1. Component Breakdown**
- `EDGE_REPORT.json` содержит поле `component_breakdown` в `totals`
- Все 6 компонент присутствуют: gross, fees_eff, slippage, adverse, inventory, net

✅ **2. Negative Edge Drivers**
- При `net_bps < 0`: `neg_edge_drivers` содержит список топ-2 компонент
- При `net_bps >= 0`: `neg_edge_drivers` пустой список
- Драйверы отсортированы по убыванию абсолютного значения

✅ **3. Block Reasons**
- `EDGE_REPORT.json` содержит поле `block_reasons` в `totals`
- Для каждой причины (min_interval, concurrency, risk, throttle) есть `count` и `ratio`
- Статистика собирается из `audit.jsonl`

✅ **4. Marker Updated**
- Маркер изменён с `FIELDS=extended` на `FIELDS=diagnostics`

✅ **5. Tests**
- Все unit тесты проходят (9/9)
- Все E2E тесты проходят (6/6)

## Изменённые файлы

1. `tools/reports/edge_metrics.py` (+151 строка)
   - `compute_component_breakdown()`
   - `compute_neg_edge_drivers()`
   - `compute_block_reasons()`
   - Обновлён `compute_edge_metrics()` для включения новых полей

2. `tools/reports/edge_report.py` (+1 строка)
   - Маркер: `FIELDS=extended` → `FIELDS=diagnostics`

3. `tests/unit/test_edge_diagnostics.py` (+183 строки, новый файл)
   - 9 unit тестов для диагностических функций

4. `tests/e2e/test_edge_report_kpi_gate.py` (+177 строк)
   - Обновлён `test_edge_report_generation` для проверки новых полей
   - Новый `test_edge_report_negative_net_bps`
   - Новый `test_edge_report_with_block_reasons`

## Use Cases

### 1. Диагностика минусового edge

**Сценарий:** Soak-ран показал `net_bps = -1.78 bps`

**Действия:**
1. Открыть `artifacts/reports/EDGE_REPORT.json`
2. Посмотреть `neg_edge_drivers`:
   ```json
   "neg_edge_drivers": ["slippage_bps", "adverse_bps"]
   ```
3. Проверить `component_breakdown`:
   ```json
   "component_breakdown": {
     "gross_bps": 5.0,
     "slippage_bps": 4.2,    // Проблема!
     "adverse_bps": 3.1,      // Проблема!
     "fees_eff_bps": 2.0,
     "inventory_bps": 0.5,
     "net_bps": -4.8
   }
   ```
4. **Вывод:** Основные потери от slippage и adverse selection → нужно уменьшить агрессивность стратегии

### 2. Анализ блокировок

**Сценарий:** Много CANCEL/REPLACE, подозрение на блокировки

**Действия:**
1. Посмотреть `block_reasons`:
   ```json
   "block_reasons": {
     "min_interval": {"count": 120, "ratio": 0.75},
     "concurrency": {"count": 30, "ratio": 0.19},
     "risk": {"count": 10, "ratio": 0.06},
     "throttle": {"count": 0, "ratio": 0.0}
   }
   ```
2. **Вывод:** 75% блокировок из-за `min_interval` → увеличить `min_interval_ms` или уменьшить `replace_rate`

## Integration

### CI/CD Monitoring

Маркер `| edge_report | OK | FIELDS=diagnostics |` может быть использован для:
- Автоматической проверки наличия диагностических полей
- Интеграции с Grafana/Prometheus для отслеживания компонент net_bps
- Alerts при отрицательном net_bps с автоматическим извлечением топ-драйверов

### Downstream Consumers

Инструменты, использующие `EDGE_REPORT.json`:
- `tools/ci/validate_readiness.py` (KPI Gate): читает `net_bps`, но теперь может также смотреть на `neg_edge_drivers` для детальных причин
- `tools/soak/run.py` (Auto-tuning): может использовать `block_reasons` для более точной настройки параметров
- Grafana dashboards: новые метрики можно визуализировать в breakdown-chart

## Следующие шаги

1. **Grafana Dashboard:** Добавить панель для визуализации `component_breakdown` (stacked bar chart)
2. **Alerts:** Настроить оповещения при `net_bps < 0` с включением топ-драйверов в сообщение
3. **Auto-tuning Integration:** Использовать `block_reasons` для более интеллектуального подбора `min_interval_ms` и `replace_rate_per_min`

## Status

**✅ COMPLETE AND TESTED**

- Все изменения применены
- Все unit тесты проходят (9/9)
- Все E2E тесты проходят (6/6)
- Маркер обновлён
- Готово к production использованию в soak-runs

