# Full Stack Validation Checklist

Этот документ описывает процедуру полной валидации проекта mm-bot перед развёртыванием в продакшн.

## Быстрый старт

```bash
# Запуск полной валидации
python tools/ci/full_stack_validate.py

# Генерация отчёта
python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json

# Просмотр результата
cat artifacts/FULL_STACK_VALIDATION.md
```

## Критерии успеха

Валидация считается **успешной**, если:
- `RESULT=OK` в выводе скрипта
- Все секции в отчёте имеют статус `OK`
- Файл `artifacts/FULL_STACK_VALIDATION.json` содержит `"result":"OK"`

## Секции валидации

### 1. Linters (Критично)
**Что проверяется:**
- ASCII-only логи (`lint_ascii_logs.py`)
- Корректность JSON writer (`lint_json_writer.py`) 
- Валидность меток метрик (`lint_metrics_labels.py`)
- Отсутствие секретов (`scan_secrets.py`)

**Критические ошибки:**
- `secrets=FOUND` - найдены потенциальные секреты в коде
- `json_writer=FAIL` - нарушения детерминированного JSON
- `metrics_labels=FAIL` - некорректные метки Prometheus

### 2. Tests Whitelist (Критично)
**Что проверяется:**
- Выполнение отобранных тестов из `tools/ci/test_selection.txt`
- Все тесты должны пройти успешно

**Критические ошибки:**
- Любые падающие тесты в whitelist

### 3. Dry Runs (Важно)
**Что проверяется:**
- Pre-live deployment pack generation
- Chaos failover simulation  
- Soak test autopilot (dry run)
- Artifact rotation simulation

**Допустимые предупреждения:**
- Отсутствие некоторых зависимостей в dev окружении

### 4. Reports (Важно)
**Что проверяется:**
- Edge sentinel analysis
- Parameter sweep execution
- Tuning application
- Weekly rollup generation
- KPI gate validation

**Допустимые предупреждения:**
- `SKIP_NO_FIXTURES` - отсутствие тестовых данных

### 5. Dashboards (Важно)
**Что проверяется:**
- Валидность JSON схем Grafana дашбордов

**Критические ошибки:**
- Некорректные JSON схемы дашбордов

### 6. Secrets (Критично)
**Что проверяется:**
- Сканирование секретов в artifacts, dist, logs, config

**Критические ошибки:**
- `FOUND` - обнаружены потенциальные секреты

### 7. Audit Chain (Важно)
**Что проверяется:**
- End-to-end тесты аудита

**Допустимые предупреждения:**
- `SKIP_NO_TEST` - отсутствие тестов аудита

## Действия при ошибках

### Критические ошибки (блокируют деплой)
1. **Secrets found**: Удалить секреты из кода, использовать переменные окружения
2. **JSON writer fail**: Исправить нарушения детерминированного JSON
3. **Tests fail**: Исправить падающие тесты или исключить из whitelist
4. **Dashboard schema fail**: Исправить JSON схемы дашбордов

### Предупреждения (не блокируют деплой)
- Отсутствие фикстур в dev окружении - нормально
- Пропуск некоторых dry-run тестов - допустимо

## Артефакты

После успешной валидации создаются:
- `artifacts/FULL_STACK_VALIDATION.json` - сырые данные
- `artifacts/FULL_STACK_VALIDATION.md` - человекочитаемый отчёт
- `artifacts/PRE_LIVE_PACK.json` - пакет для деплоя
- `artifacts/PRE_LIVE_PACK.md` - отчёт по деплою

## Переменные окружения

### Обязательные для продакшн
- `MM_VERSION` - версия релиза
- `MM_FREEZE_UTC_ISO` - фиксированное время для детерминизма

### Опциональные для разработки
- `FULL_STACK_VALIDATION_FAST=1` - быстрый режим (пропуск долгих тестов)
- `PRE_LIVE_SKIP_BUG_BASH=1` - пропуск bug bash тестов

## Интеграция с CI/CD

```yaml
# Пример для GitHub Actions
- name: Full Stack Validation
  run: |
    export MM_VERSION=${{ github.ref_name }}
    export MM_FREEZE_UTC_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    python tools/ci/full_stack_validate.py
    python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json
    
- name: Check Result
  run: |
    if grep -q '"result":"OK"' artifacts/FULL_STACK_VALIDATION.json; then
      echo "✅ Validation passed"
    else
      echo "❌ Validation failed"
      exit 1
    fi
```

## Связанные документы

- [OPS_ONE_PAGER.md](OPS_ONE_PAGER.md) - Операционные процедуры
- [RUNBOOKS.md](RUNBOOKS.md) - Руководства по устранению неполадок  
- [REPORTS.md](REPORTS.md) - Описание отчётов системы
- [GO_CHECKLIST.md](GO_CHECKLIST.md) - Чек-лист перед запуском

## Поддержка

При проблемах с валидацией:
1. Проверьте логи в stderr валидатора
2. Изучите детали в `artifacts/FULL_STACK_VALIDATION.json`
3. Обратитесь к соответствующим runbook'ам
4. Эскалируйте команде разработки при критических ошибках
