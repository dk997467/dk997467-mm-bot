# PROMPT 4: Sleep Between Iterations — COMPLETE ✅

## Задача

**Цель:** Обеспечить реальное wall-clock время для mini-soak (6 итераций × 300s = ~30 минут), вместо быстрого пролёта за минуты.

**Проблема:** Цикл мини-soak раньше мог завершаться слишком быстро без пауз между итерациями.

---

## Реализация

### 1. Код в `tools/soak/run.py` (строки 981-985)

```python
# Sleep between iterations (respect environment variable)
sleep_seconds = int(os.getenv("SOAK_SLEEP_SECONDS", "300"))
if iteration < args.iterations - 1:  # Don't sleep after last iteration
    print(f"| soak | SLEEP | {sleep_seconds}s |")
    time.sleep(sleep_seconds)
```

**Ключевые особенности:**
- ✅ Читает из env var `SOAK_SLEEP_SECONDS` (default: 300s)
- ✅ Sleep только между итерациями (НЕ после последней)
- ✅ Логирование с маркером `| soak | SLEEP | {N}s |`

### 2. Workflow `.github/workflows/soak-windows.yml` (строка 455)

```yaml
- name: Run mini-soak with auto-tuning
  id: mini-soak
  if: ${{ inputs.iterations }}
  env:
    SOAK_SLEEP_SECONDS: ${{ inputs.heartbeat_interval_seconds || 300 }}
  run: |
    # ...
```

**Интеграция:**
- ✅ Прокидывается через `inputs.heartbeat_interval_seconds`
- ✅ Default: 300s (5 минут) — баланс скорости/качества
- ✅ Конфигурируется через workflow_dispatch

### 3. Summary в конце run (строки 987-999)

```python
# RISK-AWARE: Calculate wall-clock duration
wall_secs = int(time.time() - t0)
wall_str = str(timedelta(seconds=wall_secs))

# After all iterations, print summary
print(f"\n{'='*60}")
print(f"[MINI-SOAK COMPLETE] {args.iterations} iterations with auto-tuning")
print(f"{'='*60}")
print(f"Final overrides: {json.dumps(current_overrides, indent=2)}")
print(f"{'='*60}")
print(f"REAL DURATION (wall-clock): {wall_str}")
print(f"ITERATIONS COMPLETED: {iter_done}")
print(f"{'='*60}")
```

**Выходные данные:**
- ✅ Wall-clock время (реальное, включая sleep)
- ✅ Число завершённых итераций

---

## Проверка: Демо-запуск

### Запуск `demo_sleep_check.py`

**TEST 1: 3 iterations × 5s sleep**
```
[CHECK 1] Sleep marker count
  Expected: 2 (iterations - 1)
  Found: 2
  [OK] Correct number of sleep markers

[CHECK 2] Sleep duration values
  Sleep 1: 5s [OK]
  Sleep 2: 5s [OK]
  [OK] All sleep durations correct

[CHECK 3] Wall-clock duration
  Expected: ~10s (2 sleeps × 5s)
  Actual: 10.6s
  [OK] Wall-clock time within expected range
```

**TEST 2: 1 iteration (NO SLEEP expected)**
```
[CHECK 1] Sleep marker count
  Expected: 0 (iterations - 1)
  Found: 0
  [OK] Correct number of sleep markers
```

**TEST 3: 2 iterations × 3s sleep**
```
[CHECK 1] Sleep marker count
  Expected: 1 (iterations - 1)
  Found: 1
  [OK] Correct number of sleep markers
```

### ✅ Критерии готовности — ВЫПОЛНЕНЫ

| Критерий | Статус | Доказательство |
|----------|--------|----------------|
| Sleep виден в логах между итерациями | ✅ | `\| soak \| SLEEP \| 5s \|` найдено 2 раза (3 iterations) |
| Sleep НЕ срабатывает после последней итерации | ✅ | TEST 1: 2 sleeps (не 3), TEST 2: 0 sleeps |
| Wall-clock время в summary корректно | ✅ | `REAL DURATION (wall-clock): 0:00:10` |
| Число завершённых итераций корректно | ✅ | `ITERATIONS COMPLETED: 3` |

---

## Рекомендации по границам SOAK_SLEEP_SECONDS

### Таблица профилей

| Профиль          | Sleep (s) | Iterations | Total Time | Use Case                          |
|------------------|-----------|------------|------------|-----------------------------------|
| **Fast**         | 30-60     | 3-6        | 5-10 min   | CI smoke, debug                   |
| **Standard**     | 180-300   | 6-12       | 30-60 min  | Regular soak, auto-tune (DEFAULT) |
| **Deep**         | 600-900   | 12-24      | 3-6h       | Weekly, pre-prod                  |
| **Ultra-Long**   | 1800-3600 | 24-72      | 24-72h     | Final validation, stress test     |

### Абсолютные границы

- **MIN (абсолютный):** 30s — меньше не имеет смысла (processing overhead ~10-60s)
- **MAX (абсолютный):** 3600s (1h) — больше лучше использовать legacy long-soak
- **DEFAULT (текущий):** 300s (5 min) — оптимальный баланс ✅

### Рекомендации для workflow input

```yaml
heartbeat_interval_seconds:
  description: "Sleep between iterations (30-3600s, default: 300)"
  required: false
  type: number
  default: 300
```

**Валидация (опционально):**
```python
sleep_seconds = int(os.getenv("SOAK_SLEEP_SECONDS", "300"))
if sleep_seconds < 30:
    print(f"[WARN] Sleep {sleep_seconds}s < MIN(30s), using 30s")
    sleep_seconds = 30
elif sleep_seconds > 3600:
    print(f"[WARN] Sleep {sleep_seconds}s > MAX(3600s), using 3600s")
    sleep_seconds = 3600
```

---

## Формула wall-clock времени

```
Total time = (iterations × iteration_duration) + ((iterations - 1) × sleep_seconds)
```

**Пример для 6 iterations × 300s sleep:**
```
Total ≈ (6 × 30s) + (5 × 300s) = 180s + 1500s = 1680s ≈ 28 минут
```

**Реальное время может быть больше из-за:**
- Processing overhead (EDGE_REPORT генерация, iter_watcher, apply_deltas)
- I/O operations (чтение/запись artifacts)
- Mock data delays

---

## PITFALLS и смягчение

### PITFALL 1: Sleep = 0 (пропуск сна)

**Симптом:** Total time ≈ processing time, нет `| soak | SLEEP |` в логах

**Причина:** `SOAK_SLEEP_SECONDS=0` или не прокинута env var

**Решение:**
- Default 300s уже защищает
- Опционально добавить guard: `sleep_seconds = max(sleep_seconds, 0)`

### PITFALL 2: Sleep после последней итерации

**Симптом:** Total time на 1 sleep больше ожидаемого

**Текущий код (CORRECT):**
```python
if iteration < args.iterations - 1:  # Don't sleep after last iteration
```

**Проверка:** Демо-скрипт TEST 2 (single iteration) — 0 sleeps ✅

### PITFALL 3: Таймаут workflow

**Симптом:** GitHub Actions убивает job по timeout

**Причина:** `(iterations × sleep) > workflow timeout`

**Текущая защита:**
- `.github/workflows/soak-windows.yml`:
  ```yaml
  timeout-minutes: 4380  # 73 hours (max для GitHub)
  ```
- Для 6 iterations × 300s = 25 min — далеко от лимита ✅

**Рекомендация:** Добавить валидацию при запуске (опционально):
```python
total_time_minutes = ((args.iterations - 1) * sleep_seconds) / 60
if total_time_minutes > 4320:  # 72h
    print(f"[WARN] Total time ({total_time_minutes:.1f} min) exceeds recommended max (72h)")
```

### PITFALL 4: Негативные sleep значения

**Симптом:** Ошибка `ValueError: sleep length must be non-negative`

**Причина:** Некорректный ввод в workflow

**Защита:**
```python
sleep_seconds = max(0, int(os.getenv("SOAK_SLEEP_SECONDS", "300")))
```

---

## Артефакты

| Файл | Назначение |
|------|-----------|
| `demo_sleep_check.py` | Демо-скрипт для валидации sleep-логики |
| `SLEEP_BOUNDARIES_ANALYSIS.md` | Подробный анализ границ для разных профилей |
| `PROMPT_4_COMPLETE_SUMMARY.md` | Итоговая сводка (этот документ) |

---

## Итоговый статус

### ✅ Готовность: 100%

**Реализовано:**
1. ✅ Sleep между итерациями (кроме последней) — `tools/soak/run.py`
2. ✅ Env var `SOAK_SLEEP_SECONDS` с default 300s — `tools/soak/run.py`
3. ✅ Workflow прокидывает `heartbeat_interval_seconds` — `.github/workflows/soak-windows.yml`
4. ✅ Логирование `| soak | SLEEP | {N}s |` — `tools/soak/run.py`
5. ✅ Wall-clock summary в конце — `tools/soak/run.py`
6. ✅ Демо-проверка NO sleep после последней итерации — `demo_sleep_check.py`
7. ✅ Рекомендации по границам — `SLEEP_BOUNDARIES_ANALYSIS.md`

**Проверено:**
- ✅ Sleep count = iterations - 1 (TEST 1, 2, 3)
- ✅ Wall-clock ≈ (iterations - 1) × sleep_seconds + overhead
- ✅ Single iteration → 0 sleeps
- ✅ Multi iterations → correct sleep count

**Производительность:**
- Default (6 iter × 300s): ~30 min ✅
- Fast (6 iter × 60s): ~6 min
- Deep (12 iter × 600s): ~2h

---

## Примеры использования

### 1. Standard soak (default)
```bash
python -m tools.soak.run --iterations 6 --auto-tune
# SOAK_SLEEP_SECONDS=300 (default)
# Total: ~30 minutes
```

### 2. Fast iteration для дебага
```bash
SOAK_SLEEP_SECONDS=30 python -m tools.soak.run --iterations 3 --auto-tune --mock
# Total: ~2 minutes
```

### 3. Deep soak для weekly validation
```bash
SOAK_SLEEP_SECONDS=600 python -m tools.soak.run --iterations 12 --auto-tune
# Total: ~2 hours
```

### 4. Workflow dispatch (GitHub Actions)
```yaml
workflow_dispatch:
  inputs:
    iterations: 6
    heartbeat_interval_seconds: 300  # Прокидывается в SOAK_SLEEP_SECONDS
```

---

## Заключение

**PROMPT 4 полностью реализован и протестирован.**

**Ключевые достижения:**
- ✅ Mini-soak теперь реально длится нужное время (6 iter × 300s = ~30 min)
- ✅ Sleep НЕ срабатывает после последней итерации (защита от лишних задержек)
- ✅ Wall-clock время корректно отображается в summary
- ✅ Границы sleep задокументированы для разных профилей (30s - 3600s)
- ✅ Демо-проверка подтверждает корректность

**Следующие шаги:**
- Опционально: добавить soft-cap validation для SOAK_SLEEP_SECONDS (30-3600s)
- Опционально: добавить workflow timeout warning при большом числе итераций
- Готово к production использованию! 🎉

