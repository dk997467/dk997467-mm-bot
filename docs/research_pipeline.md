# Research Pipeline Documentation

## Overview

The research pipeline provides comprehensive data collection, analysis, and optimization capabilities for the market making strategy. It consists of four main components:

1. **Data Recorder** - Collects and persists market data, order events, and PnL information
2. **PnL Attribution** - Calculates and tracks realized/unrealized PnL, fees, and inventory
3. **Backtesting Engine** - Simulates strategy performance using historical or synthetic data
4. **Parameter Tuner** - Optimizes strategy parameters using random/grid search

## Components

### 1. Research Recorder (`src/storage/research_recorder.py`)

Records comprehensive market data and order events for offline analysis:

- **Market Snapshots**: Mid price, spread, volatility, order book imbalance, our quotes
- **Order Events**: Create, cancel, replace, fill events with full context
- **Data Format**: Parquet files with hourly rotation and compression (gzip/zstd)
- **File Naming**: `research_YYYYMMDD_HH.parquet`

**Usage:**
```python
from src.storage.research_recorder import ResearchRecorder

recorder = ResearchRecorder(ctx, "./data/research")
await recorder.start()

# Record market snapshot
recorder.record_market_snapshot(symbol, orderbook, our_quotes, vola_1m)

# Record order event
recorder.record_order_event("create", order, fill_price=50000.0, fill_qty=0.001)
```

### 2. PnL Attribution (`src/metrics/pnl.py`)

Tracks and calculates PnL components:

- **Maker Rebates**: Calculated from maker fills
- **Taker Fees**: Deducted from taker fills
- **Realized PnL**: Cumulative fees/rebates
- **Unrealized PnL**: Mark-to-market position value
- **Inventory Tracking**: Position size and average prices

**Usage:**
```python
from src.metrics.pnl import PnLAttributor

pnl = PnLAttributor(ctx)

# Record a fill
pnl.record_fill("BTCUSDT", "Buy", 0.001, 50000.0, is_maker=True)

# Get PnL breakdown
breakdown = pnl.get_total_pnl("BTCUSDT", current_price=51000.0)
print(f"Total PnL: {breakdown.total_pnl}")
```

### 3. Backtesting Engine (`src/backtest/`)

#### OrderBook Replay (`src/backtest/orderbook_replay.py`)
- Replays recorded L2 data from research files
- Generates synthetic order book data for testing
- Supports time range filtering

#### Queue Simulation (`src/backtest/queue_sim.py`)
- FIFO-based fill simulation with ahead_volume
- Realistic order matching and queue positioning
- Tracks fill statistics and order states

#### Backtest Runner (`src/backtest/run.py`)
- Main execution engine for backtests
- CLI interface for running backtests
- Generates performance reports

**Usage:**
```bash
# Run backtest with recorded data
python -m src.backtest.run --data ./data/research --symbol BTCUSDT --out report.json

# Run backtest with synthetic data
python -m src.backtest.run --data ./data/research --symbol BTCUSDT --synthetic --out report.json
```

### 4. Parameter Tuner (`src/strategy/tuner.py`)

Optimizes strategy parameters using:

- **Random Search**: Random sampling within parameter bounds
- **Grid Search**: Systematic exploration of parameter space
- **Objective Function**: NetPnL - fees - λ × CVaR95

**Parameter Bounds:**
- `k_vola_spread`: [0.6, 1.4] - Volatility spread coefficient
- `skew_coeff`: [0.1, 0.6] - Inventory skew coefficient
- `levels_per_side`: [2, 4] - Number of quote levels
- `level_spacing_coeff`: [0.2, 0.6] - Level spacing coefficient
- `min_time_in_book_ms`: [300, 800] - Minimum time in book
- `replace_threshold_bps`: [0, 6] - Replace threshold in bps
- `imbalance_cutoff`: [0.55, 0.75] - Order book imbalance cutoff

**Usage:**
```bash
# Random search optimization
python -m src.strategy.tuner --data ./data/research --symbol BTCUSDT --config config.yaml --method random --trials 100 --output best_params.json

# Grid search optimization
python -m src.strategy.tuner --data ./data/research --symbol BTCUSDT --config config.yaml --method grid --density 3 --output best_params.json
```

## Configuration

Add the following to your `config.yaml`:

```yaml
# Storage Configuration
storage:
  backend: "parquet"  # parquet, csv, or sqlite
  compress: "zstd"     # zstd, gzip, or none
  batch_size: 1000     # Records per batch
  flush_ms: 200        # Flush interval in milliseconds

# Strategy Parameters
strategy:
  # ... existing parameters ...
  
  # Research and backtesting parameters
  slip_bps: 2.0  # Estimated slippage in basis points
```

## Data Flow

1. **Live Trading**: Research recorder collects market data and order events
2. **Data Persistence**: Data is written to hourly Parquet files with compression
3. **Offline Analysis**: Backtesting engine replays data or generates synthetic scenarios
4. **Parameter Optimization**: Tuner tests parameter combinations and selects best performers
5. **Strategy Updates**: Best parameters can be applied to live trading

## Performance Metrics

The backtesting engine calculates:

- **Net PnL**: Total profit/loss minus fees
- **Sharpe Ratio**: Risk-adjusted returns
- **Hit Rate**: Percentage of profitable trades
- **Max Drawdown**: Maximum peak-to-trough decline
- **CVaR95**: Conditional Value at Risk at 95% confidence
- **Queue Statistics**: Fill rates, maker/taker ratios

## File Structure

```
data/
├── research/
│   ├── research_20241201_00.parquet
│   ├── research_20241201_01.parquet
│   └── ...
├── backtest/
│   ├── reports/
│   └── parameters/
└── tuning/
    ├── results/
    └── plots/
```

## Dependencies

The research pipeline uses only existing dependencies:
- `polars` - Data manipulation and Parquet I/O
- `gzip` - Standard library compression
- `zstandard` - High-performance compression (optional)

No new external dependencies are required.

## Testing

Run the test suite:

```bash
# Test research recorder
pytest tests/test_research_recorder.py -v

# Test PnL attribution
pytest tests/test_pnl_attribution.py -v

# Test backtest queue
pytest tests/test_backtest_queue.py -v

# Test parameter tuner
pytest tests/test_tuner_bounds.py -v
```

## Integration

The research pipeline integrates with the existing system through:

- **AppContext**: Dependency injection for configuration and components
- **OrderManager**: Records order events and fills
- **MarketMakingStrategy**: Records market snapshots and quotes
- **Metrics**: Exports PnL and performance metrics to Prometheus

## Future Enhancements

- **Real-time Analysis**: Live PnL attribution and risk monitoring
- **Advanced Optimization**: Bayesian optimization, genetic algorithms
- **Multi-symbol Support**: Cross-asset correlation and optimization
- **Machine Learning**: Feature engineering and predictive models
- **Web Interface**: Interactive backtesting and parameter tuning UI
