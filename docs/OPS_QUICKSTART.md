# OPS QUICKSTART

ASCII-only команды для быстрых операций (окружение нормализуется скриптом):

```
# READY-бандл
python tools/ops/quick_cmds.py --do ready-bundle
# Мегапроверка
python tools/ops/quick_cmds.py --do full-validate
# Запуск 14-дневного soak
python tools/ops/quick_cmds.py --do soak-14d
# Всё подряд
python tools/ops/quick_cmds.py --do all
```

Примечания:
- Переменные окружения фиксируются: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, TZ=UTC, LANG=LC_ALL=C, MM_FREEZE_UTC=1.
- Вывод — ASCII; dry-run печатает детерминированный план и заканчивается строкой `QUICK_CMDS=PLAN`.
- Реальный запуск пишет сводку в `artifacts/QUICK_CMDS_SUMMARY.md` (LF, атомарная запись, fsync) и печатает `QUICK_CMDS=DONE`.
- Для удобства есть цели Makefile: `ready-bundle`, `full-validate`, `soak-14d`, `all-ops`.

## Artifacts (snapshot & archive)

- Archive (по умолчанию fast):

```
python -m tools.ops.artifacts_archive --src artifacts --fast
```

- Archive (тонкая настройка):

```
python -m tools.ops.artifacts_archive --src artifacts --max-files 200 --max-mb 3 --exclude failures --exclude tmp
```

- Snapshot on FAIL (hooked в пайплайны):

```
python -m tools.ops.artifacts_snapshot_on_fail --journal artifacts/SOAK_JOURNAL.jsonl --fast
```

## Daily routine (ежедневный цикл)
Последовательность: daily_check → sentinel → digest → archive.

1) Daily check — быстрые проверки метрик/порогов:

```
python -m tools.ops.daily_check
```

2) Cron Sentinel — контроль окон и недельный rollup:

```
python -m tools.ops.cron_sentinel --tz Europe/Berlin --window-hours 24 --dry
```

3) Digest — итог дня (светофор, метрики, рекомендации):

```
python -m tools.ops.daily_digest --out artifacts/DAILY_DIGEST.md --journal artifacts/SOAK_JOURNAL.jsonl --hours 24
```

4) Archive — упаковать артефакты за сутки:

```
python -m tools.ops.artifacts_archive --src artifacts --fast
```

### Примечания
- Все артефакты складываются в `artifacts/` (очистка старых выполняется периодически).
- В случае FAIL триггерится snapshot; ссылки на runbooks — в Alertmanager.
- Таймзона по умолчанию Europe/Berlin (можно переопределить флагом `--tz`).

## Long Soak
Smoke (короткие окна):

```bash
python -m tools.ops.soak_run --shadow-hours 0.01 --canary-hours 0.01 --live-hours 0.02 --tz Europe/Berlin --out artifacts/soak_reports/smoke.json
```

Длительный прогон:

```bash
python -m tools.ops.soak_run --shadow-hours 6 --canary-hours 6 --live-hours 12 --tz Europe/Berlin --out artifacts/soak_reports/$(date +%F).json
```

### Daily checks (Cron Sentinel)

Быстрая проверка свежести ключевых артефактов и статусов:

```
python tools/ops/cron_sentinel.py --window-hours 24 --artifacts-dir artifacts --dry
python -m tools.ops.daily_check
```

Интерпретация:
- Логи `event=sentinel_check ...` и сводная строка `RESULT=OK|FAIL missing=<n> stale=<n> checked=<n>`.
- В случае FAIL проверьте пайплайн nightly/cron и сервисы, формирующие отчёты.

### Full-Accept

Запуск строгих структурных проверок ключевых артефактов:

```
make full-accept
```

Критерии: наличие и минимальная структура `KPI_GATE.json`, `FULL_STACK_VALIDATION.json`, `EDGE_REPORT.json`, `EDGE_SENTINEL.json`.
Итоговая строка: `event=full_accept status=OK|FAIL files_checked=<n> errors=<n>`.

### Soak orchestration

Фазы: `shadow → canary → live-econ` (малый капитал). Оркестратор:

```
make soak-shadow
make soak-canary
make soak-live-econ
```

Каждый тик (ежечасно) оценивает KPI/EDGE и пишет `artifacts/SOAK_JOURNAL.jsonl` с hash-цепочкой и решениями:
`event=soak_tick phase=<...> status=<CONTINUE|WARN|FAIL> action=<NONE|TUNE_DRY|ROLLBACK_STEP|...> reason_code=<CODE> reason=<...>`.
Лестница rollback: WARN→TUNE_DRY; FAIL1→ROLLBACK_STEP; FAIL2→DISABLE_STRАТ; FAIL3→REGION_STEP_DOWN.

Reason codes:

| code | meaning |
|------|---------|
| OK | no issues |
| NET_BPS_LOW | low net_bps (2.0..2.5) |
| TAKER_CEIL | taker above phase ceiling |
| P95_SPIKE | latency spike (p95/p99) |
| READINESS_LOW | readiness below threshold |
| GEN_FAIL | generic fail (other conditions) |

### Release bundle

READY-gate блокирует сборку при readiness<85:

```
make ready-gate
```

Сборка бандла и штампа (версия/sha256/git):

```
make bundle
```

Автопересбор каждые 3–5 дней:

```
make bundle-auto
```

Штамп записывается в `artifacts/RELEASE_STAMP.json` с полями `version`, `git_hash`, `bundle_sha256`, `ts`.


