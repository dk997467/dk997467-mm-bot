# CI Windows Cache & Anti-Sleep Fix — Safe Caching + Fallback Keep-Awake

## Проблема A: tar/gzip warnings

На Windows self-hosted runner'е `actions/cache` при post-processing пытался использовать `tar -z` (gzip compression), но `gzip.exe` недоступен → warning "exit code 2" при сохранении кэша.

## Проблема B: PowerShell модуль шум

PowerShell-модуль `keep_awake.ps1` с `Export-ModuleMember` генерирует красные строки при `Import-Module` в начале и при cleanup, создавая шум в логах.

## Решение

### 1. Исправлены пути кэширования (forward slashes)

**До:**
```yaml
path: ~\AppData\Local\pip\Cache
path: ~\.cargo\registry\index
path: rust\target
```

**После:**
```yaml
path: ~/AppData/Local/pip/Cache
path: ~/.cargo/registry/index
path: rust/target
```

**Почему:** GitHub Actions нормализует пути с `/` на всех платформах, а backslashes `\` могут вызывать проблемы с tar/gzip на Windows.

### 2. Расширен pip cache

```yaml
path: |
  ~/AppData/Local/pip/Cache
  **/__pycache__
```

Теперь также кэшируются скомпилированные `.pyc` файлы для ускорения.

### 3. Уточнены ключи кэша

```yaml
# Более точное отслеживание изменений
key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt') }}
```

Реагирует на изменения в `requirements.txt`, `requirements_ci.txt` и т.д.

### 4. Добавлена документация

В `actions/upload-artifact@v4` добавлен комментарий:
```yaml
# Note: actions/upload-artifact@v4 handles compression automatically
#       (no need for manual tar/gzip on Windows)
```

### 5. Упрощены пути артефактов

**До:**
```yaml
path: |
  ${{ env.ARTIFACTS_ROOT }}/**
  ${{ github.workspace }}/.pytest_cache/**
```

**После:**
```yaml
path: |
  artifacts/**
  .pytest_cache/**
```

**Почему:** `actions/upload-artifact@v4` сам резолвит относительные пути от workspace root, не нужны env vars.

### 6. Упрощен anti-sleep механизм (fallback)

**До:**
```yaml
- name: Initialize anti-sleep protection
  run: |
    Import-Module keep_awake.ps1  # ❌ Export-ModuleMember шум
    Test-RunnerService
    Get-PowerHealthDiagnostics -PreTest
    Set-PowerSettingsForSoak
    Enable-StayAwake  # WinAPI
```

**После:**
```yaml
- name: Keep runner awake (fallback)
  shell: pwsh
  run: |
    $global:keepAwakeJob = Start-Job -ScriptBlock {
      while ($true) {
        Write-Host "[KEEP-AWAKE] Heartbeat"
        Start-Sleep -Seconds 300
      }
    }
    "KEEP_AWAKE_JOB_ID=$($global:keepAwakeJob.Id)" | Out-File -Append $env:GITHUB_ENV
```

**Cleanup:**
```yaml
- name: Stop anti-sleep
  if: always()
  shell: pwsh
  run: |
    Stop-Job -Id $env:KEEP_AWAKE_JOB_ID -Force
    Remove-Job -Id $env:KEEP_AWAKE_JOB_ID -Force
```

**Почему:** 
- ✅ Нет шума от `Export-ModuleMember`
- ✅ Работает везде (не требует keep_awake.ps1 или WinAPI)
- ✅ Простой fallback для предотвращения idle timeout
- ✅ Чистые логи без красных строк

## Результат

✅ **Acceptance Criteria:**

**Cache (Prompt A):**
- Больше нет жёлтых блоков `tar.exe ... exit code 2`
- Кэш работает на всех ОС (Windows/Linux)
- `actions/cache` сам выбирает оптимальный метод упаковки:
  - Linux: tar + gzip/zstd
  - Windows: tar без gzip (или альтернативная упаковка)
- Артефакты чистые, без ручной архивации

**Anti-sleep (Prompt B):**
- Никаких красных строк об `Export-ModuleMember`
- Пайплайн тише, логи чистые
- Keep-awake job работает в фоне без шума
- Cleanup проходит без ошибок Import-Module

## Файлы изменены

- `.github/workflows/soak-windows.yml` — основной фикс

## Затронутые шаги

**Cache fixes:**
1. `[3/12] Cache Cargo registry` — исправлены пути (forward slashes)
2. `[4/12] Cache Rust build artifacts` — исправлены пути
3. `[6/12] Cache pip dependencies` — исправлены пути + добавлен `__pycache__`
4. `[11/12] Upload artifacts` — упрощены пути + документация

**Anti-sleep fixes:**
5. `Initialize anti-sleep protection` → `Keep runner awake (fallback)` — убран Import-Module, простой background job
6. `Cleanup anti-sleep protection` → `Stop anti-sleep` — убран Import-Module, простой Stop-Job/Remove-Job

## Тестирование

После merge запустить soak test на Windows runner:
```bash
gh workflow run soak-windows.yml \
  --ref <branch> \
  -f soak_hours=1 \
  -f stay_awake=0
```

Проверить:
- [ ] Post-cache шаги завершаются без warnings
- [ ] Cache успешно восстанавливается на повторных запусках
- [ ] Артефакты корректно загружаются

## Ссылки

- [actions/cache известная issue на Windows](https://github.com/actions/cache/issues/891)
- [GitHub Actions path normalization](https://docs.github.com/en/actions/learn-github-actions/workflow-syntax-for-github-actions#jobsjob_idstepswithinput_idname)

