# State & Concurrency Architecture (P0.8)

## Обзор

P0.8 реализует **надёжное состояние**, **безопасную конкуренцию** и **идемпотентность** для MM-Bot с использованием **stdlib-only** подхода для Redis, Redlock и детерминированного retry механизма.

## Архитектурные принципы

1. **Pure Stdlib**: Все компоненты state layer реализованы без внешних зависимостей
2. **Детерминизм**: Тестируемость через инъекцию fake clock
3. **Идемпотентность**: Все мутации безопасны для повторных вызовов
4. **Снапшоты**: Периодическое сохранение на диск для восстановления
5. **In-Memory Fake**: Redis эмулируется в памяти для CI/тестов

---

## Компоненты

### 1. RedisKV (`tools/state/redis_client.py`)

**Интерфейс:**
```python
class RedisKV:
    def __init__(self, clock: Callable[[], float] | None = None):
        # In-memory fake Redis with TTL support
        
    # String operations
    def get(self, key: str) -> str | None
    def set(self, key: str, value: str, ex: int | None = None) -> None
    def delete(self, key: str) -> int
    def exists(self, key: str) -> bool
    
    # Hash operations
    def hget(self, key: str, field: str) -> str | None
    def hset(self, key: str, field: str, value: str) -> int
    def hmget(self, key: str, fields: list[str]) -> list[str | None]
    def hmset(self, key: str, mapping: dict[str, str]) -> None
    def hgetall(self, key: str) -> dict[str, str]
    def hdel(self, key: str, *fields: str) -> int
    
    # List operations
    def lpush(self, key: str, *values: str) -> int
    def rpush(self, key: str, *values: str) -> int
    def lpop(self, key: str) -> str | None
    def rpop(self, key: str) -> str | None
    def llen(self, key: str) -> int
    def lrange(self, key: str, start: int, stop: int) -> list[str]
    
    # Set operations
    def sadd(self, key: str, *members: str) -> int
    def smembers(self, key: str) -> set[str]
    def srem(self, key: str, *members: str) -> int
    
    # Scan operations
    def scan(self, cursor: int = 0, match: str | None = None, count: int = 10) -> tuple[int, list[str]]
```

**Режимы:**
- `no_network=True` → in-memory fake (default для CI)
- `no_network=False` → заглушка с NotImplementedError (live режим позже)

**Сериализация:**
- JSON с `sort_keys=True`, `separators=(',', ':')` для детерминизма
- Compact формат без пробелов
- Trailing `\n` для JSONL

---

### 2. Redlock (`tools/state/locks.py`)

**Интерфейс:**
```python
class Redlock:
    def __init__(self, clock: Callable[[], float] | None = None):
        # In-memory distributed lock with TTL
        
    def acquire(self, resource: str, ttl_ms: int) -> str | None:
        # Returns token if acquired, None if locked
        
    def release(self, resource: str, token: str) -> bool:
        # Returns True if released, False if token mismatch
        
    def refresh(self, resource: str, token: str, ttl_ms: int) -> bool:
        # Returns True if refreshed, False if token mismatch or expired
```

**Особенности:**
- **Token-based validation**: Только владелец токена может освободить/обновить lock
- **TTL expiry**: Автоматическое освобождение после истечения TTL
- **Clock injection**: Детерминированное тестирование через fake clock
- **No leaks**: Гарантия освобождения при сбоях через TTL

**Тестовые сценарии:**
- Конкурентные acquire (race conditions)
- Refresh до/после TTL
- Token leak detection
- Clock drift

---

### 3. DurableOrderStore (`tools/live/order_store_durable.py`)

**Интерфейс:**
```python
class DurableOrderStore:
    def __init__(
        self,
        redis_client: RedisKV,
        snapshot_dir: Path,
        clock: Callable[[], float] | None = None
    ):
        # Durable order storage with Redis + disk snapshot
        
    def place_order(
        self,
        symbol: str,
        side: Side,
        qty: float,
        price: float,
        idem_key: str | None = None
    ) -> Order | None:
        # Idempotent place order
        
    def update_order_state(
        self,
        client_order_id: str,
        new_state: OrderState,
        idem_key: str | None = None
    ) -> bool:
        # Idempotent state update
        
    def update_fill(
        self,
        client_order_id: str,
        filled_qty: float,
        avg_fill_price: float,
        idem_key: str | None = None
    ) -> bool:
        # Idempotent fill update
        
    def cancel_all_open(self, idem_key: str | None = None) -> list[str]:
        # Idempotent cancel all open orders
        
    def save_snapshot(self) -> None:
        # Save to disk (orders.jsonl)
        
    def recover_from_snapshot(self) -> int:
        # Recover from disk snapshot
```

**Ключи Redis:**
- `orders:{client_order_id}` → order JSON
- `orders:open` → set of open order IDs
- `orders:by_symbol:{symbol}` → set of order IDs for symbol
- `idem:{key}` → idempotency tracking (result cache)

**Snapshot формат:**
```jsonl
{"client_order_id":"...", "symbol":"...", "state":"OPEN", ...}
{"client_order_id":"...", "symbol":"...", "state":"FILLED", ...}
```

**Идемпотентность:**
- `idem_key` → результат первой операции кэшируется в Redis
- Повторный вызов с тем же `idem_key` → возврат кэшированного результата
- TTL для `idem:*` ключей → автоматическая очистка

---

### 4. Retry Mechanism (`tools/common/retry.py`)

**Интерфейс:**
```python
def retry(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_ms: float = 100.0,
    jitter_off: bool = False,
    deterministic_clock: Callable[[], float] | None = None
) -> T:
    # Retry with exponential backoff + deterministic jitter
    
def retry_with_log(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_ms: float = 100.0,
    logger: logging.Logger | None = None
) -> T:
    # Retry with logging
```

**Backoff:**
- Exponential: `delay = base_ms * (2 ** attempt)`
- Deterministic jitter: `_pseudo_jitter(idem_key, attempt)` вместо `random()`
- Для тестов: `jitter_off=True` → без jitter

**Детерминированный джиттер:**
```python
def _pseudo_jitter(seed_str: str, attempt: int) -> float:
    # Hash-based pseudo-random jitter for deterministic tests
    hash_val = hash(f"{seed_str}:{attempt}")
    return 0.5 + ((hash_val % 1000) / 1000.0) * 0.5  # [0.5, 1.0]
```

---

## Интеграция с ExecutionLoop

### Конфигурация

```python
# With idempotency (DurableOrderStore)
loop = ExecutionLoop(
    exchange=exchange,
    order_store=DurableOrderStore(...),
    risk_monitor=risk_monitor,
    enable_idempotency=True
)

# Without idempotency (InMemoryOrderStore)
loop = ExecutionLoop(
    exchange=exchange,
    order_store=InMemoryOrderStore(),
    risk_monitor=risk_monitor,
    enable_idempotency=False
)
```

### Freeze Handling

**При freeze:**
1. `ExecutionLoop._cancel_all_open_orders()` вызывается
2. Генерируется `freeze_idem_key = f"freeze_{timestamp}"`
3. `order_store.cancel_all_open(idem_key=freeze_idem_key)`
4. Повторные вызовы freeze → тот же `idem_key` → идемпотентность

**Кэширование freeze key:**
```python
self._freeze_idem_key = None  # Cached freeze idempotency key

def _cancel_all_open_orders(self) -> None:
    if not self._freeze_idem_key:
        freeze_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._freeze_idem_key = f"freeze_{freeze_ts}"
    
    # Idempotent cancel_all
    canceled_ids = self.order_store.cancel_all_open(idem_key=self._freeze_idem_key)
```

### Recovery from Restart

```python
# Simulate restart
recovery_report = loop.recover_from_restart()

# Returns:
{
    "recovered": True,
    "open_orders_count": 5,
    "open_orders": [
        {"client_order_id": "...", "symbol": "BTCUSDT", ...},
        ...
    ]
}
```

---

## Тестирование

### Unit Tests

**`tests/unit/test_redis_kv_unit.py`:**
- String/Hash/List/Set operations
- TTL expiry
- Scan with pattern matching
- JSON serialization determinism

**`tests/unit/test_redlock_unit.py`:**
- Acquire/release/refresh
- Token validation
- TTL expiry
- Concurrent acquire (race conditions)
- Clock drift scenarios

**`tests/unit/test_retry_unit.py`:**
- Exponential backoff
- Deterministic jitter
- Retry exhaustion
- Success on N-th attempt

**`tests/unit/test_order_store_durable_unit.py`:**
- Idempotent place_order
- Idempotent update_order_state/update_fill
- Idempotent cancel_all_open
- Snapshot save/recover

### Integration Tests

**`tests/integration/test_exec_with_state_and_freeze.py`:**
- ExecutionLoop + DurableOrderStore
- Freeze → cancel_all (idempotent)
- Restart → recovery
- Byte-stable JSON report

**`tests/integration/test_idempotent_retries.py`:**
- Retry place_order with same idem_key → single effect
- Retry update_order_state → no duplicate updates
- Retry update_fill → no double fills
- Retry cancel_all → cached result

### E2E Tests

**`tests/e2e/test_exec_shadow_e2e.py`:**
- Scenario 4: Restart with recovery (`--durable-state --recover`)
- Scenario 5: Idempotent freeze cancel (`--durable-state`)

---

## CLI Flags (exec_demo.py)

```bash
# Enable durable state
python -m tools.live.exec_demo \
  --shadow \
  --durable-state \
  --state-dir artifacts/state \
  --symbols BTCUSDT \
  --iterations 50

# Recover from snapshot
python -m tools.live.exec_demo \
  --shadow \
  --durable-state \
  --state-dir artifacts/state \
  --recover \
  --symbols BTCUSDT \
  --iterations 50
```

---

## Метрики и Логи

### Метрики

**ExecutionLoop stats:**
- `orders_placed`: Total orders placed
- `orders_filled`: Total fills
- `orders_canceled`: Total cancels (including freeze)
- `freeze_events`: Number of freeze triggers

**DurableOrderStore:**
- `snapshot_saved_at`: Timestamp of last snapshot
- `snapshot_order_count`: Number of orders in snapshot
- `idempotency_cache_hits`: Number of idem_key cache hits

### Логи

**ExecutionLoop:**
```python
logger.info(f"[IDEM] place_order with key={idem_key}")
logger.warning(f"[FREEZE] cancel_all triggered, idem_key={freeze_idem_key}")
logger.info(f"[RECOVERY] Recovered {count} open orders")
```

**DurableOrderStore:**
```python
logger.info(f"[SNAPSHOT] Saved {count} orders to {snapshot_file}")
logger.info(f"[IDEM HIT] place_order key={idem_key} → cached result")
logger.info(f"[RECOVER] Loaded {count} orders from snapshot")
```

---

## Будущие расширения (P0.9+)

1. **Live Redis**: Реальное подключение к Redis (пока in-memory fake)
2. **Prometheus metrics**: Экспорт метрик в Prometheus формат
3. **Distributed Redlock**: Поддержка нескольких Redis узлов
4. **Stream processing**: Redis Streams для event sourcing
5. **Alert integration**: Trigger alerts на freeze events

---

## Ссылки

- [RUNBOOK_SHADOW.md](docs/RUNBOOK_SHADOW.md) — Операционная документация
- [tools/state/redis_client.py](tools/state/redis_client.py) — RedisKV implementation
- [tools/state/locks.py](tools/state/locks.py) — Redlock implementation
- [tools/live/order_store_durable.py](tools/live/order_store_durable.py) — DurableOrderStore
- [tools/common/retry.py](tools/common/retry.py) — Retry mechanism

---

**Версия:** P0.8  
**Дата:** 2025-10-27  
**Автор:** Staff Quant/Infra Team

