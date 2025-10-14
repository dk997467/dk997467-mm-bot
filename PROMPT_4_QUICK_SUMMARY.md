# PROMPT 4: Sleep Between Iterations — Quick Summary

## Статус: ✅ COMPLETE (реализовано ранее)

### Что было сделано

**Код уже реализован:**
- ✅ `tools/soak/run.py` (строки 981-985) — sleep между итерациями
- ✅ `.github/workflows/soak-windows.yml` (строка 455) — env var прокинута

**Проверка выполнена:**
- ✅ `demo_sleep_check.py` — 3 теста пройдены
- ✅ Sleep НЕ срабатывает после последней итерации
- ✅ Wall-clock время корректно

### Ключевые результаты

#### TEST 1: 3 iterations x 5s sleep
```
Expected: 2 sleeps (iterations - 1)
Found: 2 sleeps [OK]
Wall-clock: 10.6s (expected ~10s) [OK]
```

#### TEST 2: 1 iteration (критический тест!)
```
Expected: 0 sleeps (no sleep after last iteration)
Found: 0 sleeps [OK]
```

#### TEST 3: 2 iterations x 3s sleep
```
Expected: 1 sleep
Found: 1 sleep [OK]
Wall-clock: 3.4s (expected ~3s) [OK]
```

### Рекомендуемые границы

| Профиль | Sleep (s) | Iterations | Total Time | Use Case |
|---------|-----------|------------|------------|----------|
| Fast | 30-60 | 3-6 | 5-10 min | CI smoke, debug |
| **Standard** | **180-300** | **6-12** | **30-60 min** | **Regular soak (DEFAULT)** |
| Deep | 600-900 | 12-24 | 3-6h | Weekly, pre-prod |
| Ultra-Long | 1800-3600 | 24-72 | 24-72h | Final validation |

**Абсолютные границы:**
- MIN: 30s (меньше не имеет смысла)
- MAX: 3600s (1h, больше — использовать legacy long-soak)
- DEFAULT: 300s (5 min) — оптимальный баланс ✅

### Примеры использования

```bash
# 1. Standard soak (default, ~30 min)
python -m tools.soak.run --iterations 6 --auto-tune

# 2. Fast iteration (debug, ~2 min)
SOAK_SLEEP_SECONDS=30 python -m tools.soak.run --iterations 3 --auto-tune --mock

# 3. Deep soak (weekly, ~2h)
SOAK_SLEEP_SECONDS=600 python -m tools.soak.run --iterations 12 --auto-tune
```

### Артефакты

- ✅ `demo_sleep_check.py` — демо-скрипт для проверки
- ✅ `SLEEP_BOUNDARIES_ANALYSIS.md` — детальный анализ границ
- ✅ `PROMPT_4_COMPLETE_SUMMARY.md` — полная сводка
- ✅ `PROMPTS_1_2_3_4_FINAL_SUMMARY.md` — мега-сводка всех 4 промптов

### Готово к production ✅

**Без дополнительных изменений — всё уже работает!**

