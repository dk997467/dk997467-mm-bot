OPS DAY-0 CHEATSHEET

1) Утро (2 мин)
- python tools/ci/run_bug_bash.py  → RESULT=OK
- python -m tools.ops.daily_check → RESULT=OK
- python -m tools.ops.daily_digest --out artifacts/DAILY_DIGEST.md

2) Запуск soak (14 дней, econ)
- python tools/ops/quick_cmds.py --do soak-14d

3) Быстрая валидация
- python tools/ops/quick_cmds.py --do full-validate

4) Сборка пакета
- python tools/ops/quick_cmds.py --do ready-bundle

5) Аварии (SOP, кратко)
- Drift/Reg guard → день FAIL, смотреть DRIFT_STOP/REG_GUARD_STOP, auto_rollback
- Chaos drill (dry): python -m tools.chaos.soak_failover --dry-run
- Rollback overlay: python -m tools.tuning.auto_rollback

6) Где смотреть
- artifacts/DAILY_DIGEST.md, WEEKLY_ROLLUP.{json,md}, READINESS_SCORE.{json,md}, FULL_STACK_VALIDATION.md
- Grafana: Latency, Edge, Guards


