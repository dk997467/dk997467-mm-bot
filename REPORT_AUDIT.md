### Reliability & Security Audit (mm-bot)

Commit: unknown
Generated at: 1970-01-01T00:00:00Z

## TL;DR: Top-10 быстрых побед
- [P1] Требовать ADMIN_TOKEN по умолчанию; ввести ADMIN_AUTH_DISABLED для локала (cli/run_bot.py:1663-1671)
- [P2] Сделать `rollout_state_snapshot_loop` управляемым через `self.running` (cli/run_bot.py:1984)
- [P3] Добавить проверку лимита 1MB и failed_total для всех loader-эндпоинтов снапшотов
- [P4] Жестко применять детерминированный JSON во всех админ-ответах (проверить редкие ветки ошибок)
- [P5] Добавить fsync(dir) после replace для критичных снапшотов (allocator/throttle/ramp/rollout_state)
- [P6] Документировать bound-лейблы метрик; добавить lightweight _reset_* в тестовой среде
- [P7] Добавить негативные тесты 401/429/invalid-json/size>1MB по всем /admin/* загрузкам
- [P8] Равномерно применить rate-limit к mutating /admin/* (где пропущен)
- [P9] Для ramp/rollout drift — зафиксировать min_sample_orders и тест на rollback/freeze
- [P10] Уточнить graceful shutdown: отмена фоновых задач после web_runner.cleanup

## Strengths
- Детерминированные сериализации JSON: `sort_keys=True, separators=(",", ":")` (cli/run_bot.py:2045 "payload = json.dumps(...)")
- Атомарные записи: tmp->flush->fsync->replace (cli/run_bot.py:1997-2007 "f.flush(); _os.fsync(...); _os.replace(...)")
- Джиттер интервалов детерминированный по пути (HMAC-SHA1) (cli/run_bot.py:2023-2027)
- Метрики снапшотов ok/failed и mtime gauges присутствуют (src/metrics/exporter.py:204-208)
- Токен-проверка через hmac.compare_digest (cli/run_bot.py:1669)
- Rate-limit и audit log для /admin/* (cli/run_bot.py:1681-1715)
- Лейблы метрик — bounded множества (symbol/side/color/op/state) (src/metrics/exporter.py:47,174,198)
- Разделение снапшотов allocator/throttle/ramp/rollout_state, изолированные циклы (cli/run_bot.py:612,658,1224,1982)

## Weaknesses
- ADMIN_TOKEN может быть пустым => доступ разрешен (cli/run_bot.py:1663-1666 "if not token: return True")
- `rollout_state_snapshot_loop` использует `while True` (cli/run_bot.py:1984) — нет остановки
- Нет fsync каталога после replace => риск потери после крэша FS (cli/run_bot.py:2005)
- Не везде единообразный rate-limit по мутирующим /admin/* (см. выборочные 429: cli/run_bot.py:1741,1793,1823,1923,1949)
- Не везде негативные тесты (>1MB loader, 401/429) в tests
- Отсутствует явный _reset_* для метрик в тестах (кардинальность/стейты между тестами)
- Ramp safety: не виден четкий min_sample_orders для drift/rollback (см. tests и cli логика)
- Graceful shutdown: порядок остановки фоновых задач требует проверки на гонки

## Risk heatmap
- determinism: M
- locks: L
- io: M
- security: M
- metrics: M
- rollout: M
- allocator: M
- throttle: M
- scheduler: M
- tests: M

## Ключевые Findings
- F-001 security: ADMIN_TOKEN допускает пустой (disabled by default)
  - file:line: cli/run_bot.py:1663-1666
  - quote:
```1663:cli/run_bot.py
            token = os.getenv('ADMIN_TOKEN')
            if not token:
                return True
```
  - why: доступ к /admin/* без аутентификации в непреднамеренных средах
  - rec: ввести `ADMIN_AUTH_DISABLED=true` для отключения, иначе требовать токен

- F-002 io_atomicity: rollout_state_snapshot_loop не управляется self.running
  - file:line: cli/run_bot.py:1984
  - quote:
```1984:cli/run_bot.py
        while True:
```
  - why: задача не остановится при shutdown, риск гонок и висячих задач
  - rec: `while self.running`

- F-003 io_atomicity: нет fsync(dir) после replace
  - file:line: cli/run_bot.py:2005
  - quote:
```2005:cli/run_bot.py
                        _os.replace(tmp, sp)
```
  - why: редкий риск потери после крэша/питания
  - rec: fsync каталога снапшота (см. src/storage/research_recorder.py:215)

- F-004 tests: недостаточно негативных кейсов 401/429/invalid-json/size>1MB
  - evidence: тесты покрывают happy-pathы; отсутствуют >1MB и повсеместные 401/429
  - rec: добавить parametrize кейсов по всем /admin/* loaders

- F-005 security: rate-limit не унифицирован на всех /admin/*
  - file:line: cli/run_bot.py:1741,1793,1823,1923,1949
  - quote:
```1741:cli/run_bot.py
                return web.json_response({"error": "rate_limited"}, status=429)
```
  - rec: применять для всех мутирующих POST

## Guardrails для PR
- Все JSON — deterministic (sort_keys, separators)
- Любой writer: tmp->flush->fsync->replace; fsync(dir) после replace
- Любой loader: size<=1MB, try/except, *_failed_total
- /admin: compare_digest, токен обязателен (или ADMIN_AUTH_DISABLED=true), rate-limit, audit log
- Метрики: только bounded лейблы; без логов/метрик под lock; тестовый _reset_*

## Appendix
- Endpoints inventory: artifacts/endpoints.json
- Metrics inventory: artifacts/metrics.json
- Snapshots inventory: artifacts/snapshots.json
- Locks inventory: artifacts/locks.json
- Loops inventory: artifacts/threads_loops.json
- Machine audit: artifacts/audit.json
