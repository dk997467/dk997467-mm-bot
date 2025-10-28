# Shadow Mode Runbook — Bybit Adapter

## Overview

This runbook provides step-by-step procedures for launching, monitoring, and troubleshooting shadow trading with the Bybit adapter (`BybitRestClient`).

**Status**: P0.2 Complete — Dry-Run Mode Only (**No Real Orders**)

**Last Updated**: 2025-10-27

---

## Table of Contents

1. [Pre-Launch Checklist](#pre-launch-checklist)
2. [Environment Setup](#environment-setup)
3. [Credential Configuration](#credential-configuration)
4. [Launch Commands](#launch-commands)
5. [Monitor & Observe](#monitor--observe)
6. [Read Reports](#read-reports)
7. [Freeze Events](#freeze-events)
8. [Troubleshooting](#troubleshooting)
9. [Post-Run Checklist](#post-run-checklist)
10. [Emergency Procedures](#emergency-procedures)

---

## Pre-Launch Checklist

Before starting a shadow run, verify:

### System Requirements

- [ ] **Python 3.11+** installed
- [ ] **All dependencies** installed (`pip install -r requirements.txt`)
- [ ] **Environment variables** set (see [Environment Setup](#environment-setup))
- [ ] **Secrets configured** (see [Credential Configuration](#credential-configuration))
- [ ] **Disk space** > 1GB available (for logs and reports)

### Code & Tests

- [ ] **Latest code** pulled from `main` or relevant branch
- [ ] **Unit tests** passing (`pytest tests/unit/test_bybit_client_unit.py`)
- [ ] **Integration tests** passing (`pytest tests/integration/test_exec_bybit_risk_integration.py`)
- [ ] **No uncommitted changes** in working directory (unless testing locally)

### Configuration Review

- [ ] **Risk limits** reviewed (`--max-inv`, `--max-total`)
- [ ] **Edge threshold** appropriate for scenario (`--edge-threshold`)
- [ ] **Fill rate** set correctly (`--fill-rate`)
- [ ] **Network disabled** (`--no-network` is default and MUST be used for P0.2)

---

## Environment Setup

### Required Environment Variables

```bash
# Shadow mode flag (MUST be set)
export MM_FREEZE_UTC_ISO="2025-01-01T00:00:00Z"  # For deterministic timestamps

# Secrets backend
export SECRETS_BACKEND="memory"  # or "aws" for production

# Exchange environment
export MM_ENV="dev"  # or "shadow", "soak", "prod"

# Optional: AWS region (if using AWS Secrets Manager)
export AWS_REGION="us-east-1"
```

### Optional: Set Deterministic Seed

For reproducible results:

```bash
export PYTHONHASHSEED=42
```

---

## Credential Configuration

### Method 1: Memory Backend (Testing)

```bash
# Set credentials via environment variables
export BYBIT_API_KEY="test_api_key_for_shadow"
export BYBIT_API_SECRET="test_api_secret_for_shadow"

# Verify
python -m tools.live.secrets_cli fetch --exchange bybit --env dev
```

**Output**:
```json
{
  "api_key": "tes...***",
  "api_secret": "tes...***",
  "exchange": "bybit",
  "env": "dev"
}
```

### Method 2: AWS Secrets Manager (Production)

```bash
# Ensure AWS credentials are configured
aws sts get-caller-identity

# Save secrets
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env shadow \
  --key-type api_key \
  --value "your_actual_api_key"

python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env shadow \
  --key-type api_secret \
  --value "your_actual_api_secret"

# Verify (output will be masked)
python -m tools.live.secrets_cli fetch --exchange bybit --env shadow
```

### Validation Test

```python
# Test credentials are accessible
python3 << EOF
from tools.live.secrets import SecretProvider

provider = SecretProvider(backend="memory")  # or "aws"
api_key = provider.get_api_key("dev", "bybit")
api_secret = provider.get_api_secret("dev", "bybit")

print(f"✓ API Key loaded: {api_key[:3]}...***")
print(f"✓ API Secret loaded: {api_secret[:3]}...***")
EOF
```

---

## Launch Commands

### Scenario 1: Normal Shadow Run (No Freeze Expected)

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

**Expected Output**:
- JSON report to stdout
- No freeze events
- Orders placed, filled, and positions tracked
- Deterministic output (same input → same output)

### Scenario 2: Freeze Trigger Test (High Edge Threshold)

```bash
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --mode shadow \
  --no-network \
  --symbols BTCUSDT \
  --iterations 30 \
  --max-inv 10000 \
  --max-total 50000 \
  --edge-threshold 8.0 \
  --fill-rate 0.9 \
  --latency-ms 100
```

**Expected Behavior**:
- System freezes when edge drops below 8.0 bps
- All open orders are canceled
- `report["risk"]["frozen"]` = `true`
- `report["risk"]["freeze_events"]` > 0

### Scenario 3: Risk Limits Test (Low Inventory Limits)

```bash
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --mode shadow \
  --no-network \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 40 \
  --max-inv 5000 \
  --max-total 8000 \
  --edge-threshold 1.0 \
  --fill-rate 0.95 \
  --latency-ms 50
```

**Expected Behavior**:
- Many orders blocked by risk limits
- `report["orders"]["risk_blocks"]` > 10
- System does NOT freeze (unless edge drops)

### Save Output to File

```bash
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --no-network \
  --symbols BTCUSDT \
  --iterations 20 \
  > reports/shadow_run_$(date +%Y%m%d_%H%M%S).json
```

---

## Monitor & Observe

### Real-Time Logging

While shadow run is executing, monitor logs:

```bash
# In a separate terminal
tail -f logs/execution_loop.log  # If logging to file is enabled
```

Look for:
- `"event": "order_placed_scheduled_fill"` — Orders being placed
- `"event": "fill_generated"` — Fills happening
- `"event": "order_canceled"` — Cancellations (freeze or manual)
- `"event": "risk_check_blocked"` — Orders blocked by risk monitor

### Key Metrics to Watch

1. **Order Statistics**:
   - `orders.placed` — Total orders attempted
   - `orders.filled` — Successfully filled
   - `orders.risk_blocks` — Blocked by risk limits

2. **Position Tracking**:
   - `positions.by_symbol` — Current positions per symbol
   - `positions.total_notional_usd` — Total portfolio value

3. **Risk Events**:
   - `risk.frozen` — System frozen status
   - `risk.freeze_events` — Number of freeze triggers
   - `risk.last_freeze_reason` — Why system froze

### Health Checks

During execution, verify:
- No network calls are made (check firewall logs if paranoid)
- Memory usage stable (< 100MB for typical runs)
- No exceptions in stderr

---

## Observability (P0.9)

### Enable Observability Server

Start shadow run with `--obs` flag to enable HTTP endpoints:

```bash
python -m tools.live.exec_demo \
  --shadow \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 100 \
  --obs \
  --obs-port 8080
```

**Endpoints:**
- `GET /health` — Liveness check (always 200)
- `GET /ready` — Readiness check (200 if OK, 503 if frozen)
- `GET /metrics` — Prometheus metrics

### Check Health & Ready

**Liveness** (process alive):
```bash
curl http://127.0.0.1:8080/health
# {"status":"ok"}
```

**Readiness** (not frozen):
```bash
curl http://127.0.0.1:8080/ready
# {"checks":{"exchange":true,"risk":true,"state":true},"status":"ok"}
```

**If frozen** (returns 503):
```bash
curl http://127.0.0.1:8080/ready
# {"checks":{"exchange":true,"risk":false,"state":true},"status":"fail"}
```

### Query Prometheus Metrics

**Orders placed:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep mm_orders_placed_total
# mm_orders_placed_total{symbol="BTCUSDT"} 42
# mm_orders_placed_total{symbol="ETHUSDT"} 38
```

**Freeze events:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep mm_freeze_events_total
# mm_freeze_events_total 1
```

**Latency distribution:**
```bash
curl -s http://127.0.0.1:8080/metrics | grep mm_order_latency_ms_bucket
# mm_order_latency_ms_bucket{symbol="BTCUSDT",le="10"} 35
# mm_order_latency_ms_bucket{symbol="BTCUSDT",le="50"} 42
# ...
```

### Structured Logs

With observability enabled, all logs are emitted as single-line JSON to stderr:

**Example log entry:**
```json
{"component":"execution_loop","event":"order_placed","latency_ms":12,"lvl":"INFO","name":"mm.execution","price":50000,"qty":0.001,"symbol":"BTCUSDT","ts_utc":"2025-10-27T10:00:00.000000Z"}
```

**Filter logs by event:**
```bash
python -m tools.live.exec_demo --shadow --obs 2>&1 | grep -E '"event":"freeze_triggered"'
```

**Parse logs with jq:**
```bash
python -m tools.live.exec_demo --shadow --obs 2>&1 | \
  grep '^{' | \
  jq -r 'select(.event == "order_placed") | "\(.symbol): \(.qty)@\(.price)"'
```

### Alerts & Monitoring

**Key events to watch:**

| Event                 | Level    | Action                              |
|-----------------------|----------|-------------------------------------|
| `freeze_triggered`    | WARNING  | Investigate edge degradation        |
| `order_rejected`      | WARNING  | Check reason (risk? exchange?)      |
| `order_placement_error` | ERROR  | Alert on-call, check network        |
| `cancel_all_done`     | INFO     | Normal after freeze                 |

**Prometheus alerts** (example):
```promql
# Alert if frozen for > 1 min
mm_freeze_events_total > 0
AND time() - mm_orders_placed_timestamp_seconds > 60

# Alert if P99 latency > 500ms
histogram_quantile(0.99, rate(mm_order_latency_ms_bucket[5m])) > 500
```

For full observability documentation, see [OBSERVABILITY.md](OBSERVABILITY.md).

---

## Read Reports

### Report Structure

```json
{
  "execution": {
    "iterations": 50,
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "start_time_ms": 1609459200000,
    "end_time_ms": 1609459250000,
    "duration_ms": 50000
  },
  "orders": {
    "placed": 45,
    "filled": 36,
    "rejected": 0,
    "canceled": 3,
    "risk_blocks": 6
  },
  "positions": {
    "by_symbol": {
      "BTCUSDT": 0.18,
      "ETHUSDT": 1.5
    },
    "net_pos_usd": {
      "BTCUSDT": 9000.0,
      "ETHUSDT": 4500.0
    },
    "total_notional_usd": 13500.0
  },
  "risk": {
    "frozen": false,
    "freeze_events": 0,
    "last_freeze_reason": null,
    "last_freeze_symbol": null,
    "blocks_total": 6,
    "freezes_total": 0
  },
  "runtime": {
    "utc": "2025-01-01T00:00:00Z",
    "version": "P0.2"
  }
}
```

### Key Fields Explained

| Field | Meaning | Good Range | Alert If |
|-------|---------|------------|----------|
| `orders.placed` | Total orders attempted | 80-100% of iterations | < 50% (risk blocking too much) |
| `orders.filled` | Successfully filled orders | 70-90% | < 50% (low fill rate) |
| `orders.risk_blocks` | Orders blocked by risk | < 20% of placed | > 50% (limits too tight) |
| `positions.total_notional_usd` | Portfolio value | < `max_total` | ≥ `max_total` (risk breach!) |
| `risk.frozen` | System frozen? | `false` | `true` (freeze triggered) |
| `risk.freeze_events` | Number of freezes | 0 | > 0 (edge dropped) |

### Analysis Commands

```bash
# Pretty-print report
cat reports/shadow_run_20250127_103045.json | jq .

# Extract specific metric
cat reports/shadow_run_20250127_103045.json | jq '.orders.filled'

# Check if system froze
cat reports/shadow_run_20250127_103045.json | jq '.risk.frozen'

# Get freeze reason
cat reports/shadow_run_20250127_103045.json | jq '.risk.last_freeze_reason'
```

---

## Freeze Events

### What is a Freeze?

A **freeze** occurs when the system detects unfavorable market conditions (edge below threshold). When frozen:
- No new orders are placed
- All open orders are canceled
- System waits for edge to recover

### How Freeze is Triggered

In `ExecutionLoop.on_edge_update()`:

```python
if net_bps < self.risk_monitor.edge_freeze_threshold_bps:
    self.risk_monitor.freeze()
    self._cancel_all_open_orders()
```

### Freeze Indicators in Report

```json
{
  "risk": {
    "frozen": true,
    "freeze_events": 1,
    "last_freeze_reason": "Edge below threshold",
    "last_freeze_symbol": "BTCUSDT",
    "blocks_total": 10,
    "freezes_total": 1
  },
  "orders": {
    "canceled": 5  // Orders canceled due to freeze
  }
}
```

### Expected Behavior

1. **Before Freeze**:
   - Orders placed normally
   - Fills happening
   - Positions growing

2. **Freeze Triggered**:
   - `on_edge_update()` called with low edge
   - `is_frozen()` returns `true`
   - All open orders canceled via `exchange.cancel_order()`

3. **After Freeze**:
   - No new orders placed (quote processing skipped)
   - Existing fills processed
   - System remains frozen until manually reset or edge recovers

### Testing Freeze Behavior

```bash
# Set high threshold to trigger freeze
python -m tools.live.exec_demo \
  --shadow \
  --exchange bybit \
  --no-network \
  --symbols BTCUSDT \
  --iterations 20 \
  --edge-threshold 10.0 \
  > reports/freeze_test.json

# Verify freeze occurred
cat reports/freeze_test.json | jq '.risk.freeze_events'
# Expected: 1 or more

cat reports/freeze_test.json | jq '.orders.canceled'
# Expected: > 0 (orders canceled during freeze)
```

---

## Troubleshooting

### Issue: "Secret not found" Error

**Symptoms**:
```
ERROR: No value found for BYBIT_API_KEY in environment
```

**Fix**:
```bash
# Check environment variables
echo $BYBIT_API_KEY
echo $BYBIT_API_SECRET

# Set if missing
export BYBIT_API_KEY="your_key"
export BYBIT_API_SECRET="your_secret"

# Or use AWS Secrets Manager
python -m tools.live.secrets_cli save --exchange bybit --env dev ...
```

### Issue: "Network-enabled mode not implemented"

**Symptoms**:
```
NotImplementedError: Network-enabled mode not implemented in P0.2
```

**Fix**:
- This is intentional! P0.2 is dry-run only.
- Ensure `--no-network` flag is used (it's the default).
- Do NOT set `network_enabled=True` in code.

### Issue: No Orders Filling

**Symptoms**:
- `orders.filled` = 0
- `orders.placed` > 0

**Possible Causes**:
1. **Fill rate too low**:
   ```bash
   # Increase fill rate
   --fill-rate 1.0  # Always fill
   ```

2. **Latency too high**:
   ```bash
   # Reduce latency
   --latency-ms 50
   ```

3. **Clock not advancing**:
   - Check that `on_fill()` is being called
   - Verify clock is incrementing

### Issue: Too Many Risk Blocks

**Symptoms**:
- `orders.risk_blocks` > 50% of `orders.placed`
- Very few fills

**Possible Causes**:
1. **Limits too tight**:
   ```bash
   # Increase limits
   --max-inv 20000 --max-total 100000
   ```

2. **Positions accumulating too fast**:
   - Reduce fill rate
   - Lower quantity per order

3. **Edge threshold too high**:
   - System freezes before filling many orders

### Issue: Non-Deterministic Output

**Symptoms**:
- Running same command twice produces different JSON

**Fix**:
```bash
# Set deterministic timestamp
export MM_FREEZE_UTC_ISO="2025-01-01T00:00:00Z"

# Set Python hash seed
export PYTHONHASHSEED=42

# Use fixed seed in FakeExchangeClient (if applicable)
# (BybitRestClient uses deterministic hash of order ID)
```

### Issue: System Never Freezes

**Symptoms**:
- Running with high `--edge-threshold` but `risk.frozen` = `false`

**Possible Causes**:
1. **Edge not dropping below threshold**:
   - In `ExecutionLoop.run_shadow()`, edge decreases over iterations
   - May need more iterations or higher threshold

2. **`on_edge_update()` not called**:
   - Check that shadow loop calls `loop.on_edge_update()`

**Test**:
```bash
# Use very high threshold
--edge-threshold 50.0 --iterations 100
# Should definitely freeze
```

---

## Post-Run Checklist

After completing a shadow run:

- [ ] **Review JSON report** — Check key metrics
- [ ] **Verify determinism** — Run twice with same params, compare output
- [ ] **Check logs** — No unexpected errors or warnings
- [ ] **Archive reports** — Save to `reports/archive/` with timestamp
- [ ] **Update runbook** — Document any new issues or findings
- [ ] **Clean up** — Remove temporary files, clear logs if needed

### Archive Reports

```bash
# Create archive directory
mkdir -p reports/archive/$(date +%Y%m)

# Move reports
mv reports/shadow_run_*.json reports/archive/$(date +%Y%m)/

# Compress old archives (optional)
find reports/archive -type f -name "*.json" -mtime +30 -exec gzip {} \;
```

---

## Emergency Procedures

### Scenario: Suspect Real Orders Placed

**⚠️ This should NEVER happen in P0.2 (network is disabled)**

If you suspect real orders were placed:

1. **Immediate Actions**:
   ```bash
   # Check Bybit UI for open orders
   # Log in to Bybit → Trading → Orders
   # Cancel any unexpected orders manually
   ```

2. **Verify Logs**:
   ```bash
   # Search for network calls (should be NONE)
   grep -i "http" logs/execution_loop.log
   grep -i "POST\|GET" logs/execution_loop.log
   ```

3. **Check Code**:
   ```python
   # In tools/live/exchange_bybit.py
   # Verify network_enabled=False in all code paths
   ```

4. **Report Incident**:
   - Document what happened
   - Review code for bugs
   - File incident report

### Scenario: API Keys Compromised

Follow procedures in [SECRETS_OPERATIONS.md](SECRETS_OPERATIONS.md#emergency-revocation).

### Scenario: System Unresponsive

```bash
# Force kill if necessary
pkill -9 -f "exec_demo"

# Check for deadlocks or hangs
ps aux | grep python
```

---

## P0.8: Durable State & Idempotency

**Status**: P0.8 Complete — State Persistence & Recovery

### Overview

P0.8 добавляет **надёжное состояние** с использованием Redis + disk snapshots, **идемпотентность** для всех мутаций, и **recovery** после рестартов.

### Enabling Durable State

```bash
# Enable durable state persistence
python -m tools.live.exec_demo \
  --shadow \
  --durable-state \
  --state-dir artifacts/state \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 100
```

**Flags:**
- `--durable-state` — Enable Redis + disk snapshot persistence
- `--state-dir DIR` — Directory for snapshots (default: `artifacts/state`)
- `--recover` — Recover open orders from previous snapshot on startup

### State Files

**Location**: `artifacts/state/`

**Files:**
- `orders.jsonl` — Snapshot of all orders (JSONL format)
- `last_snapshot_ts.txt` — Timestamp of last snapshot

**Example snapshot:**
```jsonl
{"client_order_id":"ORD_001","symbol":"BTCUSDT","side":"BUY","state":"OPEN","qty":0.001,"price":50000.0}
{"client_order_id":"ORD_002","symbol":"ETHUSDT","side":"SELL","state":"FILLED","qty":0.01,"price":3000.0}
```

### Recovery After Restart

**Scenario**: System crashed or was stopped with open orders.

**Steps:**

1. **Check snapshot exists:**
```bash
ls -lh artifacts/state/orders.jsonl
```

2. **Restart with recovery:**
```bash
python -m tools.live.exec_demo \
  --shadow \
  --durable-state \
  --state-dir artifacts/state \
  --recover \
  --symbols BTCUSDT,ETHUSDT \
  --iterations 50
```

3. **Verify recovery in logs:**
```
[RECOVERY] {'recovered': True, 'open_orders_count': 5, ...}
```

4. **Check report for recovery section:**
```json
{
  "recovery": {
    "recovered": true,
    "open_orders_count": 5,
    "open_orders": [...]
  }
}
```

### Idempotency

Все мутации безопасны для повторных вызовов:

**Place Order:**
```python
# First call → places order
order1 = store.place_order(..., idem_key="place_001")

# Retry with same key → returns cached result, no duplicate
order2 = store.place_order(..., idem_key="place_001")
assert order1.client_order_id == order2.client_order_id
```

**Cancel All on Freeze:**
```python
# First freeze → cancels all open orders
loop._cancel_all_open_orders()

# Retry freeze → idempotent, no duplicate cancels
loop._cancel_all_open_orders()
```

### Monitoring State Health

**Check snapshot age:**
```bash
# Snapshot should be recent
stat -c %Y artifacts/state/orders.jsonl

# If older than 1 hour → investigate
```

**Verify Redis keys (if using real Redis):**
```bash
redis-cli --scan --pattern "orders:*" | head -20
redis-cli --scan --pattern "idem:*" | head -20
```

**Check idempotency cache hits:**
```python
# In logs:
# [IDEM HIT] place_order key=place_001 → cached result
```

### Freeze with Idempotency

**Scenario**: System freezes, cancel_all called multiple times.

**Behavior**:
1. First `cancel_all` → generates `freeze_idem_key`
2. Cancels all open orders
3. Caches result with `idem_key`
4. Subsequent `cancel_all` → returns cached result, no duplicate API calls

**Verification**:
```json
{
  "orders": {
    "canceled": 10,  // Total canceled (not duplicated)
    ...
  },
  "risk": {
    "frozen": true,
    "freeze_events": 1  // Single freeze event
  }
}
```

### Troubleshooting State Issues

**Problem**: Snapshot not found on recovery

**Solution**:
```bash
# Check snapshot directory
ls -la artifacts/state/

# If missing, run without --recover (fresh start)
python -m tools.live.exec_demo --shadow --durable-state ...
```

---

**Problem**: Recovery shows 0 orders but expected open orders

**Solution**:
```bash
# Verify snapshot content
cat artifacts/state/orders.jsonl | jq -c 'select(.state == "OPEN")'

# If empty → orders were filled/canceled before snapshot
```

---

**Problem**: Idempotency cache not working (duplicates detected)

**Solution**:
```bash
# Check idem_key uniqueness in logs
grep "IDEM" artifacts/latest/exec_debug.log

# Verify Redis keys (if using real Redis)
redis-cli KEYS "idem:*"

# If in-memory fake → check test logs for clock drift
```

### References

- [STATE_ARCHITECTURE.md](STATE_ARCHITECTURE.md) — State layer architecture
- [tools/state/redis_client.py](tools/state/redis_client.py) — RedisKV implementation
- [tools/live/order_store_durable.py](tools/live/order_store_durable.py) — DurableOrderStore

---

## P0.10: Testnet Soak & Canary Guardrails

**Status**: Complete — Reconciliation, Kill-Switch, Symbol Filters Cache, Fees/Rebates

This section covers critical guardrails for testnet soak testing and canary deployments before live trading.

### Overview

P0.10 adds the following production-readiness features:

1. **Reconciliation** — Periodic comparison of local state vs. exchange state (orders, positions, fills)
2. **Kill-Switch** — Dual consent mechanism to prevent accidental live trading
3. **Symbol Filters Cache** — TTL-based caching of exchange trading rules (tickSize, stepSize, minQty)
4. **Fees & Rebates Accounting** — Precise Decimal-based fee/rebate calculations

### Key CLI Flags

```bash
# P0.10 flags for exec_demo.py
--live                       # Enable live mode (requires MM_LIVE_ENABLE=1 env var)
--recon-interval-s 60        # Reconciliation interval in seconds (default: 60)
--fee-maker-bps 1.0          # Maker fee in basis points (default: 1.0)
--fee-taker-bps 7.0          # Taker fee in basis points (default: 7.0)
--rebate-maker-bps 2.0       # Maker rebate in basis points (default: 2.0)
--warmup-filters             # Warm up symbol filters cache on startup
```

### Reconciliation Triage

Reconciliation runs periodically (default: every 60s) and detects divergences between local and remote state.

#### Divergence Types & Actions

| Type | Likely Cause | Immediate Action | Prevention |
|------|--------------|------------------|------------|
| **orders_local_only** | - Order canceled on exchange without us knowing<br/>- Missed cancel response<br/>- Exchange API lag | 1. Verify order status on exchange UI<br/>2. If still open remotely → cancel via UI<br/>3. If not open remotely → update local status to CANCELED | - Robust order tracking<br/>- Use idempotency keys<br/>- Handle REST timeouts correctly |
| **orders_remote_only** | - Order placed but local record lost<br/>- Restart before recording placement | 1. **IMMEDIATELY cancel** on exchange<br/>2. Investigate why order wasn't recorded locally<br/>3. If legitimate → replay order into local state | - Durable order store (P0.8)<br/>- Snapshot before/after placement<br/>- Idempotency keys |
| **position_mismatch** | - Missed fill events<br/>- Fill processing error<br/>- WebSocket disconnect | 1. Compare local fills vs. exchange trades<br/>2. Identify missing fills<br/>3. Replay missing fills into local store | - Robust fill processing<br/>- REST polling as backup<br/>- WebSocket health checks |
| **unrecorded_fills** | - Fill processing lag<br/>- WebSocket buffer overrun<br/>- REST polling delay | 1. Check if fills eventually processed<br/>2. If persistent → restart fill processing pipeline<br/>3. If never recorded → manual replay | - Increase WebSocket buffer<br/>- Reduce REST poll interval<br/>- Monitor fill latency |

### Alert Rules (PromQL)

Paste these into Prometheus/Grafana for production monitoring:

```promql
# Critical: Orders exist on exchange but not locally (orphan orders)
mm_recon_divergence_total{type="orders_remote_only"} > 0

# Critical: Position mismatch detected
mm_recon_divergence_total{type="position_mismatch"} > 0

# Warning: Maker ratio too low (paying too many taker fees)
mm_maker_taker_ratio < 0.85

# Warning: Net PnL negative for 30m (losing money)
mm_net_bps < 0

# Info: Reconciliation divergence summary
sum(mm_recon_divergence_total) by (type)

# Info: Symbol filters cache hit rate
rate(mm_symbol_filters_source_total{source="cached"}[5m]) / 
rate(mm_symbol_filters_source_total[5m])

# Error: Symbol filters fetch failures
rate(mm_symbol_filters_fetch_errors_total[5m]) > 0
```

### Warm-Up Procedure

Before starting a long-running soak test or canary, warm up the symbol filters cache to avoid cold-start latency:

```bash
# Testnet with warm-up
python -m tools.live.exec_demo \
  --shadow \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --network \
  --testnet \
  --warmup-filters \
  --iterations 1000 \
  --recon-interval-s 300

# Expected output (stderr):
# [INFO] Warming up symbol filters cache...
# [INFO] Warmed up filters for BTCUSDT: tickSize=0.01, stepSize=0.00001, minQty=0.00001
# [INFO] Warmed up filters for ETHUSDT: tickSize=0.01, stepSize=0.0001, minQty=0.0001
# [INFO] Warmed up filters for SOLUSDT: tickSize=0.001, stepSize=0.01, minQty=0.01
# [INFO] Symbol filters cache warm-up complete

# Verify in final JSON
cat SHADOW_REPORT.json | jq '.execution.warmup_filters'
# Output: true
```

**Notes**:
- `--warmup-filters` requires `--network` (no-op in shadow mode without network)
- Filters are cached with 600s TTL (10 minutes)
- Cache invalidates automatically on errors (fallback to defaults)

### Kill-Switch Checklist (Before --live)

**NEVER** attempt live trading without completing this checklist:

- [ ] **1. Verify Testnet Success**
  - At least 24h of stable testnet soak
  - Zero critical divergences in recon
  - Maker ratio > 0.85
  - Net BPS > -5 (not losing money)
  - No freeze events due to bugs (only edge-triggered)

- [ ] **2. Review Risk Limits**
  - `--max-inv` appropriate for live capital (e.g., $1000 per symbol)
  - `--max-total` set to safe level (e.g., $5000 total)
  - `--edge-threshold` set high (e.g., 5.0 bps to avoid frequent freezes)

- [ ] **3. Secrets & Permissions**
  - Live API keys in AWS Secrets Manager (`mm-bot/live/bybit`)
  - API keys have correct permissions (read + trade, NO withdrawals)
  - IP whitelist configured on exchange
  - Keys tested with testnet first

- [ ] **4. Observability**
  - Prometheus scraping `/metrics` endpoint
  - Grafana dashboards configured
  - Alerts configured (see [Alert Rules](#alert-rules-promql))
  - PagerDuty/Slack/Email notifications tested

- [ ] **5. Kill-Switch Environment Variable**
  - **MUST** set `MM_LIVE_ENABLE=1` environment variable
  - Without this, `--live` flag will fail with `RuntimeError`
  - This is dual consent: both CLI flag AND env var required

- [ ] **6. Team Approval**
  - At least 2 team members reviewed testnet results
  - Go/No-Go decision documented
  - Incident response plan in place
  - Rollback procedure ready

### Live Launch Command

**Only after completing the checklist:**

```bash
# Set kill-switch environment variable
export MM_LIVE_ENABLE=1

# Launch with minimal position (canary)
python -m tools.live.exec_demo \
  --shadow \
  --live \
  --symbols BTCUSDT \
  --iterations 100 \
  --max-inv 500 \
  --max-total 500 \
  --edge-threshold 5.0 \
  --recon-interval-s 60 \
  --warmup-filters \
  --obs \
  --obs-port 8080

# Monitor in real-time:
# - /metrics endpoint: http://localhost:8080/metrics
# - Grafana dashboard: http://grafana/d/mm-bot-live
# - Exchange UI: https://www.bybit.com/trade/
```

### Recon Metrics Dashboard

Add these panels to Grafana:

**Panel 1: Divergence Count**
```promql
sum(mm_recon_divergence_total) by (type)
```

**Panel 2: Maker/Taker Ratio**
```promql
mm_maker_taker_ratio
```

**Panel 3: Net PnL (BPS)**
```promql
mm_net_bps
```

**Panel 4: Live Enable Status**
```promql
mm_live_enable
```

**Panel 5: Symbol Filters Cache Efficiency**
```promql
rate(mm_symbol_filters_source_total{source="cached"}[5m]) / 
rate(mm_symbol_filters_source_total[5m]) * 100
```

### Troubleshooting P0.10

#### Problem: `RuntimeError: Attempted to enable live mode without dual consent`

**Cause**: Tried to use `--live` without setting `MM_LIVE_ENABLE=1` environment variable.

**Solution**:
```bash
export MM_LIVE_ENABLE=1
python -m tools.live.exec_demo --shadow --live ...
```

---

#### Problem: Reconciliation shows divergence_count > 0 immediately after start

**Cause**: Previous run left orphan orders on exchange, or testnet has residual state.

**Solution**:
```bash
# 1. Check exchange UI for open orders
# 2. Cancel all orders manually
# 3. Verify clean state:
python -m tools.live.exec_demo --shadow --network --testnet --symbols BTCUSDT --iterations 1

# 4. Check recon in final JSON:
cat SHADOW_REPORT.json | jq '.recon.divergence_count'
# Expected: 0
```

---

#### Problem: `mm_maker_taker_ratio < 0.5` (too many taker fills)

**Cause**: Aggressive pricing, fast market, or incorrect `--post-only-offset-bps`.

**Solution**:
```bash
# Increase post-only offset
python -m tools.live.exec_demo \
  --shadow \
  --maker-only \
  --post-only-offset-bps 2.5 \
  ...

# Check if ratio improves
```

---

#### Problem: Warm-up fails with "Failed to warm up filters for BTCUSDT"

**Cause**: Network issue, exchange API down, or wrong `--api-env`.

**Solution**:
```bash
# Test API connectivity
curl https://api.bybit.com/v5/market/instruments-info?category=linear&symbol=BTCUSDT

# Check logs for detailed error
python -m tools.live.exec_demo --shadow --network --testnet --warmup-filters --symbols BTCUSDT 2>&1 | grep WARN

# If persistent → disable warm-up, cache will populate lazily
```

### References

- [RECON_OPERATIONS.md](RECON_OPERATIONS.md) — Detailed reconciliation operations guide
- [tools/live/recon.py](tools/live/recon.py) — Reconciliation logic
- [tools/live/kill_switch.py](tools/live/kill_switch.py) — Kill-switch implementation
- [tools/live/symbol_filters.py](tools/live/symbol_filters.py) — Symbol filters cache
- [tools/live/fees.py](tools/live/fees.py) — Fee/rebate calculations

---

## P0.11: Testnet Smoke Pack

**Status**: Complete — Prometheus Alerts, Grafana Dashboard, VIP Fees, Auto-Warmup, CI Smoke

This section covers observability, monitoring, and smoke testing enhancements for testnet and canary live deployments.

### Overview

P0.11 adds production-readiness tooling:

1. **Prometheus Alerts** — 5 critical alert rules for operational monitoring
2. **Grafana Dashboard** — Comprehensive visual monitoring (10 panels)
3. **Auto-Warmup** — Symbol filters cache automatically warmed up for testnet/live
4. **VIP Fee Profiles** — Per-symbol fee/rebate schedules for different trading tiers
5. **CI Smoke Workflow** — Automated testnet connectivity dry-run in GitHub Actions

### Prometheus Alert Rules

Located in `obs/prometheus/alerts_mm_bot.yml`, includes:

| Alert Name | Condition | Severity | Description |
|------------|-----------|----------|-------------|
| `MMBotReconDivergence` | `increase(mm_recon_divergence_total[10m]) > 0` | Critical | Reconciliation divergence detected (orders/positions mismatch) |
| `MMBotMakerTakerLow` | `mm_maker_taker_ratio < 0.85` for 30m | Warning | Maker/taker ratio too low (excessive taker fees) |
| `MMBotNetBpsNegative` | `mm_net_bps < 0` for 30m | Warning | Net PnL negative for extended period (losing money) |
| `MMBotFiltersFallback` | `increase(mm_symbol_filters_fetch_errors_total[15m]) > 0` OR `rate(mm_symbol_filters_source_total{source="default_fallback"}[15m]) > 0` | Warning | Symbol filters falling back to defaults (exchange API issues) |
| `MMBotLiveEnableArmed` | `mm_live_enable == 1` AND `up == 0` for 1m | Critical | Live mode armed but bot process down (safety check) |

#### Import Alerts into Prometheus

```bash
# 1. Copy alerts file to Prometheus config directory
cp obs/prometheus/alerts_mm_bot.yml /etc/prometheus/rules/

# 2. Update prometheus.yml to include rule file
# Add to prometheus.yml:
#   rule_files:
#     - /etc/prometheus/rules/alerts_mm_bot.yml

# 3. Reload Prometheus
curl -X POST http://localhost:9090/-/reload
# OR restart Prometheus service
```

#### Verify Alerts Loaded

```bash
# Check Prometheus UI: http://localhost:9090/alerts
# Should see 5 MM-Bot alerts (green = OK, red = firing)

# Or via API:
curl http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name == "mm_bot_critical")'
```

### Grafana Dashboard

Located in `obs/grafana/MMBot_Dashboard.json`, includes 10 panels:

1. **Reconciliation Divergences (by type)** — Critical operational metric
2. **Maker/Taker Ratio** — Fee efficiency (target: ≥ 85%)
3. **Net PnL (BPS)** — Strategy profitability
4. **Orders Blocked (by reason)** — Execution quality
5. **Symbol Filters Source (stacked)** — API health (cached vs fetched)
6. **Freeze Events** — Safety mechanism activation
7. **Kill-Switch Status (Live Enable)** — Safety override
8. **Exchange Latency (histogram)** — Performance monitoring
9. **Symbol Filters Fetch Errors** — API reliability
10. **Cache Hit Rate** — Efficiency metric

#### Import Dashboard into Grafana

1. Open Grafana UI: `http://your-grafana:3000`
2. Navigate to **Dashboards → Import**
3. Upload `obs/grafana/MMBot_Dashboard.json`
4. Select Prometheus data source
5. Click "Import"

See `obs/grafana/README.md` for detailed import instructions and panel descriptions.

### Auto-Warmup Default Behavior

**New in P0.11**: Symbol filters cache is automatically warmed up on startup when:
- `--network` flag is used
- AND `EXCHANGE_ENV ∈ {testnet, live}`

This reduces cold-start latency and ensures consistent behavior.

#### CLI Flags

```bash
# Auto-warmup enabled (default for testnet/live)
python -m tools.live.exec_demo --shadow --network --testnet --symbols BTCUSDT

# Explicitly enable warmup (shadow mode)
python -m tools.live.exec_demo --shadow --warmup-filters --symbols BTCUSDT

# Explicitly disable auto-warmup
python -m tools.live.exec_demo --shadow --network --testnet --no-warmup-filters --symbols BTCUSDT
```

#### Verify Warmup

Check stderr logs:
```
[INFO] Auto-enabling --warmup-filters for testnet/live network mode
[INFO] Warming up symbol filters cache...
[INFO] Warmed up filters for BTCUSDT: tickSize=0.01, stepSize=0.00001, minQty=0.00001
[INFO] Symbol filters cache warm-up complete
```

Check final JSON report:
```bash
cat SHADOW_REPORT.json | jq '.execution.warmup_filters'
# Output: true
```

### VIP Fee Profiles

**New in P0.11**: Per-symbol fee/rebate schedules for different trading tiers.

Located in `tools/live/fees_profiles.py`, includes pre-defined profiles:
- `VIP0_PROFILE` — maker=1.0bps, taker=7.0bps, rebate=0.0bps
- `VIP1_PROFILE` — maker=0.8bps, taker=6.5bps, rebate=1.0bps
- `VIP2_PROFILE` — maker=0.5bps, taker=5.0bps, rebate=2.5bps
- `VIP3_PROFILE` — maker=0.2bps, taker=4.0bps, rebate=3.0bps
- `MM_TIER_A_PROFILE` — maker=0.0bps, taker=3.0bps, rebate=5.0bps (strong MM rebate)

#### Usage Example (Python API)

```python
from tools.live.fees import FeeSchedule, Fill, calc_fees_and_rebates
from tools.live.fees_profiles import build_profile_map

# Default schedule (fallback)
default_schedule = FeeSchedule(
    maker_bps=Decimal("1.0"),
    taker_bps=Decimal("7.0"),
    maker_rebate_bps=Decimal("2.0"),
)

# Build VIP2 profile map (applies to all symbols via wildcard)
profile_map = build_profile_map("VIP2")

# Calculate fees with VIP2 profile
fills = [...]  # List of Fill objects
fees_report = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
```

#### Per-Symbol Profiles

```python
from tools.live.fees_profiles import FeeProfile, VIP2_PROFILE, VIP0_PROFILE

# Custom per-symbol profiles
profile_map = {
    "BTCUSDT": VIP2_PROFILE,  # BTC gets VIP2 rates
    "ETHUSDT": VIP0_PROFILE,  # ETH gets VIP0 rates
    "*": VIP1_PROFILE,        # All other symbols get VIP1 rates
}

# Profiles override default schedule per-symbol
fees_report = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
```

#### Future CLI Integration

*Note: CLI exposure coming in P0.12. For now, profiles are Python API only.*

### CI Smoke Workflow

Located in `.github/workflows/testnet-smoke.yml`, manual dispatch workflow.

**Purpose**: Quick connectivity dry-run to validate testnet readiness (NO real credentials).

#### Trigger Workflow

1. Navigate to GitHub Actions: `https://github.com/your-org/mm-bot/actions`
2. Select **"Testnet Smoke Tests"** workflow
3. Click **"Run workflow"**
4. Configure inputs:
   - Symbols: `BTCUSDT` (default)
   - Iterations: `50` (default)
   - Recon Interval: `60` (default)
5. Click **"Run workflow"**

#### Workflow Steps

1. **Shadow Dry-Run Tests** — Fast unit + integration tests
2. **Testnet Simulation** — Run `exec_demo.py` with testnet flags (dry-run)
3. **Validation** — Check JSON output, logs, metrics snapshot
4. **Artifacts** — Collect `TESTNET_SMOKE_REPORT.json`, `TESTNET_SMOKE_LOGS.txt`, `METRICS_SNAPSHOT.txt`

#### Review Artifacts

After workflow completes (green ✅):

1. Download artifacts from workflow summary page
2. Verify `TESTNET_SMOKE_REPORT.json`:
   ```bash
   cat TESTNET_SMOKE_REPORT.json | jq '.recon.divergence_count'
   # Expected: 0
   ```
3. Check for warnings in `TESTNET_SMOKE_LOGS.txt`:
   ```bash
   grep -i "warn\|error" TESTNET_SMOKE_LOGS.txt
   ```

### Testnet Smoke Checklist (3–5 Days)

Before promoting to canary live, complete this checklist:

#### Day 1: Initial Smoke
- [ ] **Trigger CI smoke workflow** — Should pass in < 15 minutes
- [ ] **Review artifacts** — No critical errors, divergence_count=0
- [ ] **Deploy to testnet** — Use real testnet credentials (read-only first)
- [ ] **Run 1h soak** — `--iterations 100 --recon-interval-s 60`
- [ ] **Verify Grafana panels** — All metrics populated correctly
- [ ] **Check Prometheus alerts** — No alerts firing (or only expected ones)

#### Day 2–3: Extended Soak
- [ ] **24h continuous run** — No crashes, no memory leaks
- [ ] **Recon divergences** — Should be 0 (or documented/explained if non-zero)
- [ ] **Maker/taker ratio** — Should be ≥ 0.85
- [ ] **Net PnL (BPS)** — Should be positive or near-zero (not losing money)
- [ ] **Freeze events** — Only edge-driven freezes (no bugs)
- [ ] **Cache hit rate** — ≥ 80% (symbol filters cached effectively)

#### Day 4–5: Pre-Live Validation
- [ ] **Kill-switch drill** — Set `MM_LIVE_ENABLE=1` (shadow mode), verify metrics show live=1, then unset
- [ ] **Warmup validation** — Verify auto-warmup logs present, `warmup_filters: true` in JSON
- [ ] **VIP fee profiles** — Test per-symbol profiles (if using custom tiers)
- [ ] **Alert testing** — Temporarily lower thresholds to trigger alerts, verify notifications
- [ ] **Dashboard review** — All 10 panels displaying correctly

#### Go/No-Go Decision

**Go Criteria**:
- ✅ All smoke tests green (CI + testnet)
- ✅ 24h soak stable (no crashes, no divergences)
- ✅ Maker/taker ratio ≥ 0.85
- ✅ Net PnL ≥ 0 (not losing money)
- ✅ Alerts configured and tested
- ✅ Dashboard reviewed by 2+ team members

**No-Go Criteria** (any ONE of these → NO GO):
- ❌ Any critical alert fired (recon divergence, live enable armed)
- ❌ Frequent freezes due to bugs (not edge-driven)
- ❌ Memory leaks or crashes during soak
- ❌ Maker/taker ratio < 0.80 (paying too much in taker fees)
- ❌ Net PnL < -10 BPS (losing money)

If **NO-GO**: Document issues, fix root cause, restart smoke checklist from Day 1.

### Severity Matrix

| Alert / Metric | Severity | Response Time | Action |
|----------------|----------|---------------|--------|
| `MMBotReconDivergence` (type=orders_remote_only) | **P0 Critical** | Immediate (< 5min) | **STOP trading**, cancel orphan orders, investigate |
| `MMBotLiveEnableArmed` (live=1, up=0) | **P0 Critical** | Immediate (< 5min) | Check for orphan orders, review crash logs |
| `MMBotReconDivergence` (type=orders_local_only) | **P1 High** | < 15min | Verify exchange status, update local state |
| `MMBotReconDivergence` (type=position_mismatch) | **P1 High** | < 15min | Compare fills, replay missing fills |
| `MMBotMakerTakerLow` | **P2 Medium** | < 1h | Review --post-only-offset-bps, adjust pricing |
| `MMBotNetBpsNegative` | **P2 Medium** | < 1h | Review execution quality, consider pause |
| `MMBotFiltersFallback` | **P3 Low** | < 4h | Check exchange API status, verify connectivity |

### References

- [obs/prometheus/alerts_mm_bot.yml](obs/prometheus/alerts_mm_bot.yml) — Alert rules
- [obs/grafana/MMBot_Dashboard.json](obs/grafana/MMBot_Dashboard.json) — Grafana dashboard
- [obs/grafana/README.md](obs/grafana/README.md) — Dashboard import guide
- [tools/live/fees_profiles.py](tools/live/fees_profiles.py) — VIP fee profiles
- [tools/live/fees.py](tools/live/fees.py) — Fee/rebate calculations (extended for profiles)
- [.github/workflows/testnet-smoke.yml](.github/workflows/testnet-smoke.yml) — CI smoke workflow
- [RECON_OPERATIONS.md](RECON_OPERATIONS.md) — Reconciliation operations guide
- [README_EXECUTION.md](README_EXECUTION.md) — Execution engine overview

---

## References

- [README_EXECUTION.md](README_EXECUTION.md) — Execution engine architecture
- [SECRETS_OPERATIONS.md](SECRETS_OPERATIONS.md) — Credential management
- [P0.2 Implementation Summary](P0_2_IMPLEMENTATION_SUMMARY.md) — Technical details
- [STATE_ARCHITECTURE.md](STATE_ARCHITECTURE.md) — State & Concurrency (P0.8)
- [Bybit API Docs](https://bybit-exchange.github.io/docs/v5/intro)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-10-27 | Initial version for P0.2 completion |
| 1.1 | 2025-10-27 | Added P0.8 durable state & idempotency section |
| 1.2 | 2025-10-27 | Added P0.10 testnet soak & canary guardrails (recon, kill-switch, filters, fees) |
| 1.3 | 2025-10-27 | Added P0.11 testnet smoke pack (alerts, dashboard, VIP fees, auto-warmup, CI smoke) |

---

## Contact & Support

For questions or issues:
1. Check [Troubleshooting](#troubleshooting) section
2. Review test failures in CI/CD
3. Consult team documentation
4. Escalate to senior engineer if production-critical

**Last Reviewed**: 2025-10-27  
**Next Review**: 2026-01-27

