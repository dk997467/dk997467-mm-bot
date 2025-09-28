### ACTION PLAN — минимальные изменения и тест-план

All JSON deterministic: sort_keys=True, separators=(",", ":"). ASCII only.

## [P1] Enforce ADMIN_TOKEN by default; add ADMIN_AUTH_DISABLED
- Context: cli/run_bot.py:1663-1671
- Goal: Требовать токен везде, кроме явного DEV режима
- Change: читать env ADMIN_AUTH_DISABLED; если не true — требовать ненулевой ADMIN_TOKEN
- Pseudo-diff:
  - read env `ADMIN_AUTH_DISABLED`
  - if disabled: allow; else: require token non-empty and compare_digest
- Tests:
  - 401 без токена; 200 c верным токеном; 401 с неверным; pass при ADMIN_AUTH_DISABLED=true
- Acceptance: все /admin/* защищены, логируется audit, rate-limit работает
- Risk/Rollback: флагом ADMIN_AUTH_DISABLED включить прежнее поведение
- Effort: S

## [P2] Make rollout_state_snapshot_loop stoppable
- Context: cli/run_bot.py:1984
- Goal: Остановка цикла на shutdown
- Change: `while self.running` и старт/стоп вместе с web server
- Tests: запустить цикл, затем set running=False, убедиться что завершился
- Acceptance: нет висячих задач на остановке
- Effort: S

## [P3] Loader size<=1MB + *_failed_total everywhere
- Context: snapshot loaders in cli/run_bot.py (allocator/throttle/ramp/rollout_state)
- Goal: Единообразие safe-load
- Change: перед чтением проверять st_size <= 1MB; инкрементировать *_failed_total
- Tests: файл >1MB -> 400/failed_total, корректный файл -> ok/total
- Effort: S

## [P4] Deterministic JSON for all admin responses
- Context: rare error branches
- Change: гарантировать json.dumps(... sort_keys, separators) или web.json_response стабильно
- Tests: провал валидации -> дет-JSON
- Effort: S

## [P5] fsync(dir) after replace for critical snapshots
- Context: cli/run_bot.py:2005; reference dir fsync (src/storage/research_recorder.py:215)
- Change: open dirfd of snapshot parent, fsync, close
- Tests: unit test monkeypatch fsync on dir
- Effort: S

## [P6] Metrics label bounds and _reset_* in tests
- Change: документировать bound-лейблы; добавить утилиту reset для тестов
- Tests: вызвать reset между parametrize батчами
- Effort: S

## [P7] Negative tests for /admin loaders (401/429/invalid-json/size>1MB)
- Effort: S

## [P8] Unify rate-limit on all mutating /admin POST
- Change: использовать общий helper _admin_rate_limit_check
- Tests: 429 по превышению
- Effort: S

## [P9] Ramp safety and drift min_sample_orders
- Change: ввести min_sample_orders для drift и тест rollback/freeze
- Tests: ниже порога -> нет смены шага; при резком ухудшении -> rollback/freeze
- Effort: M

## [P10] Graceful shutdown ordering
- Change: сначала остановить фоновые циклы, потом web_runner.cleanup
- Tests: интеграционный тест на clean shutdown
- Effort: M

## KPI / Metrics of success
- Снижение 401/429 ошибок вне тестов не требуется; рост admin_audit_events_total ожидаем в тестах
- *_writes_failed_total остаются на 0 в норме; *_loads_failed_total растут в негативных тестах
- rollout_state_snapshot_mtime_seconds{op="write"} отражает записи по POST
- Отсутствуют висячие задачи (нет предупреждений об отмененных тасках)
