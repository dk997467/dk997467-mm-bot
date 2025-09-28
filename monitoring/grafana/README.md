# MM Bot Grafana Dashboard

## Импорт Dashboard

1. Откройте Grafana
2. Перейдите в **Dashboards** → **Import**
3. Загрузите файл `mm_bot_overview.json`
4. Выберите Prometheus как источник данных
5. Нажмите **Import**

## Метрики

### Flow Metrics
- `creates_total{symbol}` - Общее количество созданных ордеров
- `cancels_total{symbol}` - Общее количество отменённых ордеров
- `replaces_total{symbol}` - Общее количество заменённых/изменённых ордеров
- `quotes_placed_total{symbol}` - Общее количество размещённых котировок
- `create_rate{symbol}` - Скорость создания ордеров (ордеров/сек)
- `cancel_rate{symbol}` - Скорость отмены ордеров (ордеров/сек)
- `orders_active{symbol,side}` - Активные ордера по символу и стороне

### P&L и Fees
- `maker_pnl{symbol}` - P&L от мейкер ордеров в USD
- `taker_fees{symbol}` - Комиссии от тейкер ордеров в USD
- `inventory_abs{symbol}` - Абсолютное значение инвентаря в USD

### Market Metrics
- `spread_bps{symbol}` - Текущий спред в базисных пунктах
- `vola_1m{symbol}` - 1-минутная волатильность
- `ob_imbalance{symbol}` - Дисбаланс order book

### Risk Metrics
- `risk_paused` - Статус риск-менеджмента (0/1)
- `drawdown_day` - Дневной drawdown в процентах

### System Metrics
- `latency_ms{stage}` - Латентность по этапам (md/rest/ws)
- `ws_reconnects_total{exchange}` - Количество переподключений WebSocket
- `rest_error_rate{exchange}` - Частота ошибок REST API

### Config Metrics
- `cfg_levels_per_side` - Настроенное количество уровней с каждой стороны
- `cfg_min_time_in_book_ms` - Минимальное время в книге (мс)
- `cfg_k_vola_spread` - Коэффициент волатильности для спреда
- `cfg_skew_coeff` - Коэффициент наклона инвентаря
- `cfg_imbalance_cutoff` - Порог отсечения дисбаланса
- `cfg_max_create_per_sec` - Максимальная скорость создания (ордеров/сек)
- `cfg_max_cancel_per_sec` - Максимальная скорость отмены (ордеров/сек)

## Dashboard Panels

### Profit Row
- **Profit**: maker_pnl, taker_fees, net_pnl (вычисляемый)
- **Hit Rate**: процент успешных котировок (fills/quotes)

### Flow Row
- **Flow**: creates_total, cancels_total, replaces_total, create_rate, cancel_rate

### Risk Row
- **Risk**: inventory_abs, drawdown_day, risk_paused

### Market Row
- **Market**: spread_bps, vola_1m, ob_imbalance

### System Row
- **System**: latency p95, ws_reconnects_total, rest_error_rate
- **Active Orders**: orders_active{symbol,side}

### Config Row
- **Config**: все cfg_* gauges для мониторинга конфигурации

## Обновление

Dashboard автоматически обновляется каждые 5 секунд. При изменении конфигурации через `/admin/reload` config метрики обновляются в реальном времени.
