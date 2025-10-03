# 🔬 Memory Diagnostic - Инструкция по запуску

## 📋 Цель

Найти тесты, которые вызывают `exit code 143 (OOM)` после исправления Prometheus registry leak.

---

## 🚀 Шаг 1: Запуск Memory Diagnostic на GitHub Actions

### Вариант A: Через Web UI (Рекомендуется)

1. **Откройте GitHub Actions:**
   ```
   https://github.com/<ваш-org>/mm-bot/actions
   ```

2. **Найдите workflow:**
   - В левом меню выберите **"CI Memory Diagnostic"**

3. **Запустите workflow:**
   - Нажмите **"Run workflow"** (серая кнопка справа)
   - Выберите branch: `feature/implement-audit-fixes`
   - Настройте параметры:
     - **test_file:** `test_selection_unit.txt` (по умолчанию)
     - **batch_size:** `3` (по умолчанию)
   - Нажмите зелёную кнопку **"Run workflow"**

4. **Дождитесь завершения:**
   - Workflow займет ~10-15 минут
   - Обновите страницу чтобы увидеть прогресс

### Вариант B: Через GitHub CLI

```bash
gh workflow run "CI Memory Diagnostic" \
  --ref feature/implement-audit-fixes \
  --field test_file=test_selection_unit.txt \
  --field batch_size=3
```

---

## 📊 Шаг 2: Анализ результатов

### 2.1 Найдите failing batch

После завершения workflow:

1. **Откройте run logs**
2. **Перейдите к шагу:** `[3/6] Run tests in batches with memory profiling`
3. **Ищите pattern:**
   ```
   ================================================================================
   BATCH X: Running 3 tests
   ================================================================================
     [1/3] tests/test_AAAA.py
     [2/3] tests/test_BBBB.py
     [3/3] tests/test_CCCC.py  ← Этот тест может быть виновником!
   
   [BATCH X] Exit code: 143  ← OOM!
   ```

### 2.2 Определите проблемный тест

**Если BATCH X упал с exit 143:**
- Запустите еще раз с `batch_size: 1` для тестов из BATCH X
- Это изолирует конкретный тест

**Пример:**
```yaml
# Первый запуск показал: BATCH 5 failed (tests 13-15)
# Второй запуск с batch_size=1 для тестов 13-15:
test_file: test_selection_unit.txt
batch_size: 1
# (вручную отредактируйте test_selection_unit.txt, оставив только тесты 13-15)
```

### 2.3 Проверьте memory profiles

1. **Скачайте artifacts:**
   - Внизу страницы run найдите **"Artifacts"**
   - Скачайте `memory-diagnostic-<run-id>`

2. **Анализируйте .bin файлы:**
   ```bash
   pip install memray
   python -m memray stats batch_X.bin
   python -m memray flamegraph batch_X.bin  # Создаст HTML flamegraph
   ```

---

## 🔍 Шаг 3: Интерпретация результатов

### Сценарий A: Все батчи прошли успешно ✅

**Это означает:**
- Prometheus registry fix полностью решил проблему! 🎉
- Никаких дополнительных утечек нет
- **Действие:** Мержить PR и закрывать issue

### Сценарий B: Batch X упал с exit 143 ❌

**Это означает:**
- Есть дополнительная утечка памяти в одном из 3-х тестов батча X
- **Действие:** Перейти к Шагу 4 (изоляция проблемного теста)

### Сценарий C: Batch X упал с exit code != 143

**Это означает:**
- Тест упал не из-за OOM, а из-за другой ошибки (AssertionError, Exception)
- **Действие:** Исправить ошибку теста, это не связано с памятью

---

## 🎯 Шаг 4: Изоляция проблемного теста

### 4.1 Создайте временный test list

Создайте файл `tools/ci/test_selection_debug.txt`:
```
# Только тесты из failing batch X
tests/test_AAAA.py
tests/test_BBBB.py
tests/test_CCCC.py
```

### 4.2 Запустите с batch_size=1

```yaml
test_file: test_selection_debug.txt
batch_size: 1
```

### 4.3 Найдите виновника

Смотрите, какой из 3-х тестов дал exit 143:
```
BATCH 1: tests/test_AAAA.py
[BATCH 1] Exit code: 0  ✅

BATCH 2: tests/test_BBBB.py
[BATCH 2] Exit code: 143  ❌ ← ВИНОВНИК!

BATCH 3: tests/test_CCCC.py
[BATCH 3] Exit code: 0  ✅
```

---

## 🛠️ Шаг 5: Исправление проблемного теста

### 5.1 Анализ кода теста

Откройте найденный файл (например, `tests/test_BBBB.py`) и ищите:

**Red flags:**
```python
# 1. Загрузка больших файлов БЕЗ очистки
def test_heavy():
    data = load_huge_dataset()  # ← Нет del/gc.collect()
    process(data)

# 2. Фикстуры с scope="module" или "session"
@pytest.fixture(scope="module")
def heavy_fixture():
    return load_massive_data()  # ← Живет весь модуль!

# 3. Глобальные переменные, накапливающие данные
CACHE = []  # ← Накапливается между тестами

def test_something():
    CACHE.append(generate_big_object())  # ← Утечка!

# 4. Pandas DataFrames без очистки
def test_pandas():
    df = pd.read_csv("huge.csv")  # ← 2GB в памяти
    # ... нет del df

# 5. Subprocess без cleanup
def test_subprocess():
    proc = subprocess.Popen([...])
    # ... нет proc.terminate()
```

### 5.2 Применение исправлений

**Паттерн 1: Явная очистка**
```python
def test_heavy():
    data = load_huge_dataset()
    result = process(data)
    assert result
    # FIX: Явно удаляем большие объекты
    del data
    import gc
    gc.collect()
```

**Паттерн 2: Фикстура с cleanup**
```python
@pytest.fixture
def heavy_fixture():
    data = load_massive_data()
    yield data
    # FIX: Cleanup после теста
    del data
    import gc
    gc.collect()
```

**Паттерн 3: Убрать глобальное состояние**
```python
# BEFORE
CACHE = []
def test_something():
    CACHE.append(data)

# AFTER
def test_something():
    cache = []  # ← Локальная переменная
    cache.append(data)
```

**Паттерн 4: Использовать контекст-менеджеры**
```python
def test_pandas():
    df = pd.read_csv("huge.csv")
    try:
        process(df)
    finally:
        del df
        gc.collect()
```

---

## 📚 Частые проблемные тесты

### Кандидаты #1: Backtest тесты
- `tests/test_backtest_*.py`
- **Причина:** Загружают большие JSONL файлы с тиками
- **Исправление:** Добавить `del df; gc.collect()` после обработки

### Кандидаты #2: E2E тесты
- `tests/e2e/test_*.py`
- **Причина:** Используют тяжелые фикстуры с реальными данными
- **Исправление:** Убедиться что фикстуры имеют scope="function", не "module"

### Кандидаты #3: Симуляция
- `tests/test_queue_sim_*.py`, `tests/test_sim_*.py`
- **Причина:** Моделируют тысячи событий в памяти
- **Исправление:** Ограничить размер симуляции, очищать после каждого теста

### Кандидаты #4: Metrics тесты
- `tests/test_metrics_*.py`
- **Причина:** Создают много объектов Metrics (уже исправлено с registry cleanup)
- **Статус:** ✅ Должно быть исправлено нашим фиксом

---

## 🎓 Best Practices

### DO ✅
- Используйте `del` + `gc.collect()` для больших объектов
- Фикстуры с `scope="function"` (по умолчанию)
- Очистка в `finally` блоках или `yield` фикстур
- Маленькие тестовые данные (< 10MB)

### DON'T ❌
- Глобальные переменные в тестах
- Фикстуры с `scope="session"` для тяжелых данных
- Загрузка реальных больших файлов (используйте моки)
- Subprocess без `terminate()` + `wait()`

---

## 🚨 Troubleshooting

### Проблема: Workflow не запускается

**Решение:**
- Проверьте права доступа к GitHub Actions
- Убедитесь что workflow файл существует: `.github/workflows/ci-memory-diagnostic.yml`
- Попробуйте запустить через GitHub CLI

### Проблема: Все батчи проходят на CI, но fail локально

**Решение:**
- CI использует чистое окружение
- Локально может быть грязный кеш pytest
- Очистите: `rm -rf .pytest_cache __pycache__`

### Проблема: Нет .bin файлов в artifacts

**Решение:**
- pytest-memray не установлен (проверьте шаг [1/6] в логах)
- Тесты упали до создания профилей
- Используйте `--memray` флаг в pytest команде

---

## ✅ Checklist

- [ ] Запустил CI Memory Diagnostic workflow
- [ ] Проверил логи на exit 143
- [ ] Скачал artifacts (если есть)
- [ ] Изолировал проблемный тест (batch_size=1)
- [ ] Проанализировал код теста
- [ ] Применил исправление (del + gc.collect())
- [ ] Протестировал локально
- [ ] Закоммитил исправление
- [ ] Запустил CI еще раз для верификации
- [ ] ✅ Все зелёное!

---

## 📞 Поддержка

Если workflow не дает нужной информации:

1. **Добавьте debug logging в тест:**
   ```python
   import psutil
   import os
   
   def test_heavy():
       process = psutil.Process(os.getpid())
       print(f"Memory before: {process.memory_info().rss / 1024 / 1024:.2f} MB")
       
       data = load_huge_dataset()
       print(f"Memory after load: {process.memory_info().rss / 1024 / 1024:.2f} MB")
       
       del data
       import gc
       gc.collect()
       print(f"Memory after cleanup: {process.memory_info().rss / 1024 / 1024:.2f} MB")
   ```

2. **Запустите локально с memray:**
   ```bash
   pip install pytest-memray
   pytest tests/test_PROBLEMATIC.py --memray -vv
   python -m memray flamegraph pytest-memray-*.bin
   ```

---

**Good hunting! 🎯**

