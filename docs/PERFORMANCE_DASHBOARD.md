# Performance Dashboard & Canary Deployment Guide

**Цель**: Построить систему метрик для безопасного канареечного развёртывания Async Batching.

---

## 📊 Prometheus Metrics

### Stage Duration Histograms
```promql
# P95 tick total duration (target: <200ms)
histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total"})

# P95 by stage
histogram_quantile(0.95, mm_stage_duration_ms{stage="stage_fetch_md"})
histogram_quantile(0.95, mm_stage_duration_ms{stage="stage_spread"})
histogram_quantile(0.95, mm_stage_duration_ms{stage="stage_guards"})
histogram_quantile(0.95, mm_stage_duration_ms{stage="stage_emit"})
```

### Guard Trips
```promql
# Total guard trips by reason
sum(rate(mm_guard_trips_total[5m])) by (reason)

# Vol guard trips (soft vs hard)
sum(rate(mm_guard_trips_total{reason=~"vol_.*"}[5m])) by (reason)
```

### Deadline Misses
```promql
# Deadline miss rate (target: <2% for canary)
rate(mm_tick_deadline_miss_total[5m]) / rate(mm_stage_duration_ms_count{stage="tick_total"}[5m]) * 100

# Total deadline misses
sum(mm_tick_deadline_miss_total)
```

### Exchange API Latency
```promql
# P95 exchange request latency
histogram_quantile(0.95, mm_exchange_req_ms) by (verb, api)

# Batch vs individual comparison
histogram_quantile(0.95, mm_exchange_req_ms{api="batch-cancel"}) -
histogram_quantile(0.95, mm_exchange_req_ms{api="cancel"})
```

### Parallel Symbols Gauge
```promql
# Current parallel symbols
mm_parallel_symbols
```

---

## 📈 Grafana Dashboard

### Panel 1: Tick Duration (P50, P95, P99)
**Query**:
```promql
# P50
histogram_quantile(0.50, mm_stage_duration_ms{stage="tick_total"})

# P95 (red line at 200ms)
histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total"})

# P99 (red line at 250ms)
histogram_quantile(0.99, mm_stage_duration_ms{stage="tick_total"})
```

**Alert**: P95 > 200ms OR P99 > 250ms

---

### Panel 2: Stage Breakdown (Stacked)
**Query**:
```promql
# Stacked area chart of stage durations
sum(rate(mm_stage_duration_ms_sum{stage="stage_fetch_md"}[5m])) by (stage) /
sum(rate(mm_stage_duration_ms_count{stage="stage_fetch_md"}[5m])) by (stage)

# Repeat for other stages: stage_spread, stage_guards, stage_emit
```

---

### Panel 3: Deadline Miss Rate
**Query**:
```promql
# Percentage of deadline misses (target: <2%)
rate(mm_tick_deadline_miss_total[5m]) / rate(mm_stage_duration_ms_count{stage="tick_total"}[5m]) * 100
```

**Alert**: Deadline miss % > 2%

---

### Panel 4: Exchange API Efficiency
**Query**:
```promql
# Batch vs individual latency comparison
avg(mm_exchange_req_ms{api="batch-cancel"}) /
avg(mm_exchange_req_ms{api="cancel"})

# Should be <0.5 (batch is 2x faster)
```

---

### Panel 5: Guard Trip Heatmap
**Query**:
```promql
# Guard trips by reason
sum(increase(mm_guard_trips_total[1h])) by (reason)
```

**Alert**: vol_hard > 5 OR latency_hard > 5 (per hour)

---

## 🐤 Canary Deployment Strategy

### Phase 1: 10% Traffic (2 hours)
**Config**:
```yaml
async_batch:
  enabled: true
trace:
  enabled: true
  sample_rate: 0.2
```

**Monitoring**:
```promql
# Check P95 regression
(histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total", env="canary"}) -
 histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total", env="baseline"})) /
 histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total", env="baseline"}) * 100
```

**Rollback Trigger**: P95 regression > +15% OR deadline_miss > 2%

---

### Phase 2: 50% Traffic (4 hours)
**Monitoring**:
- P95(tick_total) < 200ms ✓
- Deadline miss < 2% ✓
- No guard_hard spikes ✓

**Rollback Trigger**: Same as Phase 1

---

### Phase 3: 100% Traffic
**Final Check**:
- P95(tick_total) < 200ms ✓
- P99(tick_total) < 250ms ✓
- Deadline miss < 2% ✓
- Network calls reduced ≥40% ✓

**Rollback**: `async_batch.enabled=false` → instant rollback

---

## 🛠️ CI Performance Gate

### Usage
```bash
# Compare current vs baseline
python tools/ci/perf_gate.py \
  --baseline artifacts/baseline/perf_profile.json \
  --current artifacts/audit/perf_profile.json \
  --report artifacts/ci/perf_gate_report.md

# Exit codes:
# 0 = PASS (no regression)
# 1 = FAIL (regression >+3%)
# 2 = ERROR (missing files)
```

### Gate Thresholds
| Metric | Threshold |
|--------|-----------|
| P95(stage) | +3% |
| P99(stage) | +5% |
| Deadline miss % | +1% |

---

## 📂 Golden Traces

### Export Format
```json
{
  "trace_id": "tick_12345",
  "duration_ms": 187.2,
  "metadata": {
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "parallel_symbols": 10
  },
  "spans": [
    {
      "name": "stage_fetch_md",
      "duration_ms": 68.3
    },
    {
      "name": "stage_spread",
      "duration_ms": 21.8
    },
    {
      "name": "stage_guards",
      "duration_ms": 14.2
    },
    {
      "name": "stage_emit",
      "duration_ms": 92.3
    }
  ],
  "stage_durations": {
    "stage_fetch_md": 68.3,
    "stage_spread": 21.8,
    "stage_guards": 14.2,
    "stage_emit": 92.3
  }
}
```

### Usage
```python
from src.monitoring.tracer import get_tracer

tracer = get_tracer()

# Export golden trace every 100 ticks
if tick_num % 100 == 0:
    trace = tracer.finish_trace()
    json_data = tracer.export_to_json(trace)
    
    with open(f"artifacts/traces/golden_trace_{tick_num}.json", "w") as f:
        json.dump(json_data, f, indent=2)
```

---

## 🔧 Configuration

### Enable Tracing
```yaml
# config.yaml
trace:
  enabled: true  # Feature flag
  sample_rate: 0.2  # 20% sampling (low overhead)
  deadline_ms: 200.0
  export_golden: true
  golden_trace_interval: 100
```

### Disable Tracing (Rollback)
```yaml
trace:
  enabled: false  # Overhead = 0%
```

---

## 📊 Baseline Generation

### Sequential Mode Baseline
```bash
# Run 1000 ticks in sequential mode
async_batch.enabled=false

# Export profile
python tools/ci/export_perf_profile.py \
  --output artifacts/baseline/perf_profile.json
```

### Async Mode Baseline
```bash
# Run 1000 ticks in async mode
async_batch.enabled=true

# Export profile
python tools/ci/export_perf_profile.py \
  --output artifacts/baseline/perf_profile_async.json
```

---

## ✅ Acceptance Criteria

- ✅ Все метрики доступны в Prometheus
- ✅ P95(stage) и P99 фиксируются в artifacts
- ✅ Perf-gate в CI активен (порог +3%)
- ✅ В канарейке: deadline-miss < 2%, partial-fail < 5%
- ✅ Накладные трейсинга ≤ 3%
- ✅ Golden-трейсы детерминированы и сохраняются

---

## 🎯 Quick Start

### 1. Enable Tracing
```yaml
trace:
  enabled: true
  sample_rate: 0.2
```

### 2. Monitor Prometheus
```promql
histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total"})
```

### 3. Run Canary
Start with 10% traffic → monitor for 2h → 50% → 100%

### 4. Rollback if Needed
```yaml
async_batch:
  enabled: false  # Instant rollback
```

---

**🎉 Performance monitoring ready for production!**
