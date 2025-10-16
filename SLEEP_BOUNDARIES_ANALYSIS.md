# PROMPT 4: Sleep Boundaries Analysis

## Разумные границы SOAK_SLEEP_SECONDS для разных профилей

### Общая формула wall-clock времени

```
Total time = (iterations × iteration_duration) + ((iterations - 1) × sleep_seconds)
```

Где:
- `iteration_duration` — время выполнения одной итерации (~10-60s в зависимости от mock/real)
- `sleep_seconds` — время сна между итерациями

---

## 1. ПРОФИЛЬ: Fast Iteration (быстрая обратная связь)

**Цель:** Максимально быстрый фидбек для разработки/дебага

**Рекомендации:**
- `SOAK_SLEEP_SECONDS`: **30 - 60 секунд**
- Итерации: 3-6
- Total time: ~5-10 минут

**Применение:**
- CI/CD пайплайны (быстрые smoke-тесты)
- Локальная разработка с `--mock`
- Отладка iter_watcher логики

**Пример:**
```bash
# 6 iterations × 30s sleep = 5 sleeps × 30s = 2.5 min + processing
SOAK_SLEEP_SECONDS=30 python -m tools.soak.run --iterations 6 --auto-tune --mock
```

**Риски:**
- Недостаточно времени для остывания системы между итерациями
- Метрики могут не успеть стабилизироваться

---

## 2. ПРОФИЛЬ: Standard Soak (стандартный режим)

**Цель:** Баланс между скоростью и реалистичностью

**Рекомендации:**
- `SOAK_SLEEP_SECONDS`: **180 - 300 секунд (3-5 минут)**
- Итерации: 6-12
- Total time: ~30-60 минут

**Применение:**
- Регулярные soak-тесты в CI
- Проверка стабильности после изменений
- Валидация auto-tuning логики

**Пример:**
```bash
# 6 iterations × 300s sleep = 5 sleeps × 300s = 25 min + processing (~30 min total)
SOAK_SLEEP_SECONDS=300 python -m tools.soak.run --iterations 6 --auto-tune
```

**Default:** Это текущий дефолт (300s)

---

## 3. ПРОФИЛЬ: Deep Soak (глубокая проверка)

**Цель:** Поиск медленных утечек памяти, edge-кейсов

**Рекомендации:**
- `SOAK_SLEEP_SECONDS`: **600 - 900 секунд (10-15 минут)**
- Итерации: 12-24
- Total time: ~3-6 часов

**Применение:**
- Weekly soak-тесты
- Pre-production validation
- Тестирование под нагрузкой

**Пример:**
```bash
# 12 iterations × 600s sleep = 11 sleeps × 600s = 110 min + processing (~2h total)
SOAK_SLEEP_SECONDS=600 python -m tools.soak.run --iterations 12 --auto-tune
```

**Риски при меньшем sleep:**
- Не успевает проявиться медленная утечка памяти
- GC не успевает отработать между итерациями

---

## 4. ПРОФИЛЬ: Ultra-Long Soak (экстремальная стабильность)

**Цель:** 24-72h непрерывная работа с редкими проверками

**Рекомендации:**
- `SOAK_SLEEP_SECONDS`: **1800 - 3600 секунд (30-60 минут)**
- Итерации: 24-72
- Total time: 24-72 часа

**Применение:**
- Финальная валидация перед релизом
- Стресс-тест в production-like окружении

**Пример:**
```bash
# 48 iterations × 1800s sleep = 47 sleeps × 1800s = ~24h + processing
SOAK_SLEEP_SECONDS=1800 python -m tools.soak.run --iterations 48 --auto-tune
```

**Риски при меньшем sleep:**
- Слишком частые итерации могут маскировать проблемы (постоянная активность)
- Недостаточно времени для проявления race conditions

---

## Рекомендации по границам (АБСОЛЮТНЫЕ)

### Минимум: 30 секунд
**Почему:**
- Меньше 30s — нет смысла в sleep (обработка итерации ~10-60s)
- Система не успевает остыть
- Логи и метрики могут быть неполными

**Исключения:**
- Unit-тесты с `--mock` (можно 0-10s для speed)

### Максимум: 3600 секунд (1 час)
**Почему:**
- Больше 1h — избыточно для mini-soak (лучше переключиться на legacy long-soak)
- Риск таймаута всего workflow
- Неэффективное использование runner-времени

**Исключения:**
- Ultra-long soak (можно до 2h при необходимости)

---

## Таблица: Профили vs Границы

| Профиль          | Sleep (s) | Iterations | Total Time | Use Case                          |
|------------------|-----------|------------|------------|-----------------------------------|
| **Fast**         | 30-60     | 3-6        | 5-10 min   | CI smoke, debug                   |
| **Standard**     | 180-300   | 6-12       | 30-60 min  | Regular soak, auto-tune           |
| **Deep**         | 600-900   | 12-24      | 3-6h       | Weekly, pre-prod                  |
| **Ultra-Long**   | 1800-3600 | 24-72      | 24-72h     | Final validation, stress test     |

---

## Workflow Input: Рекомендуемые значения

В `.github/workflows/soak-windows.yml`:

```yaml
heartbeat_interval_seconds:
  description: "Sleep between iterations (seconds)"
  required: false
  type: number
  default: 300  # Standard profile
```

**Диапазон для validation:**
```yaml
# MIN: 30s (fast iteration)
# MAX: 3600s (ultra-long soak)
# DEFAULT: 300s (standard soak — баланс скорости/качества)
```

---

## Soft-Cap Strategy (автоматическая подстройка)

Если хотите автоматически лимитировать sleep в зависимости от числа итераций:

```python
# В tools/soak/run.py (опционально):
sleep_seconds = int(os.getenv("SOAK_SLEEP_SECONDS", "300"))

# Soft-cap: уменьшаем sleep при большом числе итераций
if args.iterations > 20:
    sleep_seconds = min(sleep_seconds, 900)  # Max 15 min для long soak
elif args.iterations > 10:
    sleep_seconds = min(sleep_seconds, 600)  # Max 10 min для deep soak
elif args.iterations <= 3:
    sleep_seconds = max(sleep_seconds, 30)   # Min 30s для fast iteration
```

**Плюсы:**
- Защита от ошибок конфигурации (100 iterations × 3600s = 100h)
- Автоматическая адаптация под профиль

**Минусы:**
- Меньше гибкости для edge-кейсов
- Может удивить пользователя

**Рекомендация:** Пока оставить как есть (явный контроль через env var), добавить soft-cap только при жалобах на таймауты.

---

## Проверка: Как узнать оптимальный sleep?

1. **Запустите с метриками:**
   ```bash
   SOAK_SLEEP_SECONDS=300 python -m tools.soak.run --iterations 6 --auto-tune
   ```

2. **Проверьте ITER_SUMMARY_*.json:**
   - Если `risk_ratio` стабилизируется к 3-й итерации → sleep достаточный
   - Если колеблется до последней итерации → увеличьте sleep

3. **Проверьте wall-clock:**
   - Если `wall-clock >> (iterations × sleep)` → processing overhead высокий, можно увеличить sleep
   - Если `wall-clock ≈ (iterations × sleep)` → processing быстрый, sleep оптимален

---

## Итого: Рекомендации

| Параметр                     | Значение                           |
|------------------------------|------------------------------------|
| **DEFAULT**                  | 300s (5 min) — баланс             |
| **MIN (абсолютный)**         | 30s — для fast iteration          |
| **MAX (абсолютный)**         | 3600s (1h) — для ultra-long       |
| **MIN (рекомендуемый)**      | 180s (3 min) — для real soak      |
| **MAX (рекомендуемый)**      | 900s (15 min) — для deep soak     |
| **Текущий default (CI)**     | 300s — OK ✅                       |

---

## PITFALL: Что может пойти не так?

### PITFALL 1: Sleep = 0 (пропуск сна)
**Симптом:** Total time ≈ processing time, нет `| soak | SLEEP |` в логах

**Причина:** `SOAK_SLEEP_SECONDS=0` или не прокинута env var при использовании default

**Решение:**
```python
# Добавить guard в run.py:
sleep_seconds = int(os.getenv("SOAK_SLEEP_SECONDS", "300"))
if sleep_seconds < 0:
    sleep_seconds = 0  # Prevent negative sleep
```

### PITFALL 2: Sleep после последней итерации
**Симптом:** Total time на 1 sleep больше ожидаемого

**Причина:** Неправильное условие `if iteration < args.iterations - 1`

**Текущий код (CORRECT):**
```python
if iteration < args.iterations - 1:  # Don't sleep after last iteration
    print(f"| soak | SLEEP | {sleep_seconds}s |")
    time.sleep(sleep_seconds)
```

**Проверка:** Демо-скрипт `demo_sleep_check.py` — тест 2 (single iteration)

### PITFALL 3: Таймаут workflow
**Симптом:** GitHub Actions убивает job по timeout

**Причина:** `(iterations × sleep) > workflow timeout`

**Решение:**
- В `.github/workflows/soak-windows.yml`:
  ```yaml
  timeout-minutes: 4380  # 73h (max для GitHub)
  ```
- Валидация при запуске:
  ```python
  total_time_minutes = ((args.iterations - 1) * sleep_seconds) / 60
  if total_time_minutes > 4320:  # 72h
      print(f"[WARN] Total time ({total_time_minutes:.1f} min) exceeds recommended max (72h)")
  ```

---

## Conclusion

**Текущая реализация (PROMPT 4) уже содержит всё необходимое:**
- ✅ Sleep между итерациями (кроме последней)
- ✅ Env var `SOAK_SLEEP_SECONDS` с default 300s
- ✅ Workflow прокидывает `heartbeat_interval_seconds`
- ✅ Логирование `| soak | SLEEP | {N}s |`
- ✅ Wall-clock summary в конце

**Дополнительно рекомендую:**
- Запустить `demo_sleep_check.py` для валидации
- Добавить soft-cap (опционально) при большом числе итераций
- Документировать допустимый диапазон в workflow description

