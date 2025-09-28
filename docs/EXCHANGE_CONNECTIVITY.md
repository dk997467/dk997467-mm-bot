# Улучшенное подключение к бирже Bybit

## Обзор

Этот документ описывает улучшения в подключении к бирже Bybit, включая:
- Idempotent client_order_id для защиты от дублирования
- Логику reconciliation для синхронизации состояния
- Retry/backoff механизмы с классификацией ошибок
- Amend-first подход с fallback на cancel+create

## Архитектура

### Компоненты

1. **BybitRESTConnector** - REST API коннектор с retry логикой
2. **BybitWebSocketConnector** - WebSocket коннектор с переподключениями
3. **OrderReconciler** - Модуль синхронизации состояния
4. **OrderManager** - Управление ордерами с amend-first логикой

### AppContext Integration

Все компоненты интегрированы через AppContext для dependency injection:

```python
@dataclass
class AppContext:
    cfg: AppConfig
    metrics: Optional[Metrics] = None
    bybit_rest: Optional[BybitRESTConnector] = None
    bybit_websocket: Optional[BybitWebSocketConnector] = None
    order_manager: Optional[OrderManager] = None
    order_reconciler: Optional[OrderReconciler] = None
```

## Idempotent Client Order ID

### Формат

```
{symbol}-{side}-{timestamp}-{counter}-{random4}
```

Пример: `BTCUSDT-Buy-1234567890-1-1000`

### Генерация

```python
def _generate_client_order_id(self, symbol: str, side: str) -> str:
    timestamp = int(time.monotonic() * 1000)
    random_suffix = random.randint(1000, 9999)
    return f"{symbol}-{side}-{timestamp}-{random_suffix}"
```

### Преимущества

- Уникальность гарантирована timestamp + random
- Легко отслеживать по символу и стороне
- Монотонно возрастающие timestamp
- Защита от коллизий

## Retry и Backoff Логика

### Классификация ошибок

#### Transient Errors (повторяемые)
- 10006: Rate limit exceeded
- 10018: Request timeout
- 10019: System busy
- 10020-10030: System errors

#### Fatal Errors (не повторяемые)
- 10001: Invalid parameter
- 10002: Invalid request
- 10003: Invalid signature
- 10004: Invalid timestamp
- 10005: Invalid API key

### Exponential Backoff с Jitter

```python
backoff_ms = min(
    self.base_backoff_ms * (2 ** retry_count) + random.randint(0, 1000),
    self.max_backoff_ms
)
```

### Конфигурация

```yaml
exchange:
  max_retries: 3
  base_backoff_ms: 1000
  max_backoff_ms: 30000
```

## Reconciliation Loop

### Принцип работы

Каждые 25 секунд система:
1. Получает активные ордера с биржи
2. Получает недавнюю историю (до 100 ордеров)
3. Сравнивает с локальным состоянием
4. Исправляет расхождения

### Действия Reconciliation

- `MARK_FILLED` - помечает ордер как исполненный
- `MARK_CANCELLED` - помечает ордер как отмененный
- `CLOSE_ORPHAN` - закрывает "сиротские" ордера
- `PAUSE_QUOTING` - приостанавливает котирование при hard desync

### Hard Desync Detection

Если расхождение превышает 10% от общего количества ордеров:
- Приостанавливается risk management
- Логируется причина паузы
- Восстанавливается после успешной синхронизации

## Amend-First Логика

### Условия для Amend

1. **Время в книге**: минимум 500ms (настраивается)
2. **Изменение цены**: максимум 1% (настраивается)
3. **Изменение количества**: максимум 20% (настраивается)

### Fallback на Cancel+Create

Если amend недоступен или не удался:
1. Отменяем существующий ордер
2. Ждем 100ms для распространения отмены
3. Создаем новый ордер

### Конфигурация

```yaml
strategy:
  min_time_in_book_ms: 500
  amend_price_threshold_bps: 1.0
  amend_size_threshold: 0.2
```

## Метрики

### Latency Metrics

```python
metrics.latency_ms.observe({"stage": "rest"}, latency_ms)
metrics.latency_ms.observe({"stage": "ws"}, latency_ms)
metrics.latency_ms.observe({"stage": "reconcile"}, latency_ms)
```

### Error Rate Metrics

```python
metrics.rest_error_rate.labels(exchange="bybit").inc()
metrics.ws_reconnects_total.labels(exchange="bybit").inc()
```

### Risk Management Metrics

```python
metrics.risk_paused.set(1)  # Приостановлено
metrics.risk_paused.set(0)  # Активно
```

## WebSocket Reconnection

### Автоматическое переподключение

- Экспоненциальный backoff с jitter
- Максимум 10 попыток
- Heartbeat каждые 30 секунд
- Переподписка на темы после reconnect

### Конфигурация

```yaml
exchange:
  max_reconnect_attempts: 10
  base_reconnect_delay: 1.0
  max_reconnect_delay: 60.0
  heartbeat_interval: 30
```

## Использование

### Инициализация

```python
# Создание контекста
ctx = AppContext(cfg=config)

# Инициализация метрик
ctx.metrics = Metrics(ctx)

# Создание REST коннектора
ctx.bybit_rest = BybitRESTConnector(ctx, exchange_config)

# Создание WebSocket коннектора
ctx.bybit_websocket = BybitWebSocketConnector(ctx, exchange_config)

# Создание order manager
ctx.order_manager = OrderManager(ctx, ctx.bybit_rest)

# Запуск reconciliation
await ctx.order_manager.start()
```

### Размещение ордера

```python
client_order_id = await ctx.order_manager.place_order(
    symbol="BTCUSDT",
    side="Buy",
    order_type="Limit",
    qty=0.1,
    price=50000.0
)
```

### Обновление ордера

```python
success = await ctx.order_manager.update_order(
    client_order_id="BTCUSDT-Buy-1234567890-1-1000",
    new_price=50100.0
)
```

### Проверка состояния risk management

```python
if ctx.order_manager.is_risk_paused():
    reason = ctx.order_manager.get_risk_pause_reason()
    print(f"Risk management paused: {reason}")
```

## Тестирование

### Запуск тестов

```bash
# Тест idempotent client order ID
pytest tests/test_idempotent_cid.py -v

# Тест reconciliation
pytest tests/test_reconcile_diff.py -v

# Тест retry/backoff
pytest tests/test_retry_backoff.py -v

# Тест amend-first логики
pytest tests/test_amend_fallback.py -v
```

### Тестовые сценарии

1. **Idempotent CID**: уникальность, формат, монотонность
2. **Reconciliation**: синхронизация состояния, обработка ошибок
3. **Retry/Backoff**: transient vs fatal ошибки, backoff расчеты
4. **Amend-Fallback**: условия amend, fallback логика

## Мониторинг

### Grafana Dashboard

Используйте существующий dashboard `mm_bot_overview.json` для мониторинга:
- Latency по стадиям (rest, ws, reconcile)
- Error rates по биржам
- WebSocket reconnections
- Risk management status

### Логирование

Все действия reconciliation логируются с детализацией:
```
Reconciliation completed: 2 orders fixed, 1 orphans closed, risk_paused=False
  Action: mark_filled
  Action: close_orphan
```

## Безопасность

### API Keys

- Храните API ключи в environment variables
- Используйте минимальные права доступа
- Регулярно ротируйте ключи

### Rate Limiting

- Respect rate limits биржи
- Используйте exponential backoff при превышении
- Мониторьте error rates

### Risk Management

- Автоматическая пауза при hard desync
- Логирование всех действий
- Метрики для мониторинга состояния

## Troubleshooting

### Частые проблемы

1. **WebSocket disconnections**: проверьте heartbeat и reconnection логику
2. **High error rates**: проверьте rate limits и backoff настройки
3. **Reconciliation failures**: проверьте connectivity и API permissions
4. **Risk management pauses**: проверьте logs для причины паузы

### Debug режим

Включите детальное логирование для отладки:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Health Checks

Используйте метрики для health checks:
- `risk_paused` - статус risk management
- `ws_reconnects_total` - количество переподключений
- `rest_error_rate` - частота ошибок REST API
