
# Pre-Calibration Readiness

**Last Updated**: 2025-10-10  
**Status**: ✅ READY  
**Version**: 1.0

## Overview

This document describes the pre-calibration readiness infrastructure for spread and queue-ETA auto-calibration.

The system provides:
- ✅ MD-Cache integration with freshness modes
- ✅ Feature collectors (10 calibration metrics per symbol)
- ✅ Fill and pipeline tick loggers (JSONL format)
- ✅ Offline dataset aggregator
- ✅ AB-harness with safety gates
- ✅ Prometheus metrics export

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Pipeline Flow                             │
├─────────────────────────────────────────────────────────────────┤
│  FetchMDStage (MD-Cache)                                        │
│        ↓                                                         │
│  SpreadStage → GuardsStage → InventoryStage → QueueAwareStage  │
│        ↓                                                         │
│  EmitStage                                                       │
│        ↓                                                         │
│  [Feature Collectors] + [Calibration Loggers]                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Calibration Data Flow                         │
├─────────────────────────────────────────────────────────────────┤
│  fills_YYYYMMDD.jsonl                                           │
│  pipeline_ticks_YYYYMMDD.jsonl                                  │
│        ↓                                                         │
│  Dataset Aggregator                                             │
│        ↓                                                         │
│  calib_{from}_{to}.json                                         │
│        ↓                                                         │
│  Summary Report (calib_summary.md)                              │
│        ↓                                                         │
│  AB-Harness Testing                                             │
│        ↓                                                         │
│  ab_run_*.md (results)                                          │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### A) MD-Cache Integration

**Location**: `src/strategy/pipeline_stages.py` → `FetchMDStage`  
**Config**: `md_cache.enabled=true` in config.yaml

**Freshness Modes**:
- **guards**: `fresh_only` (synchronous refresh if stale, 50ms timeout)
- **pricing**: `fresh_ms_for_pricing` threshold (default: 60ms)
- **other**: `stale_ok` (return stale, async refresh)

**Acceptance Criteria**:
- ✅ `hit_ratio ≥ 0.7` on 30-min synthetic
- ✅ `fetch_md p95 ≤ 35 ms`
- ✅ `tick_total p95 ≤ 140–150 ms`
- ✅ `deadline_miss < 2%`

**Configuration Example**:
```yaml
md_cache:
  enabled: true
  ttl_ms: 100
  fresh_ms_for_pricing: 60
  stale_ok: true
  invalidate_on_ws_gap_ms: 300
```

### B) Feature Collectors

**Location**: `src/strategy/feature_collectors.py` → `FeatureCollector`

**Collected Features** (per symbol, EMA-smoothed):
1. `vol_realized` - Realized volatility (bps)
2. `liq_top_depth` - Top-of-book depth (both sides)
3. `latency_p95` - Pipeline latency p95 (ms)
4. `pnl_dev` - PnL deviation from target (bps)
5. `fill_rate` - Fill rate (fills / quotes)
6. `taker_share` - Taker fills percentage
7. `queue_absorb_rate` - Queue consumption rate (qty/sec)
8. `queue_eta_ms` - Estimated time to fill (ms)
9. `slippage_bps` - Per-fill slippage (bps)
10. `adverse_move_bps` - Adverse selection metric (bps)

**Prometheus Export**:
- `mm_symbol_vol_realized{symbol="BTCUSDT"}`
- `mm_symbol_liq_top_depth{symbol="BTCUSDT"}`
- `mm_symbol_latency_p95{symbol="BTCUSDT"}`
- `mm_symbol_pnl_dev{symbol="BTCUSDT"}`
- `mm_symbol_fill_rate{symbol="BTCUSDT"}`
- `mm_symbol_taker_share{symbol="BTCUSDT"}`
- `mm_symbol_queue_absorb_rate{symbol="BTCUSDT"}`
- `mm_symbol_queue_eta_ms{symbol="BTCUSDT"}`
- `mm_symbol_slippage_bps{symbol="BTCUSDT"}`
- `mm_symbol_adverse_move_bps{symbol="BTCUSDT"}`

**Usage**:
```python
from src.strategy.feature_collectors import FeatureCollector

collector = FeatureCollector(ema_alpha=0.1)

# Record tick
collector.record_tick(
    symbol="BTCUSDT",
    mid_price=50000.0,
    bid_depth=10.0,
    ask_depth=12.0,
    latency_ms=45.0,
    pnl_bps=0.5,
    target_pnl_bps=1.0
)

# Record fill
collector.record_fill(
    symbol="BTCUSDT",
    is_maker=True,
    fill_price=50000.0,
    quote_price=50001.0,
    qty=0.1,
    mid_at_quote=50000.0,
    mid_now=50002.0
)

# Export metrics
prometheus_text = collector.export_prometheus()
```

### C) Calibration Loggers

**Location**: `src/strategy/calibration_loggers.py`

**Fill Logger**: `artifacts/edge/feeds/fills_YYYYMMDD.jsonl`

**Format** (one JSON per line):
```json
{
  "ts": 1704067200000,
  "ts_iso": "2025-01-01T00:00:00Z",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "price": 50000.0,
  "qty": 0.1,
  "maker": true,
  "taker": false,
  "queue_pos_est": 5,
  "quote_price": 50001.0,
  "mid_at_quote": 50000.0,
  "mid_now": 50002.0,
  "spread_at_quote_bps": 2.0,
  "latency_ms": 125.0,
  "slip_bps": 0.02
}
```

**Pipeline Tick Logger**: `artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl`

**Format** (sampled, default: every 10th tick):
```json
{
  "ts": 1704067200000,
  "ts_iso": "2025-01-01T00:00:00Z",
  "symbol": "BTCUSDT",
  "stage_latencies": {
    "FetchMDStage": 12.5,
    "SpreadStage": 8.3,
    "GuardsStage": 5.1,
    "InventoryStage": 3.2,
    "QueueAwareStage": 4.8,
    "EmitStage": 2.1
  },
  "stage_p95_ms": 12.5,
  "tick_total_ms": 36.0,
  "cache_hit": true,
  "cache_age_ms": 45,
  "used_stale": false,
  "deadline_miss": false
}
```

**Usage**:
```python
from src.strategy.calibration_loggers import CalibrationLoggerManager

logger_mgr = CalibrationLoggerManager(
    artifacts_dir="artifacts/edge/feeds",
    pipeline_sample_rate=10,
    enabled=True
)

# Log fill
logger_mgr.log_fill(
    symbol="BTCUSDT",
    side="BUY",
    fill_price=50000.0,
    qty=0.1,
    is_maker=True,
    quote_price=50001.0,
    mid_at_quote=50000.0,
    mid_now=50002.0,
    spread_at_quote_bps=2.0,
    latency_ms=125.0
)

# Log pipeline tick
logger_mgr.log_pipeline_tick(
    symbol="BTCUSDT",
    stage_latencies={"FetchMDStage": 12.5},
    tick_total_ms=36.0,
    cache_hit=True,
    cache_age_ms=45,
    used_stale=False,
    deadline_miss=False
)

# Close loggers
logger_mgr.close()
```

### D) Offline Dataset Aggregator

**Location**: `tools/calibration/dataset_aggregator.py`

**Output**: `artifacts/edge/datasets/calib_{from}_{to}.json`

**CLI Usage**:
```bash
python tools/calibration/dataset_aggregator.py \
  --feeds-dir artifacts/edge/feeds \
  --output-dir artifacts/edge/datasets \
  --from-ts 2025-01-01T00:00:00 \
  --to-ts 2025-01-02T00:00:00 \
  --interval-sec 300 \
  --symbols BTCUSDT ETHUSDT
```

**Dataset Structure**:
```json
{
  "from_ts": "2025-01-01T00:00:00Z",
  "to_ts": "2025-01-02T00:00:00Z",
  "interval_sec": 300,
  "total_intervals": 576,
  "filtered_count": 12,
  "intervals": [
    {
      "symbol": "BTCUSDT",
      "interval_start": "2025-01-01T00:00:00Z",
      "interval_end": "2025-01-01T00:05:00Z",
      "interval_sec": 300,
      "targets": {
        "net_bps": 0.15,
        "slippage_bps": 0.05,
        "fill_rate": 0.45,
        "taker_share": 0.08
      },
      "features": {
        "latency_p95_ms": 42.5,
        "cache_hit_ratio": 0.75,
        "cache_age_avg_ms": 38.0,
        "deadline_miss_rate": 0.01,
        "stale_rate": 0.15
      },
      "sample_count": {
        "fills": 18,
        "ticks": 40
      }
    }
  ]
}
```

**Sanity Filters**:
- Remove intervals with `deadline_miss_rate > 5%`
- Remove intervals with `sample_count.ticks < 10`

### E) Calibration Summary Report

**Location**: `tools/calibration/generate_summary.py`

**Output**: `artifacts/edge/reports/calib_summary_{dataset}.md`

**CLI Usage**:
```bash
python tools/calibration/generate_summary.py \
  artifacts/edge/datasets/calib_20250101_000000_20250102_000000.json \
  --reports-dir artifacts/edge/reports
```

**Report Contents**:
- Overview (total intervals, symbols, filtered count)
- Intervals by symbol (table)
- Target distributions (net_bps, slippage_bps, fill_rate, taker_share)
- Feature distributions (all 10 features)
- Data quality (NaN/inf detection)

### F) AB-Harness

**Location**: `src/strategy/ab_harness.py` → `ABHarness`

**Features**:
- Symbol routing (A = baseline, B = candidate)
- Per-bucket metrics tracking
- Safety gates with auto-rollback
- Results export to `artifacts/edge/reports/ab_run_*.md`

**Safety Gates** (default):
1. **slippage_degradation**: Any increase in slippage (B > A), 10 min duration
2. **taker_share_increase**: Taker share increase > +1 p.p., 10 min duration
3. **latency_regression**: Tick total p95 increase > +10%, 10 min duration
4. **deadline_miss_spike**: Deadline miss rate > 2% absolute, 10 min duration

**Usage**:
```python
from src.strategy.ab_harness import ABHarness

harness = ABHarness(
    mode="dry",  # or "online"
    split_pct=0.5,
    whitelist={"BTCUSDT", "ETHUSDT"}
)

# Assign symbols
routing = harness.assign_symbols(["BTCUSDT", "ETHUSDT", "BNBUSDT"])

# Get bucket for symbol
bucket = harness.get_bucket("BTCUSDT")  # "A" or "B"

# Record metrics
harness.record_tick(
    symbol="BTCUSDT",
    net_bps=0.5,
    slippage_bps=0.05,
    fill_rate=0.45,
    taker_share=0.08,
    tick_total_ms=42.0,
    deadline_miss=False
)

# Check safety gates
should_rollback, violated_gates = harness.check_safety_gates()

# Export report
report_path = harness.export_report(run_id="20250110_120000")
```

**AB Report Format** (`artifacts/edge/reports/ab_run_*.md`):
```markdown
# AB Test Report: 20250110_120000

**Generated**: 2025-01-10T12:00:00Z  
**Mode**: dry  
**Split**: 50.0% to B  
**Rollback Triggered**: ✓ NO

## Symbol Routing

- Bucket A: 3 symbols
- Bucket B: 2 symbols

## Metrics Comparison

| Metric | Bucket A | Bucket B | Delta (B - A) | Result |
|--------|----------|----------|---------------|--------|
| Net BPS | 0.5000 | 0.5500 | +0.0500 | ✓ |
| Slippage BPS | 0.0500 | 0.0450 | -0.0050 | ✓ |
| Fill Rate | 0.4500 | 0.4600 | +0.0100 | ✓ |
| Taker Share | 0.0800 | 0.0750 | -0.0050 | ✓ |
| Tick Total P95 (ms) | 42.00 | 40.50 | -1.50 | ✓ |
| Deadline Miss Rate | 0.0100 | 0.0080 | -0.0020 | ✓ |
```

## Readiness Checklist

Before running auto-calibration, verify:

### Prerequisites

- [ ] **MD-Cache enabled** in config (`md_cache.enabled=true`)
- [ ] **Shadow run** completed (60+ min) with `hit_ratio ≥ 0.7`
- [ ] **fetch_md p95 ≤ 35 ms** (check Prometheus or stage metrics)
- [ ] **tick_total p95 ≤ 150 ms**
- [ ] **deadline_miss < 2%**

### Data Collection

- [ ] **Feature collectors** initialized and streaming to Prometheus
- [ ] **Fill logger** writing to `artifacts/edge/feeds/fills_*.jsonl`
- [ ] **Pipeline tick logger** writing to `artifacts/edge/feeds/pipeline_ticks_*.jsonl`
- [ ] **Grafana dashboards** showing `mm_symbol_*` metrics
- [ ] **Logs stable** for 12-48h (no gaps, one \n per record)

### Dataset Generation

- [ ] **Calibration dataset** generated for ≥ 12h (better: 24-48h)
- [ ] **Dataset path**: `artifacts/edge/datasets/calib_{from}_{to}.json`
- [ ] **Sanity report** generated: `artifacts/edge/reports/calib_summary_*.md`
- [ ] **No NaN/inf** values in dataset

### AB-Harness

- [ ] **AB-harness** initialized (dry mode for testing)
- [ ] **Safety gates** enabled
- [ ] **Symbol whitelist** configured (if needed)
- [ ] **Test report** generated: `artifacts/edge/reports/ab_run_*.md`

### CI/CD Gates

- [ ] **CI perf gate** enabled (`tools/ci/stage_perf_gate.py`)
- [ ] **Regression threshold** set to +3% max
- [ ] **All tests** passing (unit + e2e)

## Quick Start

### 1. Enable MD-Cache

Edit `config.yaml`:
```yaml
md_cache:
  enabled: true
  ttl_ms: 100
  fresh_ms_for_pricing: 60
  stale_ok: true
```

### 2. Initialize Feature Collectors and Loggers

```python
from src.strategy.feature_collectors import FeatureCollector
from src.strategy.calibration_loggers import CalibrationLoggerManager

# Feature collector
collector = FeatureCollector(ema_alpha=0.1)

# Calibration loggers
logger_mgr = CalibrationLoggerManager(
    artifacts_dir="artifacts/edge/feeds",
    enabled=True
)

# In your main loop:
# - collector.record_tick(...)
# - collector.record_fill(...)
# - logger_mgr.log_fill(...)
# - logger_mgr.log_pipeline_tick(...)
```

### 3. Run Shadow Test (60+ minutes)

```bash
# Run your MM bot with MD-cache enabled
# Monitor Prometheus: mm_md_cache_hit_ratio, mm_stage_fetch_md_p95_ms

# After 60 min, check metrics:
# - hit_ratio ≥ 0.7
# - fetch_md p95 ≤ 35 ms
# - tick_total p95 ≤ 150 ms
```

### 4. Generate Calibration Dataset

```bash
# After 12-48h of data collection:
python tools/calibration/dataset_aggregator.py \
  --from-ts 2025-01-01T00:00:00 \
  --to-ts 2025-01-02T00:00:00 \
  --interval-sec 300

# Generate summary report:
python tools/calibration/generate_summary.py \
  artifacts/edge/datasets/calib_20250101_000000_20250102_000000.json
```

### 5. Run AB Test (Dry Mode)

```python
from src.strategy.ab_harness import ABHarness

harness = ABHarness(
    mode="dry",
    split_pct=0.2,  # 20% to B
    whitelist={"BTCUSDT", "ETHUSDT"}
)

# Assign symbols and run
routing = harness.assign_symbols(["BTCUSDT", "ETHUSDT"])

# After test period:
report_path = harness.export_report()
```

## Artifact Paths

### Feeds (JSONL logs)
- `artifacts/edge/feeds/fills_YYYYMMDD.jsonl`
- `artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl`

### Datasets
- `artifacts/edge/datasets/calib_{from}_{to}.json`

### Reports
- `artifacts/edge/reports/calib_summary_*.md`
- `artifacts/edge/reports/ab_run_*.md`

## Troubleshooting

### MD-Cache hit ratio < 0.7

**Causes**:
- TTL too short (`ttl_ms < 100`)
- High invalidation rate (WS gaps, price jumps)
- Depth mismatches

**Fix**:
- Increase `ttl_ms` to 120-150ms
- Check `invalidate_on_ws_gap_ms` (default: 300ms)
- Review `md_cache_age_ms` distribution

### Pipeline tick logger not writing

**Causes**:
- Sample rate too high (`sample_rate > 100`)
- Artifacts directory not writable
- File handle not closed

**Fix**:
- Set `pipeline_sample_rate=10` (log every 10th tick)
- Check directory permissions
- Call `logger_mgr.close()` on shutdown

### Dataset has NaN/inf values

**Causes**:
- Division by zero in feature calculation
- Missing fill/tick data
- Corrupt JSONL lines

**Fix**:
- Review `_compute_features()` in `dataset_aggregator.py`
- Increase `min_samples_per_interval`
- Validate JSONL files (check for incomplete lines)

### AB-harness triggers rollback immediately

**Causes**:
- Safety gate thresholds too strict
- Insufficient warm-up period
- Bad candidate configuration

**Fix**:
- Increase `duration_sec` from 600 to 1200 (20 min)
- Adjust `threshold` values
- Run longer baseline period before enabling B

## Next Steps

After completing this readiness checklist:

1. **Auto-calibrate spread**: Use dataset to train spread model
2. **Auto-calibrate queue-ETA nudge**: Use `queue_absorb_rate` + `queue_eta_ms` features
3. **Run AB test**: Compare baseline vs calibrated config
4. **Deploy**: Promote to production if AB test passes

## References

- [MD_CACHE_IMPLEMENTATION_COMPLETE.md](../MD_CACHE_IMPLEMENTATION_COMPLETE.md)
- [MD_CACHE_SAFEGUARDS_COMPLETE.md](../MD_CACHE_SAFEGUARDS_COMPLETE.md)
- [PIPELINE_IMPLEMENTATION_SUMMARY.md](../PIPELINE_IMPLEMENTATION_SUMMARY.md)
- [Prometheus metrics](../monitoring/)

---

**Maintainer**: MM-Bot Team  
**Last Review**: 2025-10-10  
**Next Review**: 2025-11-10

