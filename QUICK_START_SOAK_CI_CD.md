# Quick Start — Soak-72h + CI/CD Infrastructure

## 🚀 TL;DR

**What was built:**
- Complete Soak-72h testing infrastructure
- CI/CD gates (readiness + golden regression)
- Prometheus alerts + auto-rollback
- Grafana dashboard + export tool

**Status:** ✅ All 18/18 tests passing, ready for integration

---

## 📦 Quick Commands

### 1. Run Soak Test (Mock Mode)

```bash
python -m tools.soak.run --hours 72 --mock \
  --export-json artifacts/reports/soak_metrics.json \
  --export-md artifacts/reports/SOAK_RESULTS.md \
  --gate-summary artifacts/reports/gates_summary.json

# Expected: Exit 0 (PASS)
# Artifacts: 3 files created
```

### 2. Golden Regression Check

```bash
# Create test files
mkdir -p artifacts/golden
echo '{"a":1,"b":2.0}' > artifacts/golden/baseline.json
echo '{"a":1,"b":2.0}' > artifacts/golden/actual.json

# Compare (should pass)
python -m tools.tests.golden_compare \
  --baseline artifacts/golden/baseline.json \
  --actual artifacts/golden/actual.json \
  --fail-on-drift

# Expected: Exit 0 (no drifts)
```

### 3. Readiness Validation

```bash
# Generate score
CI_FAKE_UTC="1970-01-01T00:00:00Z" \
  python -m tools.release.readiness_score \
  --out-json artifacts/reports/readiness.json

# Validate
python -m tools.ci.validate_readiness artifacts/reports/readiness.json

# Expected: Exit 1 (HOLD) because score < 100
```

### 4. Run All Tests

```bash
# Set PYTHONPATH
export PYTHONPATH=$PWD  # Linux/Mac
$env:PYTHONPATH = "$PWD"  # Windows PowerShell

# Run all tests
python tests/unit/test_soak_aggregators.py
python tests/unit/test_rollback_policy.py
python tests/unit/test_golden_compare.py
python tests/unit/test_validate_readiness.py
python tests/e2e/test_soak_runner_dry.py

# Expected: All 5 tests PASS
```

### 5. Start Rollback Watcher (Webhook Server)

```bash
python -m orchestrator.rollback_watcher \
  --port 8080 \
  --policy deploy/policies/rollback.yaml \
  --dry-run

# Health check:
curl http://localhost:8080/health

# Expected: {"status": "healthy"}
```

---

## 🧪 Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| Soak aggregators (P95, EMA) | 2 | ✅ PASS |
| Rollback policy logic | 3 | ✅ PASS |
| Golden file comparison | 5 | ✅ PASS |
| Readiness validator | 7 | ✅ PASS |
| Soak runner E2E | 2 | ✅ PASS |
| **TOTAL** | **18** | **✅ 18/18** |

---

## 📊 Key Metrics & Gates

### Hard Gates (FAIL on breach)
- **Latency P95:** ≤ 150ms
- **Hit Ratio:** ≥ 70%
- **Deadline Miss:** ≤ 2%
- **Edge BPS:** ≥ 2.0

### Soft Gates (WARN only)
- **Maker Share:** ≥ 85%
- **WS Lag:** ≤ 200ms

---

## 🔧 GitHub Actions Integration

### Soak Test Workflow

**Trigger:** Manual (workflow_dispatch)

**Parameters:**
- `duration_hours`: 72 (default)
- `mock_mode`: false (default)

**Run from UI:**
1. Go to Actions tab
2. Select "Soak Test (72h)"
3. Click "Run workflow"
4. Set parameters
5. Run

### Nightly Workflow (Updated)

**New steps added:**
1. Generate readiness score (deterministic)
2. Validate readiness gate → FAIL if `verdict != "GO"`
3. Golden regression check → FAIL if drift detected
4. Check gates → Exit 1 if any fails

---

## 📈 Prometheus & Grafana

### Deploy Prometheus Alerts

```bash
# Copy alerts file
cp deploy/prometheus/alerts_soak.yml /etc/prometheus/rules/

# Reload Prometheus
curl -X POST http://localhost:9090/-/reload
```

### Import Grafana Dashboard

```bash
# Set token
export GRAFANA_TOKEN=<your-token>

# Import dashboard
python -m tools.ops.grafana_export import \
  --url http://grafana:3000 \
  --input deploy/grafana/dashboards/mm_operability.json
```

**Or via UI:**
- Dashboards → Import → Upload `mm_operability.json`

---

## 🚨 Auto-Rollback

### Rollback Actions (on hard gate breach)

1. ✅ Scale strategy to 0 (stop trading)
2. ✅ Open circuit breaker (block orders)
3. ✅ Freeze order placements
4. ✅ Send critical notifications (oncall, slack)

**Cooldown:** 15 minutes between rollbacks

### Configure Alertmanager

```yaml
receivers:
  - name: 'rollback-watcher'
    webhook_configs:
      - url: 'http://rollback-watcher:8080/alert-hook'
```

---

## 📁 File Structure

```
├── .github/workflows/
│   ├── soak.yml                        # NEW: 72h soak workflow
│   └── ci-nightly.yml                  # UPDATED: + gates
│
├── deploy/
│   ├── prometheus/alerts_soak.yml      # 8 alerts
│   ├── policies/rollback.yaml          # Auto-rollback policy
│   └── grafana/dashboards/mm_operability.json  # Dashboard
│
├── orchestrator/
│   └── rollback_watcher.py             # Webhook server
│
├── tools/
│   ├── soak/run.py                     # Soak orchestrator
│   ├── tests/golden_compare.py         # Golden regression
│   ├── ci/validate_readiness.py        # Readiness gate
│   └── ops/grafana_export.py           # Grafana API
│
└── tests/
    ├── unit/
    │   ├── test_soak_aggregators.py
    │   ├── test_rollback_policy.py
    │   ├── test_golden_compare.py
    │   └── test_validate_readiness.py
    └── e2e/
        └── test_soak_runner_dry.py
```

---

## ✅ Acceptance Checklist

- [x] Soak runner with gates → PASS
- [x] GitHub Actions workflows → READY
- [x] Prometheus alerts (8) → DEFINED
- [x] Rollback policy + watcher → FUNCTIONAL
- [x] Golden regression tool → WORKING
- [x] Readiness validator → STRICT
- [x] Grafana dashboard (7 panels) → CREATED
- [x] Grafana export tool → WORKING
- [x] All tests (18) → PASSING
- [x] stdlib-only → YES
- [x] Deterministic I/O → YES

---

## 🎯 Next Steps

1. **Deploy Prometheus alerts** → `/etc/prometheus/rules/alerts_soak.yml`
2. **Configure Alertmanager** → Add webhook for rollback-watcher
3. **Start rollback watcher** → `systemd` service or Docker container
4. **Import Grafana dashboard** → Via API or UI
5. **Run first 72h soak test** → GitHub Actions workflow
6. **Monitor results** → Review artifacts, adjust thresholds

---

## 📚 Full Documentation

See: `SOAK_72H_CI_CD_IMPLEMENTATION_SUMMARY.md` for complete details.

---

**Status:** ✅ READY FOR PRODUCTION INTEGRATION  
**Last Updated:** 2025-10-11

