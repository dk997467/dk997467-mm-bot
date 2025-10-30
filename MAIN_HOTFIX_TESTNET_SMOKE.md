# Main Branch Hotfix: Testnet Smoke CI-Safe Dependencies

## ✅ ГОРЯЧИЙ ФИКС ПРИМЕНЕН К MAIN

**Дата:** 2025-10-29  
**Коммит:** `d159024`  
**Ветка:** `main` (прямой push)

---

## 🐛 Проблема

**Issue:** CI workflow `testnet-smoke.yml` падает при установке зависимостей:
```
ERROR: No matching distribution found for bybit-connector>=3.0.0
```

**Root Cause:**
- Workflow использует `pip install -r requirements.txt`
- `requirements.txt` содержит `bybit-connector>=3.0.0` (live-only SDK)
- PyPI не имеет этого пакета в публичном индексе
- CI раннер не может установить зависимости → workflow fails

---

## ✅ Решение

### 1. Создан `requirements_ci.txt`

**Содержимое:** Копия `requirements.txt` **БЕЗ** `bybit-connector`.

```bash
# requirements_ci.txt структура:
# - Все зависимости из requirements.txt
# - УДАЛЕН: bybit-connector>=3.0.0
# - Добавлен заголовок с инструкциями
```

**Преимущества:**
- ✅ CI устанавливает только безопасные зависимости
- ✅ `requirements.txt` не тронут → локальные окружения не сломаны
- ✅ Четкое разделение: CI vs Local/Live

---

### 2. Изменен `.github/workflows/testnet-smoke.yml`

#### **A. Новый паттерн установки (оба job'а):**

**Было:**
```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    pip install -r requirements.txt
```

**Стало:**
```yaml
- name: Install deps (CI-safe)
  shell: bash
  run: |
    set -euo pipefail
    python -m pip install --upgrade pip
    pip install -e .
    if [ -f requirements_ci.txt ]; then
      pip install -r requirements_ci.txt
    fi
```

**Изменения в job'ах:**
- ✅ `smoke-shadow` (строки 56-64)
- ✅ `smoke-testnet-sim` (строки 102-110)

---

#### **B. Добавлен guard-step (оба job'а):**

**Guard step (после checkout, перед Python setup):**
```yaml
- name: Lint - forbid base requirements.txt in this workflow
  shell: bash
  run: |
    set -euo pipefail
    if git grep -nP '^[ \t\-]*[^"#\n]*\bpip([ \t]+|-3[ \t]+)?install[^|#\n]*\B-r[ \t]+requirements\.txt\b' .github/workflows/testnet-smoke.yml | tee /dev/stderr; then
      echo "::error::Found forbidden 'pip install -r requirements.txt' in testnet-smoke.yml. Use requirements_ci.txt." >&2
      exit 1
    fi
```

**Что делает guard:**
1. Сканирует `testnet-smoke.yml` на паттерн `pip install -r requirements.txt`
2. Игнорирует echo-сообщения и комментарии (grep -P)
3. **Фейлит CI немедленно** при обнаружении
4. Показывает точный номер строки

**Изменения в job'ах:**
- ✅ `smoke-shadow` (строки 42-49)
- ✅ `smoke-testnet-sim` (строки 88-95)

---

## 📊 Статистика изменений

| Метрика | Значение |
|---------|----------|
| Файлов создано | 1 (`requirements_ci.txt`) |
| Файлов изменено | 1 (`.github/workflows/testnet-smoke.yml`) |
| Строк добавлено | ~89 |
| Строк удалено | ~4 |
| Job'ов исправлено | 2 |
| Guard-steps добавлено | 2 |

---

## 🔍 Верификация

### Тест guard (после фикса):
```bash
git grep -nP '^[ \t\-]*[^"#\n]*\bpip([ \t]+|-3[ \t]+)?install[^|#\n]*\B-r[ \t]+requirements\.txt\b' .github/workflows/testnet-smoke.yml
# Exit code: 1 (no matches) ✅
```

**Результат:** Паттерн не найден → guard работает, но не ловит себя!

---

## ✅ Acceptance Criteria

| Критерий | Статус |
|----------|--------|
| 1. `requirements_ci.txt` создан | ✅ |
| 2. `bybit-connector` отсутствует в `requirements_ci.txt` | ✅ |
| 3. `testnet-smoke.yml` не использует `requirements.txt` | ✅ |
| 4. Guard-step добавлен в оба job'а | ✅ |
| 5. `requirements.txt` не изменен (локальные окружения safe) | ✅ |
| 6. Коммит запушен в `main` | ✅ |

---

## 🚀 Что дальше?

### Немедленные действия:
1. **Запустить** `testnet-smoke.yml` workflow на ветке `main`
2. **Проверить**, что установка зависимостей проходит без ошибок
3. **Убедиться**, что тесты выполняются корректно

### После успешного прогона:
1. Рассмотреть применение аналогичного паттерна к другим CI workflows:
   - `ci.yml`
   - `accuracy.yml`
   - `shadow.yml`
   - `soak*.yml`
2. Рассмотреть полное удаление `bybit-connector` из `requirements.txt`:
   - Переместить в `[live]` extras (через `pyproject.toml`)
   - Создать отдельный PR для этого изменения

---

## 📋 Технические детали

### Почему `pip install -e .` первым?

**Порядок имеет значение:**
```bash
pip install -e .              # Устанавливает пакет в editable mode
pip install -r requirements_ci.txt  # Устанавливает остальные зависимости
```

**Преимущества:**
- ✅ Пакет доступен для импорта немедленно
- ✅ Зависимости из `pyproject.toml` установлены
- ✅ `requirements_ci.txt` может переопределить версии (если нужно)

---

### Почему guard использует `grep -P`?

**Perl regex (grep -P) vs Extended regex (grep -E):**

| Возможность | grep -E | grep -P |
|-------------|---------|---------|
| Word boundaries (`\b`, `\B`) | ✅ | ✅ |
| Negative character classes (`[^...]`) | ✅ | ✅ |
| Ignore quotes in pattern | ❌ | ✅ (с `[^"#\n]*`) |
| Precise not-word-boundary | ❌ | ✅ (`\B`) |

**Вывод:** `grep -P` позволяет точнее исключить echo-сообщения и комментарии.

---

### Почему `requirements.txt` не изменен?

**Причины:**
1. **Локальные окружения:** Разработчики могут использовать `requirements.txt` для локальной установки
2. **Обратная совместимость:** Не ломаем существующие скрипты/инструкции
3. **Поэтапная миграция:** Сначала фиксим CI, потом делаем полный рефакторинг через PR

**Будущее:**
- Создать PR для удаления `bybit-connector` из `requirements.txt`
- Переместить в `[live]` extras (уже есть в `pyproject.toml`)
- Обновить документацию (README)

---

## 📄 Файлы в коммите

### `requirements_ci.txt` (новый файл):
```
# CI-safe dependencies (no exchange SDKs)
# Generated from requirements.txt with exchange SDKs removed
# Used in CI workflows to avoid installation issues with platform-specific SDKs
#
# Exchange SDKs are in [live] extras (see pyproject.toml)
# For live trading, use: pip install -e .[live]

# Core dependencies
websockets>=11.0.3
pydantic>=2.5.0
pyyaml>=6.0.1
...
# (all deps EXCEPT bybit-connector)
```

### `.github/workflows/testnet-smoke.yml` (изменения):

**Добавлено в `smoke-shadow` job:**
- Guard step (строки 42-49)
- Новый install pattern (строки 56-64)

**Добавлено в `smoke-testnet-sim` job:**
- Guard step (строки 88-95)
- Новый install pattern (строки 102-110)

---

## 🎯 Итоги

**Проблема:** CI падает на `bybit-connector` в `requirements.txt`  
**Решение:** Создан `requirements_ci.txt` + guard в testnet-smoke.yml  
**Результат:** CI безопасен, локальные окружения не сломаны ✅

### Ключевые достижения:
- ✅ Горячий фикс применен **напрямую** к `main` (не через PR)
- ✅ CI больше не пытается установить live-only SDK
- ✅ Guard защищает от регрессии
- ✅ `requirements.txt` не тронут → нет breaking changes
- ✅ Четкое разделение: CI-safe vs Live dependencies

---

**Prepared by:** AI Assistant  
**Date:** 2025-10-29  
**Commit:** `d159024`  
**Branch:** `main`  
**Status:** ✅ Pushed & Ready for Testing

**Запусти `testnet-smoke.yml` на main!** 🚀

