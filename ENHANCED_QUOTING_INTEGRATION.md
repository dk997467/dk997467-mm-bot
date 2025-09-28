# EnhancedQuoter Integration with Feature Flag

## Обзор

Успешно интегрирован EnhancedQuoter в основную стратегию market making с помощью feature flag. Интеграция обеспечивает плавный переход между legacy и enhanced quoting без изменения внешнего API.

## Изменения

### 1. Конфигурация (`src/common/config.py`)
- Добавлен feature flag `enable_enhanced_quoting: bool = False` в `StrategyConfig`

### 2. Основная стратегия (`src/strategy/market_making.py`)
- Полностью переписана для поддержки EnhancedQuoter
- Добавлена логика выбора между EnhancedQuoter и legacy стратегией
- EnhancedQuoter получает `AppContext` и интегрируется в существующий pipeline котировок
- Добавлена конвертация котировок из формата EnhancedQuoter в стандартный `QuoteRequest`

### 3. Bot интеграция (`cli/run_bot.py`)
- `MarketMakerBot` теперь передает `AppContext` в стратегию
- Стратегия автоматически выбирает правильный движок котировок

### 4. Конфигурация по умолчанию (`config.yaml`)
- Включен feature flag `enable_enhanced_quoting: true`

## Архитектура

```
MarketMakerBot
    ↓
MarketMakingStrategy (с feature flag)
    ↓
┌─────────────────┬─────────────────┐
│ EnhancedQuoter  │ Legacy Strategy │
│ (если включен)  │ (fallback)      │
└─────────────────┴─────────────────┘
    ↓
Order Pipeline (одинаковый для обоих)
```

## Feature Flag Behavior

### Включен (`enable_enhanced_quoting: true`)
- Инициализируется `EnhancedQuoter` с `AppContext`
- Все котировки генерируются через EnhancedQuoter
- Используются enhanced features: volatility tracking, inventory skew, adverse selection guard

### Выключен (`enable_enhanced_quoting: false`)
- Используется legacy стратегия
- EnhancedQuoter не инициализируется
- Fallback к существующему поведению

## API Compatibility

Внешний API стратегии остается неизменным:
- `on_orderbook_update()` - принимает те же параметры
- `set_quote_callback()` - работает одинаково для обоих движков
- `get_strategy_state()` - возвращает информацию о текущем движке

## Тестирование

### Unit Tests (`tests/test_enhanced_quoting_integration.py`)
- Проверка включения/выключения feature flag
- Тестирование интеграции с AppContext
- Проверка конвертации котировок
- Тестирование fallback логики

### Integration Tests (`tests/test_bot_integration.py`)
- Проверка инициализации бота с feature flag
- Тестирование создания стратегии

## Запуск

### С EnhancedQuoter
```yaml
# config.yaml
strategy:
  enable_enhanced_quoting: true
```

### С Legacy Strategy
```yaml
# config.yaml
strategy:
  enable_enhanced_quoting: false
```

## Мониторинг

Стратегия предоставляет информацию о текущем состоянии:
```python
state = strategy.get_strategy_state()
print(f"Quoting engine: {state['quoting_engine']}")  # "enhanced" или "legacy"
print(f"Enhanced features: {state['enhanced_features']}")
```

## Преимущества

1. **Безопасность**: Feature flag позволяет включать/выключать enhanced функциональность
2. **Совместимость**: Внешний API не изменяется
3. **Мониторинг**: Прозрачность о том, какой движок используется
4. **Fallback**: Автоматический переход к legacy стратегии при проблемах
5. **Тестирование**: Полное покрытие тестами для обеих веток

## Следующие шаги

1. Мониторинг производительности EnhancedQuoter в production
2. A/B тестирование между legacy и enhanced стратегиями
3. Постепенное включение для разных символов
4. Сбор метрик для сравнения эффективности
