# PROMPT G — KPI Gate + Safe-Mode в CI — COMPLETE

## Цель
Обеспечить стабильную работу KPI Gate и validate_stack в soak-ветке без падения из-за отсутствующих секретов, с чёткими маркерами для мониторинга.

## Реализация

### 1. Workflow Configuration (`.github/workflows/soak-windows.yml`)

Добавлены env-переменные для safe-mode в секцию `env`:

```yaml
# ========================================================================
# VALIDATION & KPI GATE (safe-mode for CI)
# ========================================================================

# Allow validation steps to skip when secrets are missing
MM_ALLOW_MISSING_SECRETS: "1"

# Fixtures directory for tests
FIXTURES_DIR: "tests/fixtures"
```

**Назначение:**
- `MM_ALLOW_MISSING_SECRETS=1`: Включает safe-mode для `validate_stack` и `full_stack_validate`
- `FIXTURES_DIR`: Путь к тестовым фикстурам для валидации

**Эффект:**
- Validation-шаги не падают при отсутствии `STORAGE_PG_PASSWORD` и других секретов
- `tests_whitelist` возвращает `ok=true, details="SKIPPED_NO_SECRETS"`
- Маркер `| full_stack | OK | STACK=GREEN |` печатается стабильно

### 2. KPI Gate Exit Code Fix (`tools/ci/validate_readiness.py`)

**Изменено:**
```python
# До:
return 0 if verdict == "OK" else 1

# После:
return 0 if verdict in ("OK", "WARN") else 1
```

**Обоснование:**
- `WARN` — это информационный статус, не ошибка
- Только `FAIL` должен возвращать exit code 1
- Это позволяет pipeline продолжать работу при warnings, но блокирует при критических проблемах

**Маркеры:**
- OK: `| kpi_gate | OK | THRESHOLDS=APPLIED |`
- WARN: `| kpi_gate | WARN | REASONS=EDGE:adverse,EDGE:order_age |`
- FAIL: `| kpi_gate | FAIL | REASONS=EDGE:net_bps,EDGE:cancel_ratio |`

### 3. E2E Tests (`tests/e2e/test_ci_safe_mode.py`)

Создан новый E2E тест-пак для проверки safe-mode:

#### Test 1: `test_validate_stack_safe_mode_no_secrets`
- Проверяет `validate_stack` в safe-mode без секретов
- Ожидает: `tests_whitelist.ok=true, details="SKIPPED_NO_SECRETS"`
- Проверяет маркер: `| full_stack | OK | STACK=GREEN |`

#### Test 2: `test_full_stack_validate_safe_mode`
- Проверяет `full_stack_validate` в safe-mode
- Ожидает: `RESULT=OK` и `STACK=GREEN`
- Пропускает шаги, требующие секреты

#### Test 3: `test_kpi_gate_with_good_metrics`
- Проверяет KPI Gate с хорошими метриками
- Ожидает: verdict=OK, exit code 0
- Проверяет маркер: `| kpi_gate | OK | THRESHOLDS=APPLIED |`

#### Test 4: `test_kpi_gate_with_warnings`
- Проверяет KPI Gate с метриками в WARN-диапазоне
- Ожидает: verdict=WARN, exit code 0 (не ошибка!)
- Проверяет маркер: `| kpi_gate | WARN | REASONS=... |`

**Все 4 теста проходят успешно.**

## Acceptance Criteria

✅ **1. Safe-Mode в Workflow**
- Env-переменные `MM_ALLOW_MISSING_SECRETS` и `FIXTURES_DIR` добавлены в `soak-windows.yml`
- Применяются ко всем validation-шагам

✅ **2. Validation-шаги стабильны**
- `validate_stack` и `full_stack_validate` корректно обрабатывают `MM_ALLOW_MISSING_SECRETS=1`
- `tests_whitelist` возвращает `ok=true, details="SKIPPED_NO_SECRETS"`
- Маркер `| full_stack | OK | STACK=GREEN |` печатается стабильно

✅ **3. KPI Gate работает корректно**
- Пороги из Prompt C сохранены (adverse 4.0/6.0, slippage 3.0/5.0, cancel 0.55/0.70, и т.д.)
- При `--kpi-gate` печатает чёткие маркеры OK/WARN/FAIL
- Создаёт `KPI_GATE.json` с verdict и reasons
- Exit code 0 для OK и WARN, exit code 1 только для FAIL

✅ **4. Тесты подтверждают работу**
- 4 E2E теста проверяют все сценарии
- Все тесты проходят успешно
- Покрыты случаи: safe-mode, KPI OK, KPI WARN

## Изменённые файлы

1. `.github/workflows/soak-windows.yml` (+8 строк env-переменных)
2. `tools/ci/validate_readiness.py` (+1 строка fix exit code для WARN)
3. `tests/e2e/test_ci_safe_mode.py` (+292 строки, новый файл)

## Маркеры для CI/CD Monitoring

### Validation
```
| full_stack | OK | STACK=GREEN |
| full_stack | FAIL | STACK=RED |
```

### KPI Gate
```
| kpi_gate | OK | THRESHOLDS=APPLIED |
| kpi_gate | WARN | REASONS=EDGE:adverse,EDGE:order_age |
| kpi_gate | FAIL | REASONS=EDGE:net_bps,EDGE:cancel_ratio |
```

### Tests Whitelist (Safe-Mode)
```json
{
  "name": "tests_whitelist",
  "ok": true,
  "details": "SKIPPED_NO_SECRETS"
}
```

## Следующие шаги

1. **Production Run:** Запустить soak-workflow на self-hosted runner
2. **Monitor:** Проверить, что KPI_GATE.json создаётся в каждой итерации
3. **Alert:** Настроить мониторинг маркеров WARN/FAIL для Telegram/Slack оповещений

## Status

**✅ COMPLETE AND TESTED**

- Все изменения применены
- Все тесты проходят (4/4)
- Safe-mode проверен
- KPI Gate проверен
- Маркеры стабильны
- Готово к production использованию в soak-runs

