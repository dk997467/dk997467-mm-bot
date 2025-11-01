# CI Secrets Scanner - Backward Compatibility Fix

## Problem

После рефакторинга scanner в PR `fix/ci-secret-scan-scope`, тесты, использующие `monkeypatch.setattr()` для подмены модульных констант, стали падать:

```python
# tests/unit/test_secrets_scanner.py:109
monkeypatch.setattr('tools.ci.scan_secrets.DEFAULT_PATTERNS', test_patterns)
# ❌ AttributeError: 'DEFAULT_PATTERNS' not found
```

**Причина:**
- Старый код импортировал `DEFAULT_PATTERNS` из `src.common.redact`
- Новый код использует локальный `FOCUSED_SECRET_PATTERNS`, но не экспортирует `DEFAULT_PATTERNS`
- Тесты ожидают, что `DEFAULT_PATTERNS` существует как module-level атрибут

## Solution

Восстановлена backward-совместимость без компромиссов с focused patterns:

### 1. **Добавлен экспорт `DEFAULT_PATTERNS`**

```python
# Focused secret patterns (high-signal only)
FOCUSED_SECRET_PATTERNS = [
    r'AKIA[0-9A-Z]{16}',  # AWS
    r'ghp_[0-9A-Za-z]{36,}',  # GitHub
    r'sk_live_[0-9A-Za-z]{24,}',  # Stripe
    # ... остальные focused patterns
]

# Backward-compatibility: Export as DEFAULT_PATTERNS for tests that monkeypatch
# This must be a module-level list (not a property) so monkeypatch can replace it
DEFAULT_PATTERNS = FOCUSED_SECRET_PATTERNS
```

**Ключевой момент:** `DEFAULT_PATTERNS` — это простой list (не property), поэтому `monkeypatch.setattr()` работает.

### 2. **Обновлен `main()` для использования `DEFAULT_PATTERNS`**

**До:**
```python
patterns = FOCUSED_SECRET_PATTERNS
```

**После:**
```python
# Use DEFAULT_PATTERNS (can be monkeypatched by tests)
patterns = DEFAULT_PATTERNS
```

Теперь тесты могут подменить паттерны, и сканер будет их использовать.

### 3. **Добавлен `__all__` для явного экспорта**

```python
# Public exports (for backward-compatibility with tests)
__all__ = ['DEFAULT_PATTERNS', 'TARGET_DIRS', 'ALLOWLIST_FILE', 'main']
```

Это явно документирует, какие атрибуты предназначены для внешнего использования.

### 4. **Добавлен module-level docstring**

```python
"""
Secret scanner for CI pipeline.

Scans source code for hardcoded credentials using focused patterns.
Exports module-level constants for backward-compatibility with tests.
"""
```

## Test Results

### ✅ Previously Failing Tests - Now Passing

```bash
$ python -m pytest tests/unit/test_secrets_scanner.py::test_main_exit_codes -xvs
============================== 1 passed in 1.63s ==============================

$ python -m pytest tests/unit/test_secrets_scanner.py::test_main_real_secrets -xvs
============================== 1 passed in 1.58s ==============================
```

### ✅ Full Test Suite

```bash
$ python -m pytest tests/unit/test_secrets_scanner.py -v
============================== 8 passed in 1.59s ==============================
```

**All 8 tests pass:**
1. `test_allowlist_loading` ✅
2. `test_mask_allowlisting` ✅
3. `test_path_allowlisting` ✅
4. `test_scan_file_with_allowlist` ✅
5. `test_main_exit_codes` ✅ (was failing)
6. `test_main_real_secrets` ✅ (was failing)
7. `test_deterministic_output` ✅
8. `test_builtin_test_credentials` ✅

## Changes Summary

### File: `tools/ci/scan_secrets.py`

```diff
+++ tools/ci/scan_secrets.py
@@ +1,9 @@
+"""
+Secret scanner for CI pipeline.
+
+Scans source code for hardcoded credentials using focused patterns.
+Exports module-level constants for backward-compatibility with tests.
+"""

+# Public exports (for backward-compatibility with tests)
+__all__ = ['DEFAULT_PATTERNS', 'TARGET_DIRS', 'ALLOWLIST_FILE', 'main']

+# Backward-compatibility: Export as DEFAULT_PATTERNS for tests that monkeypatch
+# This must be a module-level list (not a property) so monkeypatch can replace it
+DEFAULT_PATTERNS = FOCUSED_SECRET_PATTERNS

-    patterns = FOCUSED_SECRET_PATTERNS
+    # Use DEFAULT_PATTERNS (can be monkeypatched by tests)
+    patterns = DEFAULT_PATTERNS
```

**Lines changed:** 16 insertions(+), 2 deletions(-)

## No Functionality Change

**Important:** Эти изменения **только** восстанавливают backward-совместимость для тестов.

✅ **Сохранено:**
- Все focused patterns (AWS, GitHub, Stripe, etc.)
- IGNORE_DIRS и IGNORE_GLOBS
- Scan scope (src/, tools/, scripts/)
- Exit code semantics
- CLI arguments (--strict, --paths)

❌ **Не изменено:**
- Логика сканирования
- Обработка allowlist
- Вывод/метрики

## Deployment

**Branch:** `fix/ci-secrets-exports`  
**Commit:** `86be116` - ci(scan): restore module-level DEFAULT_PATTERNS/TARGET_DIRS/ALLOWLIST_FILE for test monkeypatch; keep focused patterns

**PR URL:**
```
https://github.com/dk997467/dk997467-mm-bot/compare/main...fix/ci-secrets-exports
```

**Merge Strategy:**
1. Merge PR → main
2. CI auto-runs (tests should all pass)
3. No runtime changes - safe to deploy

## Testing Checklist

- [x] `test_main_exit_codes` passes (was failing before)
- [x] `test_main_real_secrets` passes (was failing before)
- [x] All 8 tests in `test_secrets_scanner.py` pass
- [x] monkeypatch.setattr() works for `DEFAULT_PATTERNS`
- [x] monkeypatch.setattr() works for `TARGET_DIRS`
- [x] monkeypatch.setattr() works for `ALLOWLIST_FILE`
- [x] Focused patterns still used in normal mode
- [x] No functional changes to scanner logic

## Impact

**Before:**
```
$ pytest tests/unit/test_secrets_scanner.py::test_main_exit_codes
FAILED - AttributeError: module 'tools.ci.scan_secrets' has no attribute 'DEFAULT_PATTERNS'
```

**After:**
```
$ pytest tests/unit/test_secrets_scanner.py::test_main_exit_codes
============================== 1 passed in 1.63s ==============================
```

---

**Status:** ✅ Ready for merge  
**Risk:** NONE - Only affects test compatibility, no runtime changes  
**Reviewer note:** Verify that `DEFAULT_PATTERNS` is assignable for monkeypatch

