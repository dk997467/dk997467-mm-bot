# Fix: Guaranteed Cancel-All on Freeze with Store Fallback

## Problem

Когда ExecutionLoop триггерит freeze (edge < threshold), `_cancel_all_open_orders()` в текущем main **НЕ ОТМЕНЯЕТ** ордера локально:

- ❌ Использовал `exchange.get_open_orders()` вместо `order_store.get_open_orders()`
- ❌ FakeExchangeClient._orders ≠ InMemoryOrderStore._orders (разные словари)
- ❌ Результат: `exchange.get_open_orders()` → `[]`, ничего не отменяется
- ❌ **Тест падает**: `assert open_after == 0` → `assert 2 == 0`

**Лог из failing теста:**
```json
{"canceled_count":0,"event":"cancel_all_done"}
```

## Solution

### 1. **execution_loop.py** - Robust Cancel-All Logic

**Изменения:**
- ✅ Строка 590: `order_store.get_open_orders()` — source of truth
- ✅ Best-effort отмена на exchange (bulk → generic → per-order)
- ✅ **Обязательная** локальная отмена через `store.cancel()` или `store.remove()`
- ✅ Accurate `canceled_count` в структурированных логах

**Ключевой код (строки 627-648):**
```python
# Локальная отмена — обязательна
for o in open_orders:
    did_cancel = False
    
    # Try cancel() first (changes state to CANCELED)
    if hasattr(self.order_store, "cancel"):
        try:
            self.order_store.cancel(o.client_order_id)
            did_cancel = True
        except Exception as e:
            logger.debug(f"Failed to cancel {o.client_order_id}: {e}")
    
    # If cancel failed, try remove() (physically removes order)
    if not did_cancel and hasattr(self.order_store, "remove"):
        try:
            self.order_store.remove(o.client_order_id)
            did_cancel = True
        except Exception as e:
            logger.debug(f"Failed to remove {o.client_order_id}: {e}")
    
    if did_cancel:
        canceled += 1
```

### 2. **order_store.py** - Add Missing Methods

**Добавлены методы (строки 176-185):**

```python
def cancel(self, client_order_id: str) -> None:
    """Cancel an order by changing its state to CANCELED."""
    if client_order_id in self._orders:
        self._orders[client_order_id].state = OrderState.CANCELED
        self._orders[client_order_id].updated_at_ms = int(...)

def remove(self, client_order_id: str) -> None:
    """Physically remove an order from the store."""
    if client_order_id in self._orders:
        del self._orders[client_order_id]
```

## Tests

### ✅ Unit Test: `test_cancel_all_open_orders_on_freeze`

**Before Fix (main):**
```
FAILED: assert 2 == 0  # 2 open orders remained
canceled_count: 0
```

**After Fix:**
```
PASSED
canceled_count: 2  ✅
```

**Full suite:**
```
17 passed in 13.65s  ✅
```

### Лог успешного теста:
```json
{"canceled_count":2,"component":"execution_loop","event":"cancel_all_done","lvl":"INFO","mode":"fallback","trigger":"edge_below_threshold"}
```

## Risk Assessment

**Риск: LOW** ⚠️ Только freeze path

- ✅ Не меняет нормальный order placement flow
- ✅ Не меняет fill processing
- ✅ Fallback логика robust (3 уровня отмены на exchange + обязательная локальная)
- ✅ Idempotency path (DurableOrderStore) не затронут
- ✅ Все unit тесты проходят

## Deployment

После merge в `main`:

1. **CI автоматически запустится** (`ci.yml` → `push` trigger)
2. **Testnet проверка** (мануальная):
   - Actions → `Testnet Smoke Tests` → Run workflow → Branch: `main`
3. **Мониторинг логов** на testnet:
   - Искать `"event":"cancel_all_done"` с `canceled_count > 0`

## Files Changed

- `tools/live/execution_loop.py` (+35, -40 lines)
- `tools/live/order_store.py` (+10 lines)

---

**Branch:** `fix/execution-freeze-cancel-all`  
**Commit:** `9d6652b` - fix(exec): guaranteed cancel-all on freeze w/ store fallback + accurate canceled_count

