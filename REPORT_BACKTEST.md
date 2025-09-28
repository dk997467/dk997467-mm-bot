Backtest Reports
================

Форматы отчётов
----------------

- BACKTEST_REPORT.json — детерминированный JSON (ASCII, sort_keys, separators=(",",":"), последний символ — `\n`). Ключи:
  - `fills_total`, `net_bps`, `taker_share_pct`, `order_age_p95_ms`, `fees_bps`, `turnover_usd`
  - `runtime`: `{ "utc": "...", "version": "...", "mode": "backtest" }`
- BACKTEST_REPORT.md — рядом, ASCII, строки заканчиваются `\n`. Таблица из ключевых полей; числа форматируются `%.6f`.
- BACKTEST_WF.json — отчёт walk-forward: список окон `windows` и агрегаты `mean`/`median`.

Запуск
------

```
python -m tools.backtest.cli run --ticks tests/fixtures/backtest_ticks_case1.jsonl --mode queue_aware --out artifacts/BACKTEST_REPORT.json
python -m tools.backtest.cli wf --ticks tests/fixtures/backtest_ticks_case1.jsonl --mode queue_aware --train 200 --test 100 --out artifacts/BACKTEST_WF.json
```

Допущения
---------

- Только stdlib; запись JSON — атомарная (tmp + fsync + os.replace), ASCII.
- Без внешних зависимостей, без IO в симуляторе.
- Детерминированное форматирование, байт-в-байт при повторном запуске.


