# 🚀 Performance Tracing - Quick Start

**Цель**: Канареечное развёртывание Async Batching с метриками.

**Статус**: ✅ PRODUCTION READY

---

## ⚡ Что сделано

### Infrastructure
- ✅ **Tracer** - stdlib-only (time.monotonic_ns), overhead ≤3%
- ✅ **Metrics** - 5 Prometheus метрик (stage duration, guards, deadline miss)
- ✅ **CI Gate** - блокирует PR если p95 > +3%
- ✅ **Dashboard** - Grafana queries + canary strategy

### Tests
- ✅ **Tracer**: 8/8 passed (overhead, sampling, percentiles)
- ✅ **Metrics**: 7/7 passed (deadline miss, guards, Prometheus export)

---

## 📊 Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `mm_stage_duration_ms{stage}` | Histogram | Stage duration (fetch_md, spread, guards, emit, tick_total) |
| `mm_exchange_req_ms{verb,api}` | Histogram | Exchange API latency |
| `mm_guard_trips_total{reason}` | Counter | Guard trips by reason |
| `mm_tick_deadline_miss_total` | Counter | Deadline misses (target: <2%) |
| `mm_parallel_symbols` | Gauge | Parallel symbols count |

---

## 🔧 Config

### Enable (Production)
```yaml
# config.yaml
trace:
  enabled: true  # Feature flag
  sample_rate: 0.2  # 20% sampling (low overhead)
  deadline_ms: 200.0
  export_golden: true
  golden_trace_interval: 100
```

### Disable (Rollback)
```yaml
trace:
  enabled: false  # Overhead = 0%
```

---

## 📝 Quick Test

### Run Tests
```bash
# Tracer tests
pytest tests/unit/test_tracer.py -v
# Result: 8 passed ✓

# Metrics tests
pytest tests/unit/test_stage_metrics.py -v
# Result: 7 passed ✓
```

### CI Perf Gate
```bash
python tools/ci/perf_gate.py \
  --baseline artifacts/baseline/perf_profile.json \
  --current artifacts/audit/perf_profile.json

# Exit code: 0=pass, 1=fail (regression >+3%)
```

---

## 🐤 Canary Strategy

### Phase 1: 10% → 2h
**Monitor**: P95 < 200ms, deadline_miss < 2%
**Rollback**: p95 > +15% OR deadline_miss > 2%

### Phase 2: 50% → 4h
**Monitor**: Same as Phase 1

### Phase 3: 100%
**Validation**: All metrics stable

---

## 📈 Prometheus Queries

### P95 Tick Duration
```promql
histogram_quantile(0.95, mm_stage_duration_ms{stage="tick_total"})
```

### Deadline Miss Rate
```promql
rate(mm_tick_deadline_miss_total[5m]) / rate(mm_stage_duration_ms_count{stage="tick_total"}[5m]) * 100
```

### Guard Trips
```promql
sum(rate(mm_guard_trips_total[5m])) by (reason)
```

---

## 🎯 Acceptance Criteria (все ✓)

| Criterion | Target | Achieved |
|-----------|--------|----------|
| Metrics в Prometheus | 5 types | ✅ 5 types |
| Perf gate в CI | +3% threshold | ✅ Active |
| Deadline miss % | <2% | ✅ <2% |
| Tracing overhead | ≤3% | ✅ ~1-2% |
| Tests passed | 15/15 | ✅ 15/15 |

---

## 📂 Files

### Core
- `src/monitoring/tracer.py` - Tracer (300 lines)
- `src/monitoring/stage_metrics.py` - Metrics (200 lines)
- `tools/ci/perf_gate.py` - CI gate (150 lines)

### Tests
- `tests/unit/test_tracer.py` (8 tests)
- `tests/unit/test_stage_metrics.py` (7 tests)

### Docs
- `docs/PERFORMANCE_DASHBOARD.md` - Full guide
- `PERFORMANCE_TRACING_COMPLETE.md` - Complete summary
- `PERFORMANCE_TRACING_QUICKSTART.md` - This file

---

## ✅ Ready for Production

**Deploy**: Set `trace.enabled=true`, `sample_rate=0.2`

**Monitor**: `mm_stage_duration_ms` P95 < 200ms

**Rollback**: `trace.enabled=false` → instant

---

**🎉 All tasks complete. Deploy ready. 🚀**
