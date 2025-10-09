# Queue-Aware & Inventory-Skew - Quick Start

## ✅ Что Сделано

Добавлены две оптимизации для снижения slippage и повышения net bps:

1. **Queue-Aware Quoting** - микро-подвыставление на основе позиции в очереди
2. **Inventory-Skew** - автоматическая разгрузка через сдвиг спреда

---

## 🚀 Быстрый Старт

### 1. Запустить Тесты

```bash
# All tests
pytest tests/unit/test_queue_aware.py tests/unit/test_inventory_skew.py tests/sim/test_queue_inventory_effect.py -v
```

### 2. Интеграция (Автоматическая!)

Если у вас уже используется `QuoteLoop` из предыдущей задачи (fast-cancel/taker-cap), то **queue-aware и inventory-skew уже интегрированы**!

Просто убедитесь, что конфиги включены в `config.yaml` (по умолчанию `enabled: true`).

### 3. Использование в Коде

```python
from src.strategy.quote_loop import QuoteLoop, Quote

# QuoteLoop уже содержит queue_aware и inventory_skew
quote_loop = QuoteLoop(ctx, order_manager)

# В цикле котирования:
# 1) Базовая котировка
base_quote = Quote(symbol="BTCUSDT", side="bid", price=50000.0, size=1.0)

# 2) Применить queue-aware nudge
nudged_quote = quote_loop.apply_queue_aware_nudge(
    base_quote, orderbook, fair_value=50000.5
)
if nudged_quote:
    base_quote = nudged_quote

# 3) Применить inventory-skew к bid/ask
result = quote_loop.apply_inventory_skew_adjustment(
    symbol="BTCUSDT",
    bid_price=49999.0,
    ask_price=50001.0,
    position_base=current_position,
    max_position_base=10.0
)

# Использовать скорректированные цены
bid_final = result['bid_price']
ask_final = result['ask_price']
```

---

## 📊 Мониторинг

```python
# Получить метрики
queue_stats = quote_loop.get_queue_metrics()
inv_stats = quote_loop.get_inventory_skew_metrics()

print(f"Queue nudges: {queue_stats['queue_nudges_count']}")
print(f"Avg delta: {queue_stats['queue_avg_delta_bps']:.2f}bps")
print(f"Inv skew avg: {inv_stats['inv_skew_avg_bps']:.2f}bps")
```

### Логи

Ищите теги в логах:
- `[QUEUE]` - события queue-aware nudging
- `[SKEW]` - события inventory-skew adjustment

---

## ⚙️ Настройка

В `config.yaml`:

```yaml
# Отключить queue-aware:
queue_aware:
  enabled: false

# Отключить inventory-skew:
inventory_skew:
  enabled: false

# Настроить агрессивность:
queue_aware:
  max_reprice_bps: 1.0  # Больше micro-nudging
  join_threshold_pct: 50.0  # Чаще срабатывает

inventory_skew:
  max_skew_bps: 1.0  # Сильнее skew
  slope_bps_per_1pct: 0.15  # Быстрее реакция
```

---

## 📈 Ожидаемые Результаты

После 6-12h soak:
- `slippage_bps`: ↓ 0.3-0.7 bps
- `order_age_p95_ms`: ↓
- `taker_share_pct`: не растёт
- `net_bps`: ≥ baseline

---

## 📞 Troubleshooting

**Q: Слишком часто queue nudging?**
A: Увеличь `headroom_ms` в `config.yaml`

**Q: Inventory не балансируется?**
A: Уменьши `clamp_pct` или увеличь `slope_bps_per_1pct`

**Q: Rate-limit ошибки увеличились?**
A: Увеличь `headroom_ms` или отключи `queue_aware.enabled`

---

**Готово к использованию!** ✅
