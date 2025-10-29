# Execution Engine - Shadow Trading

## Overview

P0.1 Execution Engine provides a deterministic shadow trading system for testing execution logic without real exchange connectivity. Built with pure stdlib (no external dependencies), it integrates with `RuntimeRiskMonitor` for pre-trade risk checks and position limits.

## Installation

### Basic Installation (Shadow/Soak/CI)

For shadow mode, soak tests, and CI workflows, install the base package:

```bash
pip install -e .
```

This installs all core dependencies **without** exchange SDKs.

### Live Trading Installation

For live trading with real exchange connectivity, install with the `[live]` extras:

```bash
pip install -e .[live]
```

Or install live dependencies separately:

```bash
pip install -r requirements_live.txt
```

**What's included in `[live]`:**
- `bybit-connector>=3.0.0` - Bybit exchange SDK
- (Future: Additional exchange SDKs)

**Why separate?**
- Keeps CI lightweight (no SDK bloat)
- Exchange SDKs may have platform-specific requirements
- Clear separation between shadow/testing and live trading

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      EXECUTION LOOP                              │
│                                                                  │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│  │   Quote      │      │ Risk Check   │      │   Order      │ │
│  │  Generator   │─────▶│   Monitor    │─────▶│   Store      │ │
│  └──────────────┘      └──────────────┘      └──────────────┘ │
│         │                     │                      │          │
│         │                     │                      │          │
│         ▼                     ▼                      ▼          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            IExchangeClient (Protocol)                    │  │
│  │                                                           │  │
│  │    ┌─────────────────┐       ┌──────────────────┐       │  │
│  │    │ FakeExchange    │  OR   │  RealExchange    │       │  │
│  │    │ (Deterministic) │       │  (Future)        │       │  │
│  │    └─────────────────┘       └──────────────────┘       │  │
│  └──────────────────────────────────────────────────────────┘  │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│  │  Fill Event  │─────▶│   Position   │─────▶│   Freeze     │ │
│  │   Stream     │      │   Tracker    │      │   Trigger    │ │
│  └──────────────┘      └──────────────┘      └──────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Exchange Layer (`tools/live/exchange.py`)

**IExchangeClient (Protocol)**:
```python
class IExchangeClient(Protocol):
    def place_limit(req: PlaceOrderRequest) -> PlaceOrderResponse
    def cancel(order_id: str) -> bool
    def get_open_orders(symbol: str | None = None) -> list[OpenOrder]
    def get_positions() -> list[Position]
    def stream_fills() -> Iterator[FillEvent]
```

**FakeExchangeClient**:
- Deterministic behavior with configurable parameters:
  - `fill_rate`: Probability of order being filled (0.0-1.0)
  - `reject_rate`: Probability of order being rejected (0.0-1.0)
  - `latency_ms`: Simulated exchange latency
  - `partial_fill_rate`: Probability of partial fills
  - `seed`: Random seed for reproducibility

- Supports `MM_FREEZE_UTC_ISO` for deterministic timestamps
- Tracks internal state: orders, positions, pending fills

### 2. Order Store (`tools/live/order_store.py`)

**Order Lifecycle States**:
```
┌──────────┐
│ PENDING  │ (Before submission)
└────┬─────┘
     │ place_order()
     ▼
┌──────────┐
│   OPEN   │ (Active on exchange)
└────┬─────┘
     │
     ├────▶ ┌──────────────────┐
     │      │ PARTIALLY_FILLED │
     │      └────────┬─────────┘
     │               │
     ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│  FILLED  │   │ CANCELED │   │ REJECTED │
└──────────┘   └──────────┘   └──────────┘
```

**InMemoryOrderStore**:
- Atomic operations for state transitions
- Deterministic client order ID generation (`CLI00000001`, ...)
- Query by state, symbol, or order ID
- Export to dict for reporting

### 3. Execution Loop (`tools/live/execution_loop.py`)

**Core Workflow**:
1. **on_quote()**: Handle market quote
   - Check if system is frozen
   - Generate bid/ask orders
   - Check risk limits (`RuntimeRiskMonitor.check_before_order()`)
   - Place order via exchange
   - Track in order store

2. **on_fill()**: Process fill events
   - Match fill to order
   - Update order fill quantity
   - Notify risk monitor (`on_fill()`)
   - Update statistics

3. **on_edge_update()**: Update edge and check freeze
   - Notify risk monitor (`on_edge_update()`)
   - If freeze triggered, cancel all open orders
   - Track freeze events

**run_shadow()**:
- Simulate N iterations
- Generate synthetic quotes for each symbol
- Process fills and edge updates
- Return deterministic JSON report

### 4. Risk Integration

Integrates with `RuntimeRiskMonitor` (from P0.6):
- **Pre-trade checks**: `check_before_order(symbol, side, qty, price)`
- **Fill notifications**: `on_fill(symbol, side, qty, price)`
- **Edge monitoring**: `on_edge_update(symbol, net_bps)`
- **Freeze detection**: `is_frozen()`, triggers order cancellation

Limits enforced:
- `max_inventory_usd_per_symbol`: Maximum position value per symbol
- `max_total_notional_usd`: Maximum total portfolio notional
- `edge_freeze_threshold_bps`: Edge threshold (in bps) below which system freezes

### 5. CLI Demo (`tools/live/exec_demo.py`)

```bash
python -m tools.live.exec_demo \
  --shadow \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 50 \
  --max-inv 10000 \
  --max-total 50000 \
  --edge-threshold 1.5 \
  --fill-rate 0.7 \
  --reject-rate 0.05 \
  --latency-ms 100
```

**Output** (deterministic JSON):
```json
{
  "execution": {
    "iterations": 50,
    "symbols": ["BTCUSDT", "ETHUSDT"]
  },
  "orders": {
    "placed": 42,
    "filled": 28,
    "rejected": 2,
    "canceled": 5,
    "risk_blocks": 7
  },
  "positions": {
    "by_symbol": {
      "BTCUSDT": 0.15,
      "ETHUSDT": 1.2
    },
    "net_pos_usd": {
      "BTCUSDT": 7500.0,
      "ETHUSDT": 3600.0
    },
    "total_notional_usd": 11100.0
  },
  "risk": {
    "frozen": true,
    "freeze_events": 1,
    "last_freeze_reason": "Edge below threshold",
    "last_freeze_symbol": "BTCUSDT",
    "blocks_total": 7,
    "freezes_total": 1
  },
  "runtime": {
    "utc": "2025-01-01T00:00:00Z"
  }
}
```

## Usage Examples

### Basic Shadow Run

```python
from tools.live.execution_loop import run_shadow_demo

report_json = run_shadow_demo(
    symbols=["BTCUSDT", "ETHUSDT"],
    iterations=50,
    max_inventory_usd_per_symbol=10000.0,
    max_total_notional_usd=50000.0,
    edge_freeze_threshold_bps=1.5,
    fill_rate=0.7,
    reject_rate=0.05,
    latency_ms=100,
)

print(report_json)  # Deterministic JSON output
```

### Custom Components

```python
from tools.live.exchange import FakeExchangeClient
from tools.live.order_store import InMemoryOrderStore
from tools.live.execution_loop import ExecutionLoop, ExecutionParams, Quote
from tools.live.risk_monitor import RuntimeRiskMonitor

# Create components
exchange = FakeExchangeClient(
    fill_rate=0.8,
    reject_rate=0.05,
    latency_ms=120,
    seed=42,
)

order_store = InMemoryOrderStore()

risk_monitor = RuntimeRiskMonitor(
    max_inventory_usd_per_symbol=10000.0,
    max_total_notional_usd=50000.0,
    edge_freeze_threshold_bps=2.0,
)

loop = ExecutionLoop(exchange, order_store, risk_monitor)

# Simulate trading
params = ExecutionParams(
    symbols=["BTCUSDT"],
    iterations=10,
    max_inventory_usd_per_symbol=10000.0,
    max_total_notional_usd=50000.0,
    edge_freeze_threshold_bps=2.0,
)

report = loop.run_shadow(params)
print(report)
```

### Manual Quote Processing

```python
from tools.live.execution_loop import Quote

# Feed quotes manually
quote = Quote(
    symbol="BTCUSDT",
    bid=49990.0,
    ask=50010.0,
    timestamp_ms=1234567890000,
)

loop.on_quote(quote, params)

# Process fills
loop.on_fill()

# Update edge
loop.on_edge_update("BTCUSDT", 3.5)  # 3.5 bps edge
```

## Testing

### Unit Tests

```bash
# Test FakeExchangeClient (14 tests)
pytest tests/unit/test_fake_exchange_unit.py -v

# Test ExecutionLoop (20+ tests)
pytest tests/unit/test_execution_loop_unit.py -v
```

### E2E Tests

```bash
# Test CLI scenarios (3 scenarios)
pytest tests/e2e/test_exec_shadow_e2e.py -v
```

### Coverage

```bash
# Check coverage (target: ≥85%)
pytest tests/unit/test_fake_exchange_unit.py \
       tests/unit/test_execution_loop_unit.py \
       --cov=tools.live.exchange \
       --cov=tools.live.order_store \
       --cov=tools.live.execution_loop \
       --cov-report=term-missing
```

## Determinism

All components are fully deterministic for testing:

1. **Timestamps**: Support `MM_FREEZE_UTC_ISO` environment variable
   ```bash
   export MM_FREEZE_UTC_ISO="2025-01-01T00:00:00Z"
   ```

2. **Random Behavior**: Seeded RNG in `FakeExchangeClient`
   ```python
   client = FakeExchangeClient(seed=42)  # Reproducible behavior
   ```

3. **JSON Output**: Sorted keys, compact separators, trailing newline
   ```python
   json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
   ```

4. **Order IDs**: Sequential and deterministic
   - Client IDs: `CLI00000001`, `CLI00000002`, ...
   - Exchange IDs: `ORD000001`, `ORD000002`, ...

## Integration with P0.6 Risk Monitor

```
┌─────────────────────────────────────────────────────────┐
│              RuntimeRiskMonitor (P0.6)                  │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐           │
│  │ Position Limits  │  │  Edge Monitor    │           │
│  │ - Per Symbol     │  │ - Freeze @ drop  │           │
│  │ - Total Notional │  │ - Cancel orders  │           │
│  └────────┬─────────┘  └────────┬─────────┘           │
│           │                     │                      │
└───────────┼─────────────────────┼──────────────────────┘
            │                     │
            ▼                     ▼
┌─────────────────────────────────────────────────────────┐
│            ExecutionLoop (P0.1)                         │
│                                                         │
│  on_quote() ───▶ check_before_order()                  │
│  on_fill()  ───▶ on_fill()                             │
│  on_edge_update() ───▶ on_edge_update()                │
│                                                         │
│  If frozen: skip quote processing                      │
│  If freeze triggered: cancel all orders                │
└─────────────────────────────────────────────────────────┘
```

## Bybit Adapter (Shadow/Dry-Run) — P0.2

**Status**: ✅ **Implemented** (shadow/dry-run mode only, no real trading)

### Overview

The `BybitRestClient` implements the `IExchangeClient` protocol for Bybit exchange integration in shadow/dry-run mode. It provides:

- **HMAC SHA256 request signing** (Bybit V5 API standard)
- **Token bucket rate limiting** (configurable capacity and refill rate)
- **Dry-run order execution** (local tracking, no real API calls)
- **Secret masking** in logs (via `SecretProvider` from P0.7)
- **Full determinism** for testing and auditing

**⚠️ Important**: No real orders are placed. All operations are simulated locally.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│             BybitRestClient (IExchangeClient)                │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐ │
│  │ Request Signer │  │ Rate Limiter   │  │ Order Store   │ │
│  │ (HMAC SHA256)  │  │ (Token Bucket) │  │ (In-Memory)   │ │
│  └────────┬───────┘  └────────┬───────┘  └───────┬───────┘ │
│           │                   │                   │          │
│           ▼                   ▼                   ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         Network Layer (--no-network by default)      │   │
│  │                                                       │   │
│  │    network_enabled=False  ──▶  Local Simulation     │   │
│  │    network_enabled=True   ──▶  NotImplementedError   │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Features

#### 1. Request Signing (HMAC SHA256)

Bybit V5 API signature format:
```
sign = HMAC_SHA256(api_secret, timestamp + api_key + recv_window + query_string)
```

Example (deterministic for testing):
```python
timestamp = 1609459200000  # Fixed for testing
api_key = "your_api_key"
recv_window = 5000
query_string = "symbol=BTCUSDT&side=Buy"

signature = _generate_signature(timestamp, api_key, recv_window, query_string)
```

#### 2. Rate Limiting (Token Bucket)

Default configuration:
- **Capacity**: 100 tokens
- **Refill Rate**: 10 tokens/second
- **Injectable Clock**: For deterministic testing

```python
# Rate limiter blocks requests when tokens exhausted
if not rate_limiter.acquire(1):
    return {"retCode": 10006, "retMsg": "rate limit exceeded"}
```

#### 3. Dry-Run Behavior

**Order Placement**:
- Creates order in `InMemoryOrderStore` with `OPEN` state
- Schedules fill event based on `fill_rate` and `fill_latency_ms`
- Uses deterministic hash of `client_order_id` for reproducibility
- Returns success response with dry-run marker

**Order Cancellation**:
- Transitions order to `CANCELED` state in local store
- Removes from scheduled fills queue
- No API call made

**Fill Generation**:
- `stream_fills()` polls scheduled fills based on clock
- When `fill_time_ms <= current_time`, generates `FillEvent`
- Updates order state to `FILLED`
- Tracks filled quantity and average price

#### 4. Secret Management

Integrates with `SecretProvider` (P0.7):
```python
client = BybitRestClient(
    secret_provider=SecretProvider(backend="memory"),
    api_env="dev",  # or "shadow", "soak", "prod"
    network_enabled=False,
)
```

Secrets are masked in all log outputs:
```python
# Log output example
{"event": "bybit_client_init", "api_key": "tes...***", "network_enabled": false}
```

### Usage Examples

#### Example 1: Basic Shadow Run with Bybit

```bash
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --mode shadow \
  --no-network \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 50 \
  --max-inv 10000 \
  --max-total 50000 \
  --edge-threshold 1.5 \
  --fill-rate 0.8 \
  --latency-ms 100
```

Output (deterministic JSON):
```json
{
  "execution": {"iterations": 50, "symbols": ["BTCUSDT", "ETHUSDT"]},
  "orders": {"placed": 45, "filled": 36, "rejected": 0, "canceled": 3, "risk_blocks": 6},
  "positions": {"by_symbol": {"BTCUSDT": 0.18, "ETHUSDT": 1.5}, ...},
  "risk": {"frozen": false, "freeze_events": 0, ...}
}
```

#### Example 2: Programmatic Usage

```python
from tools.live.exchange_bybit import BybitRestClient
from tools.live.secrets import SecretProvider
from tools.live.execution_loop import ExecutionLoop, ExecutionParams
from tools.live.order_store import InMemoryOrderStore
from tools.live.risk_monitor import RuntimeRiskMonitor

# Create Bybit client (dry-run)
secret_provider = SecretProvider(backend="memory")
bybit_client = BybitRestClient(
    secret_provider=secret_provider,
    api_env="dev",
    network_enabled=False,
    fill_rate=0.9,
    fill_latency_ms=100,
    seed=42,
)

# Create execution loop
order_store = InMemoryOrderStore()
risk_monitor = RuntimeRiskMonitor(
    max_inventory_usd_per_symbol=10000.0,
    max_total_notional_usd=50000.0,
    edge_freeze_threshold_bps=1.5,
)

loop = ExecutionLoop(
    exchange=bybit_client,
    order_store=order_store,
    risk_monitor=risk_monitor,
)

# Run shadow trading
params = ExecutionParams(
    symbols=["BTCUSDT"],
    iterations=20,
    max_inventory_usd_per_symbol=10000.0,
    max_total_notional_usd=50000.0,
    edge_freeze_threshold_bps=1.5,
)

report = loop.run_shadow(params)
print(json.dumps(report, indent=2))
```

#### Example 3: Integration with Risk Monitor

```python
# Place order with risk checks
from tools.live.exchange import PlaceOrderRequest, Side

request = PlaceOrderRequest(
    client_order_id="CLI00000001",
    symbol="BTCUSDT",
    side=Side.BUY,
    qty=0.1,
    price=50000.0,
)

# Risk check happens in ExecutionLoop.on_quote()
# If limits exceeded, order is blocked
response = bybit_client.place_limit_order(request)

if response.success:
    print(f"Order placed: {response.order_id}")
else:
    print(f"Order rejected: {response.message}")
```

### CLI Flags

New flags added in P0.2:

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--exchange` | `fake`, `bybit` | `fake` | Exchange client to use |
| `--mode` | `shadow`, `dryrun` | `shadow` | Trading mode |
| `--no-network` | flag | `True` | Disable network calls (safety) |
| `--api-env` | `dev`, `shadow`, `soak`, `prod` | `dev` | Environment for `SecretProvider` |

### Limitations

**Current Scope (P0.2)**:
- ✅ Dry-run mode only (no real orders)
- ✅ No network calls by default (`--no-network`)
- ✅ Local order tracking (`InMemoryOrderStore`)
- ✅ Deterministic fill generation
- ✅ HMAC signing (tested, not executed)
- ✅ Rate limiting (tested, not enforced on real API)

**Not Implemented**:
- ❌ Real API calls (intentionally disabled for safety)
- ❌ WebSocket order book streaming
- ❌ Advanced order types (FOK, IOC, stop-loss)
- ❌ Partial fills from real exchange
- ❌ Persistent order storage

**Security Constraints**:
- `network_enabled=True` raises `NotImplementedError` (safety guard)
- All secrets masked in logs
- No credentials in repo or test files
- Dry-run marker in all responses

### Testing

**Unit Tests** (`tests/unit/test_bybit_client_unit.py`):
- 21 tests, 100% passing
- Coverage: 85%
- Tests: signing, rate-limit, dry-run, masking

**Integration Tests** (`tests/integration/test_exec_bybit_risk_integration.py`):
- Freeze triggers cancel-all
- Risk limits block orders
- Deterministic reports

**E2E Tests** (`tests/e2e/test_exec_bybit_shadow_e2e.py`):
- 3 scenarios with byte-for-byte golden comparison
- CLI execution with `--exchange bybit`

Run all tests:
```bash
# Unit tests
pytest tests/unit/test_bybit_client_unit.py -v

# Integration tests
pytest tests/integration/test_exec_bybit_risk_integration.py -v

# E2E tests
pytest tests/e2e/test_exec_bybit_shadow_e2e.py -v

# Coverage
pytest tests/unit/test_bybit_client_unit.py \
      --cov=tools.live.exchange_bybit \
      --cov-report=term-missing
```

### Secrets Setup

See [SECRETS_OPERATIONS.md](SECRETS_OPERATIONS.md) for detailed setup.

Quick start:
```bash
# Memory backend (for testing)
export BYBIT_API_KEY="test_key"
export BYBIT_API_SECRET="test_secret"

# AWS Secrets Manager (for production)
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env shadow \
  --api-key "your_key" \
  --api-secret "your_secret"
```

### Troubleshooting

**Issue**: "No value found for BYBIT_API_KEY"
- **Fix**: Set environment variables or use `SecretProvider` with AWS backend

**Issue**: "Network-enabled mode not implemented"
- **Fix**: This is intentional. Use `--no-network` (default)

**Issue**: "rate limit exceeded"
- **Fix**: Increase rate limit capacity or refill rate in `BybitRestClient` constructor

**Issue**: Orders not filling
- **Fix**: Increase `--fill-rate` or reduce `--latency-ms`

**Issue**: Non-deterministic output
- **Fix**: Set `MM_FREEZE_UTC_ISO` and use fixed seed

### Next Steps (Future Work)

- [ ] Enable real API calls with explicit opt-in flag
- [ ] WebSocket integration for live order book
- [ ] Partial fill support from real exchange
- [ ] Advanced order types (FOK, IOC, stop-loss)
- [ ] Multi-account support
- [ ] Persistent order store (Redis/PostgreSQL)
- [ ] Performance benchmarking against real API

### References

- [Bybit API Documentation](https://bybit-exchange.github.io/docs/v5/intro)
- [SECRETS_OPERATIONS.md](SECRETS_OPERATIONS.md) - API key management
- [RUNBOOK_SHADOW.md](RUNBOOK_SHADOW.md) - Shadow mode checklist
- P0.7: Secrets Management (`tools/live/secrets.py`)

---

## Future Enhancements

- [ ] Other exchange adapters (Binance, KuCoin, OKX)
- [ ] WebSocket streaming for quotes
- [ ] Persistent order store (SQLite/Redis)
- [ ] Advanced order types (FOK, IOC, stop-loss)
- [ ] Multiple account support
- [ ] Performance profiling
- [ ] Load testing scenarios

## Security Notes

- **No Real Trading**: This is a shadow/simulation engine only
- **No API Keys**: FakeExchangeClient does not require credentials
- **No Network Calls**: Fully local execution
- **No File I/O in Tests**: All state is in-memory

When integrating real exchange clients:
- Use `SecretProvider` (from P0.7) for API key management
- Implement retry logic with exponential backoff
- Add circuit breakers for API failures
- Monitor rate limits

## Performance

Typical benchmark (local machine):
- **50 iterations, 2 symbols**: ~5ms (with latency_ms=1)
- **500 iterations, 5 symbols**: ~50ms (with latency_ms=1)
- **Memory footprint**: < 10MB for 1000+ orders

Bottlenecks:
- `latency_ms` parameter (simulated network delay)
- JSON serialization for large reports

## Troubleshooting

### "System frozen" in logs
- Check edge threshold: `--edge-threshold`
- Review `net_bps` in `on_edge_update()` calls
- Verify freeze reason in report: `report["risk"]["last_freeze_reason"]`

### No fills
- Increase `fill_rate`: `--fill-rate 1.0`
- Check order state in store: `order_store.get_by_state(OrderState.OPEN)`
- Verify exchange behavior: `exchange.stream_fills()`

### Risk blocks orders
- Increase limits: `--max-inv`, `--max-total`
- Check current positions: `risk_monitor.get_positions()`
- Review `report["orders"]["risk_blocks"]`

### Non-deterministic output
- Set `MM_FREEZE_UTC_ISO` for fixed timestamps
- Use same seed for `FakeExchangeClient`
- Verify JSON keys are sorted

## VIP Fees & Per-Symbol Schedules (P0.11)

The execution engine supports flexible fee/rebate calculations via **VIP Fee Profiles**, allowing per-symbol or per-tier fee schedules.

### Fee Structure

All fees and rebates are expressed in **basis points (BPS)**:
- **Maker Fee**: Fee paid for maker orders (e.g., 1.0 BPS = 0.01%)
- **Taker Fee**: Fee paid for taker orders (e.g., 7.0 BPS = 0.07%)
- **Maker Rebate**: Income earned for maker orders (e.g., 2.0 BPS = 0.02%)

### Per-Symbol Profiles

Located in `tools/live/fees_profiles.py`, includes pre-defined VIP tiers:

```python
from tools.live.fees_profiles import VIP2_PROFILE, build_profile_map

# VIP2 profile: maker=0.5bps, taker=5.0bps, rebate=2.5bps
profile_map = build_profile_map("VIP2")

# Or custom per-symbol:
profile_map = {
    "BTCUSDT": VIP2_PROFILE,  # BTC gets VIP2 rates
    "ETHUSDT": VIP0_PROFILE,  # ETH gets VIP0 rates
    "*": VIP1_PROFILE,        # All other symbols get VIP1 rates
}
```

### Usage in Reconciliation

Fee profiles integrate with reconciliation:

```python
from tools.live.fees import calc_fees_and_rebates
from tools.live.fees_profiles import build_profile_map

# Default schedule (fallback)
default_schedule = FeeSchedule(
    maker_bps=Decimal("1.0"),
    taker_bps=Decimal("7.0"),
    maker_rebate_bps=Decimal("2.0"),
)

# Apply VIP2 profile
profile_map = build_profile_map("VIP2")

# Calculate fees with per-symbol profiles
fees_report = calc_fees_and_rebates(
    fills=fills,
    fee_schedule=default_schedule,
    profile_map=profile_map,
)
```

### CLI Exposure (Future)

*Note: CLI flags for profiles coming in P0.12. Current usage is Python API only.*

Planned CLI syntax:
```bash
# Future: Apply VIP2 tier to all symbols
python -m tools.live.exec_demo --shadow --fee-tier VIP2 --symbols BTCUSDT,ETHUSDT

# Future: Per-symbol profiles via JSON config
python -m tools.live.exec_demo --shadow --fee-profiles fees_config.json
```

### Pre-Defined Profiles

| Tier | Maker BPS | Taker BPS | Rebate BPS | Use Case |
|------|-----------|-----------|------------|----------|
| VIP0 | 1.0 | 7.0 | 0.0 | Standard retail |
| VIP1 | 0.8 | 6.5 | 1.0 | Active trader |
| VIP2 | 0.5 | 5.0 | 2.5 | High-volume trader |
| VIP3 | 0.2 | 4.0 | 3.0 | Institutional |
| MM_Tier_A | 0.0 | 3.0 | 5.0 | Market maker (strong rebate) |

### Fallback Behavior

- **Exact symbol match**: Use profile for that symbol
- **Wildcard match (`*`)**: Use wildcard profile
- **No match**: Fall back to `fee_schedule` (CLI flags: `--fee-maker-bps`, `--fee-taker-bps`, `--rebate-maker-bps`)

### Testing

Unit tests verify:
- Profile selection (exact, wildcard, fallback)
- Per-symbol override behavior
- Decimal exactness (no floating-point errors)

```bash
pytest tests/unit/test_fees_profiles_unit.py -v
```

### References

- `tools/live/fees_profiles.py` — VIP profile definitions
- `tools/live/fees.py` — Fee/rebate calculation engine
- `RECON_OPERATIONS.md` — Reconciliation with per-symbol fees
- `RUNBOOK_SHADOW.md` — P0.11 VIP fees section

## References

- P0.6: Runtime Risk Monitor (`tools/live/risk_monitor.py`)
- P0.7: Secrets Management (`tools/live/secrets.py`)
- P0.10: Reconciliation & Fees (`tools/live/recon.py`, `tools/live/fees.py`)
- P0.11: VIP Fee Profiles (`tools/live/fees_profiles.py`)
- Test coverage: `pytest --cov` for all modules

