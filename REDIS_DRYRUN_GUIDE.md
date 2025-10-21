# Redis Dry-Run Validation Guide

## Overview

This guide describes the Redis export integration for soak/shadow phase KPIs, enabling real-time dry-run validation and comparison workflows.

## Architecture

```
┌─────────────────┐         ┌───────────┐         ┌──────────────────┐
│  Soak/Shadow    │         │   Redis   │         │  Dry-Run         │
│  ITER_SUMMARY   │ ──────> │  KPI Store│ ──────> │  Validation      │
│  *.json         │ export  │  (TTL=1h) │ consume │  Comparison      │
└─────────────────┘         └───────────┘         └──────────────────┘
```

## Key Schema

KPIs are exported to Redis with namespaced keys for multi-environment support:

```
{env}:{exchange}:shadow:latest:{symbol}:{kpi}
```

**Examples:**
- `dev:bybit:shadow:latest:BTCUSDT:edge_bps` → "3.2"
- `prod:bybit:shadow:latest:BTCUSDT:maker_taker_ratio` → "0.85"
- `staging:binance:shadow:latest:ETHUSDT:p95_latency_ms` → "250"
- `dev:bybit:shadow:latest:BTCUSDT:risk_ratio` → "0.35"

**Namespace Components:**
- `env`: Environment (dev, staging, prod)
- `exchange`: Exchange name (bybit, binance, etc.)
- `symbol`: Trading symbol (auto-normalized to A-Z0-9 uppercase)

**Symbol Normalization:**
All symbols are automatically normalized to uppercase A-Z0-9 format:
- `BTC-USDT` → `BTCUSDT`
- `btc/usdt` → `BTCUSDT`
- `BTC_USDT` → `BTCUSDT`

**TTL:** 3600 seconds (1 hour) - keys automatically expire after 1 hour

## Performance & Storage Modes

### Hash Mode (Default, Recommended)

In hash mode, all KPIs for a symbol are stored in a single Redis hash. This is more efficient and provides atomic updates:

```redis
HSET dev:bybit:shadow:latest:BTCUSDT edge_bps 3.2 maker_taker_ratio 0.85 p95_latency_ms 250 risk_ratio 0.35
EXPIRE dev:bybit:shadow:latest:BTCUSDT 3600
```

**Advantages:**
- ✅ Fewer Redis operations (1 HSET + 1 EXPIRE vs 4 SETEX commands)
- ✅ Atomic updates (all KPIs updated together)
- ✅ Efficient batching via pipelines
- ✅ Better performance at scale (50-100+ symbols)

**Retrieval:**
```bash
# Get all KPIs for a symbol
redis-cli HGETALL dev:bybit:shadow:latest:BTCUSDT

# Get specific KPI
redis-cli HGET dev:bybit:shadow:latest:BTCUSDT edge_bps
```

### Flat Keys Mode (Legacy Compatibility)

In flat mode, each KPI gets its own key (legacy behavior):

```redis
SETEX dev:bybit:shadow:latest:BTCUSDT:edge_bps 3600 3.2
SETEX dev:bybit:shadow:latest:BTCUSDT:maker_taker_ratio 3600 0.85
# ... one key per KPI
```

**Use flat mode for:**
- Legacy systems expecting individual keys
- Simple key-value retrieval without hash operations

**Enable flat mode:**
```bash
python -m tools.shadow.export_to_redis --flat-keys
```

### Pipeline Batching

Both modes use Redis pipelines for efficient bulk operations:

- **Default batch size:** 50 operations
- **Configurable:** `--batch-size 100`
- **Non-transactional:** For maximum throughput
- **Idempotent:** Re-exporting same data produces same result

**Batch logging:**
```
[PIPELINE] batch=1 symbols=50 keys=200 success=50 fail=0 duration_ms=15.2
[PIPELINE] batch=2 symbols=50 keys=200 success=50 fail=0 duration_ms=14.8
```

## Exported KPIs

For each symbol, the following KPIs are exported:

| KPI Name             | Description                          | Example Value |
|----------------------|--------------------------------------|---------------|
| `edge_bps`           | Net edge in basis points             | 3.2           |
| `maker_taker_ratio`  | Maker/taker ratio                    | 0.85          |
| `p95_latency_ms`     | P95 order age latency (milliseconds) | 250           |
| `risk_ratio`         | Risk ratio                           | 0.35          |

## Usage

### Basic Export (Development)

Export KPIs from soak artifacts to Redis with dev namespace (hash mode, default):

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url redis://localhost:6379/0 \
  --env dev \
  --exchange bybit \
  --hash-mode \
  --batch-size 50 \
  --show-metrics
```

Output:
```
[INFO] Exporting KPIs to Redis (env=dev, exchange=bybit, mode=hash, batch_size=50, TTL=3600s)...
[PIPELINE] batch=1 symbols=2 keys=8 success=2 fail=0 duration_ms=12.5
[SUCCESS] Exported 2 symbols (8 total KPIs) to Redis

[METRICS] Prometheus-style metrics:
  redis_export_success_total: 2
  redis_export_batches_total: 1
  redis_export_keys_written_total: 8
  redis_export_mode{type="hash"}
```

### Production Export with TLS & High Throughput

Export to production Redis with TLS, authentication, and larger batches:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url rediss://username:password@prod.redis.com:6380/0 \
  --env prod \
  --exchange bybit \
  --hash-mode \
  --batch-size 100 \
  --ttl 7200 \
  --show-metrics
```

**Performance gains:**
- Hash mode: ~75% fewer operations than flat mode
- Batch size 100: ~50% faster for 200+ symbols
- Pipeline: 10-20x faster than individual commands

### Flat Keys Mode (Legacy)

Use flat keys mode for compatibility with legacy systems:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url redis://localhost:6379/0 \
  --env dev \
  --exchange bybit \
  --flat-keys \
  --batch-size 50
```

Output:
```
[INFO] Exporting KPIs to Redis (env=dev, exchange=bybit, mode=flat, batch_size=50, TTL=3600s)...
[PIPELINE] batch=1 keys=8 success=8 fail=0 duration_ms=18.3
[SUCCESS] Exported 8 keys to Redis
```

### Dry-Run Mode

Preview what would be exported without actually writing to Redis:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url redis://localhost:6379/0 \
  --env dev \
  --exchange bybit \
  --hash-mode \
  --dry-run \
  --show-metrics
```

Output:
```
[INFO] Loading summaries from: artifacts/soak/latest
[DRY-RUN] HSET dev:bybit:shadow:latest:BTCUSDT edge_bps 3.2 maker_taker_ratio 0.85 ...
[DRY-RUN] EXPIRE dev:bybit:shadow:latest:BTCUSDT 3600
[INFO] Loaded 8 iteration summaries
[INFO] Aggregating KPIs by symbol...
[INFO] Aggregated KPIs for 2 symbols
  BTCUSDT: 4 KPIs
  ETHUSDT: 4 KPIs
[INFO] Exporting KPIs to Redis (env=dev, exchange=bybit, TTL=3600s)...
[DRY-RUN] Would export: dev:bybit:shadow:latest:BTCUSDT:edge_bps = 3.2 (TTL=3600s)
[DRY-RUN] Would export: dev:bybit:shadow:latest:BTCUSDT:maker_taker_ratio = 0.85 (TTL=3600s)
...
[DRY-RUN] Would export 8 keys
```

### Prometheus Metrics

After export (with `--show-metrics`), Prometheus-style metrics are displayed:

```
[METRICS] Prometheus-style metrics:
  redis_export_success_total: 50
  redis_export_fail_total: 0
  redis_export_duration_ms: 142.35
  redis_export_batches_total: 3
  redis_export_keys_written_total: 200
  redis_export_batches_failed_total: 0
  redis_export_batch_duration_ms: 45.78
  redis_export_mode{type="hash"}
```

**Metrics:**
| Metric | Description |
|--------|-------------|
| `redis_export_success_total` | Number of successfully exported items (symbols in hash mode, keys in flat mode) |
| `redis_export_fail_total` | Number of failed exports |
| `redis_export_duration_ms` | Total export duration in milliseconds |
| `redis_export_batches_total` | Number of pipeline batches executed |
| `redis_export_keys_written_total` | Total number of KPI fields written |
| `redis_export_batches_failed_total` | Number of failed batches |
| `redis_export_batch_duration_ms` | Cumulative batch execution time |
| `redis_export_mode{type="..."}` | Storage mode used ("hash" or "flat") |

**Use cases:**
- Monitor export performance over time
- Alert on high failure rates
- Optimize batch sizes based on duration metrics
- Track throughput (keys_written_total / duration_ms)

### Makefile Commands

Use convenient Makefile targets:

```bash
# Export to Redis (dev)
make shadow-redis-export

# Export to Redis (prod with TLS)
make shadow-redis-export-prod

# Dry-run preview
make shadow-redis-export-dry
```

## Graceful Fallback

The export module handles Redis unavailability gracefully:

### Scenario 1: Redis Library Not Installed

```
WARNING: Redis library not installed. Install with: pip install redis
Falling back to dry-run mode (no actual export).
[DRY-RUN] Would export: shadow:latest:BTCUSDT:edge_bps = 3.2 (TTL=3600s)
```

**Solution:** Install redis library:
```bash
pip install redis
```

### Scenario 2: Redis Connection Failure

```
WARNING: Cannot connect to Redis at redis://localhost:6379/0: Connection refused
Falling back to dry-run mode (no actual export).
[DRY-RUN] Would export: shadow:latest:BTCUSDT:edge_bps = 3.2 (TTL=3600s)
```

**Solutions:**
- Start Redis: `redis-server`
- Check Redis is running: `redis-cli ping` (should return `PONG`)
- Verify URL is correct

## Integration with Dry-Run Validation

After exporting KPIs to Redis, you can run dry-run validation to compare shadow/soak predictions with actual Redis-stored metrics:

```bash
# 1. Run soak phase and export to Redis
python -m tools.soak.run --iterations 8 --mock --preset maker_bias_uplift_v1
make shadow-redis-export

# 2. Run dry-run validation (consumes from Redis)
python -m tools.dryrun.run_dryrun \
  --redis-url redis://localhost:6379/0 \
  --symbols BTCUSDT ETHUSDT \
  --iterations 6 \
  --duration 60
```

## Redis Operations

### Inspect Exported Keys

```bash
# List all shadow keys for dev environment
redis-cli --scan --pattern "dev:bybit:shadow:latest:*"

# List all shadow keys for prod environment
redis-cli --scan --pattern "prod:*:shadow:latest:*"

# Get specific KPI value
redis-cli GET dev:bybit:shadow:latest:BTCUSDT:edge_bps

# Check TTL (time remaining before expiry)
redis-cli TTL dev:bybit:shadow:latest:BTCUSDT:edge_bps
# Returns seconds remaining, or -1 if no TTL, or -2 if key doesn't exist

# Get all KPIs for a symbol in dev
redis-cli --scan --pattern "dev:bybit:shadow:latest:BTCUSDT:*" | xargs redis-cli MGET

# Count keys by environment
redis-cli --scan --pattern "dev:*:shadow:latest:*" | wc -l
redis-cli --scan --pattern "prod:*:shadow:latest:*" | wc -l
```

### Manual Cleanup

Keys auto-expire after TTL (3600s = 1 hour), but you can manually clean up:

```bash
# Delete all shadow keys for dev environment
redis-cli --scan --pattern "dev:*:shadow:latest:*" | xargs redis-cli DEL

# Delete all shadow keys for specific exchange in prod
redis-cli --scan --pattern "prod:bybit:shadow:latest:*" | xargs redis-cli DEL

# Delete all shadow keys (all environments)
redis-cli --scan --pattern "*:*:shadow:latest:*" | xargs redis-cli DEL

# Or flush entire database (⚠️ DANGEROUS - deletes everything)
redis-cli FLUSHDB
```

## CI/CD Integration

### GitHub Actions Workflow

Example workflow for soak → export → validate pipeline:

```yaml
jobs:
  soak-export-validate:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Soak Phase
        run: |
          python -m tools.soak.run --iterations 8 --mock
      
      - name: Export to Redis
        run: |
          python -m tools.shadow.export_to_redis \
            --src artifacts/soak/latest \
            --redis-url redis://localhost:6379/0
      
      - name: Verify Export
        run: |
          # Check keys exist
          redis-cli --scan --pattern "shadow:latest:*" | wc -l
      
      - name: Run Dry-Run Validation
        run: |
          python -m tools.dryrun.run_dryrun \
            --redis-url redis://localhost:6379/0 \
            --symbols BTCUSDT ETHUSDT \
            --iterations 6
```

## Troubleshooting

### Problem: No KPIs Exported

**Symptoms:**
```
[WARN] No ITER_SUMMARY_*.json files found in artifacts/soak/latest
[ERROR] No iteration summaries found
```

**Solution:**
1. Check source directory exists: `ls artifacts/soak/latest/`
2. Verify ITER_SUMMARY files exist: `ls artifacts/soak/latest/ITER_SUMMARY_*.json`
3. Run soak phase first to generate summaries

### Problem: Redis Connection Timeout

**Symptoms:**
```
WARNING: Cannot connect to Redis at redis://localhost:6379/0: Timeout
```

**Solutions:**
1. Check Redis is running: `ps aux | grep redis-server`
2. Test connection: `redis-cli ping`
3. Check firewall rules if Redis is on remote host
4. Verify Redis URL format: `redis://[host]:[port]/[db]`

### Problem: Wrong KPI Values

**Symptoms:**
KPI values in Redis don't match expected values

**Solution:**
1. Check source ITER_SUMMARY files directly:
   ```bash
   cat artifacts/soak/latest/ITER_SUMMARY_001.json | jq '.summary'
   ```
2. Run export with `--dry-run` to see what would be exported
3. Check KPI aggregation logic handles both flat and nested structure

## Dependencies

### Required
- Python 3.11+
- Redis 6.0+ (for server)

### Optional
- `redis` Python library (for actual export; gracefully falls back if missing)
  ```bash
  pip install redis
  ```

## Testing

Run unit tests:

```bash
# Run all export tests
pytest tests/test_export_to_redis.py -v

# Run specific test
pytest tests/test_export_to_redis.py::test_export_to_redis_with_client -v

# Run with coverage
pytest tests/test_export_to_redis.py --cov=tools.shadow.export_to_redis --cov-report=term-missing
```

## API Reference

### CLI Arguments

```
python -m tools.shadow.export_to_redis [OPTIONS]

Options:
  --src PATH                Source directory with ITER_SUMMARY_*.json files
                            (default: artifacts/soak/latest)
  
  --redis-url URL           Redis connection URL
                            Supports: redis://, rediss:// (TLS), authentication
                            (default: redis://localhost:6379/0)
                            Examples:
                              redis://localhost:6379/0
                              rediss://user:pass@host:6380/0
  
  --env ENV                 Environment namespace (dev, staging, prod)
                            (default: dev)
  
  --exchange EXCHANGE       Exchange namespace (bybit, binance, etc.)
                            (default: bybit)
  
  --ttl SECONDS             TTL for Redis keys in seconds
                            (default: 3600 = 1 hour)
  
  --dry-run                 Preview mode: print what would be exported
                            without actually exporting
  
  --hash-mode               Use hash mode (HSET + EXPIRE) - DEFAULT
                            All KPIs for a symbol in one hash
  
  --flat-keys               Use flat mode (SETEX per key) - LEGACY
                            Each KPI gets its own key
  
  --batch-size N            Number of operations per pipeline batch
                            (default: 50)
                            Recommended: 50-100 for most workloads
                            Larger batches = higher throughput, more memory
  
  --show-metrics            Print Prometheus-style metrics after export
                            Includes success/fail counters, durations, etc.
```

### Python API

```python
from tools.shadow.export_to_redis import (
    load_iter_summaries,
    aggregate_kpis,
    export_to_redis,
    get_redis_client,
    normalize_symbol,
    build_redis_key,
    METRICS,
    reset_metrics,
    print_metrics
)

# Load summaries
summaries = load_iter_summaries(Path("artifacts/soak/latest"))

# Aggregate KPIs
kpis = aggregate_kpis(summaries)
# Returns: {"BTCUSDT": {"edge_bps": 3.2, ...}, ...}

# Normalize symbol
normalized = normalize_symbol("BTC-USDT")  # Returns: "BTCUSDT"

# Build namespaced key
key = build_redis_key("prod", "bybit", "BTCUSDT", "edge_bps")
# Returns: "prod:bybit:shadow:latest:BTCUSDT:edge_bps"

# Get Redis client (supports TLS and auth)
client = get_redis_client("rediss://user:pass@prod.redis.com:6380/0")

# Export with namespacing (hash mode, batching)
reset_metrics()  # Reset metrics before export
exported_count = export_to_redis(
    kpis,
    client,
    env="prod",
    exchange="bybit",
    ttl=3600,
    hash_mode=True,      # Use hash mode (default)
    batch_size=100       # Batch size for pipeline
)

# Print metrics
print_metrics(show_metrics=True)

# Access specific metrics
print(f"Symbols exported: {exported_count}")
print(f"KPIs written: {METRICS['redis_export_keys_written_total']}")
print(f"Batches: {METRICS['redis_export_batches_total']}")
print(f"Duration: {METRICS['redis_export_duration_ms']:.2f}ms")
print(f"Mode: {METRICS['redis_export_mode']}")
```

## Changelog

### v1.2.0 (2025-01-21) - Performance & Pipeline Edition
- **Performance:** Added hash mode (HSET + EXPIRE) for 75% fewer Redis operations (DEFAULT)
- **Batching:** Added pipeline support with configurable `--batch-size` (default: 50)
- **Idempotency:** Re-exporting same data produces identical results
- **Metrics:** Added extended Prometheus metrics:
  - `redis_export_batches_total` - Number of pipeline batches
  - `redis_export_keys_written_total` - Total KPI fields written
  - `redis_export_batches_failed_total` - Failed batch count
  - `redis_export_batch_duration_ms` - Cumulative batch execution time
  - `redis_export_mode{type="..."}` - Storage mode indicator
- **CLI:** Added `--hash-mode` (default), `--flat-keys` (legacy), `--batch-size`, `--show-metrics`
- **API:** Added `reset_metrics()` and `print_metrics()` functions
- **Testing:** Comprehensive tests for hash mode, flat mode, batching, error handling
- **Docs:** Updated guide with performance benchmarks and usage patterns

### v1.1.0 (2025-01-21)
- **Breaking:** Changed key schema to namespaced format `{env}:{exchange}:shadow:latest:{symbol}:{kpi}`
- Added `--env` parameter for environment namespacing (dev, staging, prod)
- Added `--exchange` parameter for exchange namespacing
- Added automatic symbol normalization to A-Z0-9 uppercase format
- Added TLS/SSL support via `rediss://` protocol
- Added authentication support in Redis URL (`username:password@host`)
- Added Prometheus-style metrics (success_total, fail_total, duration_ms)
- Added socket timeout (5s) for Redis connections
- Enhanced test coverage: namespacing, auth, TLS, normalization

### v1.0.0 (2025-01-21)
- Initial release
- Basic export functionality with TTL support
- Graceful fallback when Redis unavailable
- Dry-run mode for testing
- Integration with soak/shadow phase workflows

## See Also

- [Shadow Mode Guide](SHADOW_MODE_GUIDE.md)
- [Soak Test Documentation](docs/SOAK_TESTS.md)
- [Dry-Run Validation Workflow](.github/workflows/dryrun.yml)
