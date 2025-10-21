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

KPIs are exported to Redis with the following key structure:

```
shadow:latest:{symbol}:{kpi}
```

**Examples:**
- `shadow:latest:BTCUSDT:edge_bps` → "3.2"
- `shadow:latest:BTCUSDT:maker_taker_ratio` → "0.85"
- `shadow:latest:BTCUSDT:p95_latency_ms` → "250"
- `shadow:latest:BTCUSDT:risk_ratio` → "0.35"
- `shadow:latest:ETHUSDT:edge_bps` → "2.9"

**TTL:** 3600 seconds (1 hour) - keys automatically expire after 1 hour

## Exported KPIs

For each symbol, the following KPIs are exported:

| KPI Name             | Description                          | Example Value |
|----------------------|--------------------------------------|---------------|
| `edge_bps`           | Net edge in basis points             | 3.2           |
| `maker_taker_ratio`  | Maker/taker ratio                    | 0.85          |
| `p95_latency_ms`     | P95 order age latency (milliseconds) | 250           |
| `risk_ratio`         | Risk ratio                           | 0.35          |

## Usage

### Basic Export

Export KPIs from soak artifacts to Redis:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url redis://localhost:6379/0 \
  --ttl 3600
```

### Dry-Run Mode

Preview what would be exported without actually writing to Redis:

```bash
python -m tools.shadow.export_to_redis \
  --src artifacts/soak/latest \
  --redis-url redis://localhost:6379/0 \
  --dry-run
```

Output:
```
[INFO] Loading summaries from: artifacts/soak/latest
[INFO] Loaded 8 iteration summaries
[INFO] Aggregating KPIs by symbol...
[INFO] Aggregated KPIs for 2 symbols
  BTCUSDT: 4 KPIs
  ETHUSDT: 4 KPIs
[DRY-RUN] Would export: shadow:latest:BTCUSDT:edge_bps = 3.2 (TTL=3600s)
[DRY-RUN] Would export: shadow:latest:BTCUSDT:maker_taker_ratio = 0.85 (TTL=3600s)
...
[DRY-RUN] Would export 8 keys
```

### Makefile Commands

Use convenient Makefile targets:

```bash
# Export to Redis (production)
make shadow-redis-export

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
# List all shadow keys
redis-cli --scan --pattern "shadow:latest:*"

# Get specific KPI value
redis-cli GET shadow:latest:BTCUSDT:edge_bps

# Check TTL (time remaining before expiry)
redis-cli TTL shadow:latest:BTCUSDT:edge_bps
# Returns seconds remaining, or -1 if no TTL, or -2 if key doesn't exist

# Get all KPIs for a symbol
redis-cli --scan --pattern "shadow:latest:BTCUSDT:*" | xargs redis-cli MGET
```

### Manual Cleanup

Keys auto-expire after TTL (3600s = 1 hour), but you can manually clean up:

```bash
# Delete all shadow keys
redis-cli --scan --pattern "shadow:latest:*" | xargs redis-cli DEL

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
  --src PATH           Source directory with ITER_SUMMARY_*.json files
                       (default: artifacts/soak/latest)
  
  --redis-url URL      Redis connection URL
                       (default: redis://localhost:6379/0)
  
  --ttl SECONDS        TTL for Redis keys in seconds
                       (default: 3600 = 1 hour)
  
  --dry-run            Preview mode: print what would be exported
                       without actually exporting
```

### Python API

```python
from tools.shadow.export_to_redis import (
    load_iter_summaries,
    aggregate_kpis,
    export_to_redis,
    get_redis_client
)

# Load summaries
summaries = load_iter_summaries(Path("artifacts/soak/latest"))

# Aggregate KPIs
kpis = aggregate_kpis(summaries)
# Returns: {"BTCUSDT": {"edge_bps": 3.2, ...}, ...}

# Get Redis client
client = get_redis_client("redis://localhost:6379/0")

# Export
exported_count = export_to_redis(kpis, client, ttl=3600)
```

## Changelog

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
