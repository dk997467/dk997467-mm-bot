# KPI Gate

### Circuit Gate (F2)

Circuit-gate защищает от всплесков ошибок в интеграциях (биржа/сеть):

Official enum:

| code | name |
|------|------|
| 0 | OPEN |
| 1 | TRIPPED |
| 2 | HALF_OPEN |

- Состояния: OPEN → TRIPPED → HALF_OPEN → OPEN.
- Окно по времени: `circuit_window_sec` (скользящее, err_rate по событиям).
- Триггер: `circuit_max_err_rate_ratio`.
- Время удержания: `circuit_min_closed_sec`.
- HALF_OPEN пробы: `circuit_half_open_probe` успешных событий для возврата в OPEN.

Логи переходов (ASCII, одна строка; фиксированный порядок ключей):
```
event=circuit_transition state_from=OPEN state_to=TRIPPED err_rate=0.350000 window_sec=300 now=1700000000
```

Метрики:
- `circuit_state` (enum: OPEN=0, TRIPPED=1, HALF_OPEN=2)
- `circuit_transitions_total{from,to}` (счётчик переходов)
- `circuit_err_rate_window` (гейдж текущего окна)

Diagnostics:
- `snapshot()` возвращает:
```
{"state":"OPEN","err_rate":0.0,"window_len":0,"last_transition_ts":0}
```
Idempotency:
- Повторный `TRIPPED` не порождает дубликаты переходов и логов.

Thread-safety:
- Опция `thread_safe=True` включает внутренний Lock для публичных методов.

Internals / Window:
- Окно реализовано на `deque(maxlen=...)` с жёстким потолком 10k.
- `events_per_sec_hint` — грубая верхняя оценка частоты событий (по умолчанию 1/сек).
- Можно задать `events_maxlen` явно; иначе вычисляется как `window_sec * max(1, hint)`.

### Anti-flood

Для снижения шума и нагрузки на лог/метрики используется коалесцирование событий и ограничение логов в секунду:

- События агрегируются в пер-секундные бины `(ts_sec, ok_count, err_count)`. Внутри одной секунды счётчики увеличиваются, вместо создания новых записей.
- `err_rate_window` считается как `sum(err_count)/sum(ok_count+err_count)` по бинам внутри `window_sec`, т.е. без занижения (учёт по суммам).
- Логи переходов ограничены бюджетом `max_log_lines_per_sec` на секунду; лишние переходные логи подавляются, однако сама логика переходов не меняется.
- Параметры:
  - `anti_flood_enabled=True` (по умолчанию)
  - `max_events_per_sec=50` (коалесцирование для телеметрии)
  - `max_log_lines_per_sec=10` (лимит переходных логов/сек)

Runbook (SRE):
- Если `TRIPPED` держится долго: временно повысить порог (10–20%), либо выключить проблемную стратегию.
- Проверить внешние зависимости (биржа/сеть). При необходимости откатить релиз.
- После стабилизации вернуть пороги на исходные значения.
