# MEGA-AUDIT QUICK REFERENCE

**Target**: net_bps ≥ 3.0  
**Status**: 📊 Ready for first 3h soak  
**Full Report**: [MEGA_AUDIT_NET_BPS_3.0.md](MEGA_AUDIT_NET_BPS_3.0.md)

---

## ⚡ QUICK START (30 seconds)

### Windows (PowerShell):
```powershell
# Run 3h soak with auto-tuning
.\run_3h_soak.ps1
```

### Linux/Mac (Bash):
```bash
# Run 3h soak with auto-tuning
./run_3h_soak.sh
```

### Manual (Any Platform):
```bash
# 1. Set environment
export MM_PROFILE=S1
export PYTHONPATH=$PWD:$PWD/src

# 2. Run soak
python -m tools.soak.run --hours 3 --iterations 6 --auto-tune \
  --export-json artifacts/reports/soak_metrics.json \
  --export-md artifacts/reports/SOAK_RESULTS.md

# 3. Check results
cat artifacts/reports/EDGE_REPORT.json | jq '.totals.net_bps'
```

---

## 📊 COMPONENT BREAKDOWN TABLE

| Component | Expected Range | Target (net=3.0) | Impact | Sign |
|-----------|---------------|------------------|--------|------|
| **gross_bps** | 5-15 | ≥ 8.0 | Revenue | **+** |
| **fees_eff_bps** | -0.1 to -0.2 | -0.1 | VIP tier | **-** |
| **slippage_bps** | -5 to +3 | ≤ -2.0 | **KEY DRIVER** | **±** |
| **inventory_bps** | -0.01 to -0.5 | ≤ -0.2 | Inventory risk | **-** |
| **adverse_bps** | (informational) | < 4.0 | NOT in formula | **±** |

**Formula** (VERIFIED ✅):
```python
net_bps = gross_bps + fees_eff_bps + slippage_bps + inventory_bps
```

---

## 🎯 DRIVER-AWARE TUNING MATRIX

| If This | Then Adjust | Change | Expected Effect |
|---------|------------|--------|-----------------|
| **slippage_bps** in drivers | base_spread_bps_delta | +0.02 to +0.05 | +1.0 to +2.0 bps |
| | tail_age_ms | +50 to +100 | |
| **adverse_bps > 4.0** | impact_cap_ratio | -0.02 to -0.04 | +0.5 to +1.5 bps |
| | max_delta_ratio | -0.02 to -0.04 | |
| **min_interval blocks > 40%** | min_interval_ms | +20 to +40 | +0.3 to +0.8 bps |
| **concurrency blocks > 30%** | replace_rate_per_min | -30 to -60 | +0.2 to +0.5 bps |
| **order_age > 330 + healthy** | min_interval_ms | -10 | +0.3 to +0.7 bps |
| (age relief) | replace_rate_per_min | +30 | (optimization) |

---

## 🎛️ BASELINE OVERRIDES (CONSERVATIVE START)

**File**: `artifacts/soak/runtime_overrides.json` (already created)

```json
{
  "min_interval_ms": 70,          // +10 from best cell (reduce blocks)
  "replace_rate_per_min": 280,    // -20 from best cell (reduce concurrency)
  "base_spread_bps_delta": 0.10,  // -0.25 from S1 (let auto-tune widen)
  "tail_age_ms": 650,              // -50 from S1 (fresher quotes)
  "impact_cap_ratio": 0.09,        // -0.01 from best cell (tighter adverse)
  "max_delta_ratio": 0.14          // -0.01 from best cell (less aggressive)
}
```

**Expected Baseline**: net_bps **2.0 - 2.5** → Auto-tuning will adjust to **2.8 - 3.2**

---

## ✅ SUCCESS CRITERIA

| Metric | FAIL (<) | WARN (<) | OK (≥) | IDEAL (≥) |
|--------|----------|----------|--------|-----------|
| **net_bps_total** | 2.5 | 2.8 | 2.8 | **3.0** |
| **adverse_bps_p95** | - | - | - | ≤ 4.0 |
| **slippage_bps_p95** | - | - | - | ≤ 3.0 |
| **cancel_ratio** | 0.65 | 0.60 | - | ≤ 0.55 |
| **order_age_p95_ms** | - | - | - | ≤ 330 |
| **maker_share_pct** | 80.0 | 85.0 | 85.0 | ≥ 90.0 |

---

## 🚦 DECISION MATRIX (POST-SOAK)

| net_bps Result | Verdict | Action |
|---------------|---------|--------|
| **≥ 3.0** | ✅ SUCCESS | Freeze overrides, run 24h stability soak |
| **2.8 - 2.99** | ⚠️ OK | Review drivers, apply 1-2 adjustments, re-run 3h |
| **2.5 - 2.79** | ⚠️ WARN | Apply targeted package, re-run 3h |
| **< 2.5** | ❌ FAIL | Review blocks + breakdown, may need fallback mode |

---

## 📋 POST-SOAK CHECKLIST

```bash
# 1. Check verdict
cat artifacts/reports/KPI_GATE.json | jq '.verdict'

# 2. Extract net_bps
cat artifacts/reports/EDGE_REPORT.json | jq '.totals.net_bps'

# 3. Identify drivers
cat artifacts/reports/EDGE_REPORT.json | jq '.totals.neg_edge_drivers'

# 4. Check block reasons
cat artifacts/reports/EDGE_REPORT.json | jq '.totals.block_reasons'

# 5. Review final overrides
cat artifacts/soak/runtime_overrides.json
```

---

## 🔧 RUNTIME LIMITS (GUARDRAILS)

| Field | Min | Max | Initial | Notes |
|-------|-----|-----|---------|-------|
| min_interval_ms | 50 | 300 | 70 | Floor 50ms prevents excessive churn |
| replace_rate_per_min | 120 | 360 | 280 | Cap 360 prevents exchange throttling |
| base_spread_bps_delta | 0.0 | 0.6 | 0.10 | Max +0.10 per iteration |
| impact_cap_ratio | 0.04 | 0.12 | 0.09 | Tighter = less adverse |
| tail_age_ms | 400 | 1000 | 650 | Cap 1s for quote freshness |
| max_delta_ratio | 0.10 | 0.20 | 0.14 | Spread tightening limit |

**Auto-Tuning Guards**:
- Max **2 changes per field per iteration**
- Max **+0.10 spread_delta adjustment per iteration**
- **Multi-fail guard**: 3+ triggers → calm down only
- **Fallback mode**: 2 consecutive net_bps < 0 → conservative package

---

## 📚 KEY FILES

| File | Purpose |
|------|---------|
| `MEGA_AUDIT_NET_BPS_3.0.md` | Full technical audit (70 pages) |
| `artifacts/soak/runtime_overrides.json` | Current overrides (auto-tuned) |
| `artifacts/reports/EDGE_REPORT.json` | Extended metrics with diagnostics |
| `artifacts/reports/KPI_GATE.json` | Gate results (PASS/FAIL) |
| `run_3h_soak.ps1` | Windows runner script |
| `run_3h_soak.sh` | Linux/Mac runner script |
| `tools/soak/run.py` | Auto-tuning engine |
| `strategy/edge_sentinel.py` | Profile + runtime override system |
| `tools/reports/edge_metrics.py` | EDGE_REPORT calculation |

---

## 🎯 EXPECTED TIMELINE

| Time | Action | Expected Result |
|------|--------|-----------------|
| **T+0h** | Create overrides, start 3h soak | Baseline: net_bps 2.0-2.5 |
| **T+1h** | Auto-tuning iteration 2 | Adjustments applied |
| **T+2h** | Auto-tuning iteration 4 | Convergence |
| **T+3h** | Review EDGE_REPORT | **net_bps 2.8-3.2** (70% confidence) |
| **T+3h15m** | Decision point | Success / Re-run / Investigate |
| **T+6h** (if re-run) | Second 3h soak | Adjusted overrides |
| **T+24h** (if success) | 24h stability soak | Production validation |

---

## ⚠️ COMMON ISSUES & SOLUTIONS

| Issue | Symptom | Solution |
|-------|---------|----------|
| **Positive slippage** | slippage_bps > +1.0 | Widen spread (+0.02 to +0.05) |
| **High adverse** | adverse_bps_p95 > 4.0 | Lower impact_cap (-0.02 to -0.04) |
| **Excessive blocks** | min_interval > 40% | Increase min_interval_ms (+20-40) |
| **High cancel ratio** | cancel_ratio > 0.6 | Reduce replace_rate (-30-60) |
| **Stale quotes** | order_age > 350ms | Age relief (if execution healthy) |
| **Negative net_bps** | net_bps < 0 for 2 iterations | Fallback mode auto-triggers |

---

## 🚀 FINAL CHECKLIST

Before running:
- ✅ `artifacts/soak/runtime_overrides.json` exists
- ✅ `config/profiles/market_maker_S1.json` exists
- ✅ Python 3.11+ installed
- ✅ Dependencies installed (`pip install -r requirements.txt`)

After running:
- ✅ Check `artifacts/reports/EDGE_REPORT.json`
- ✅ Review `artifacts/soak/summary.txt`
- ✅ Inspect final `artifacts/soak/runtime_overrides.json`
- ✅ Follow decision matrix based on net_bps result

---

**Ready to Run**: ✅  
**Confidence**: 70% achieve net_bps ≥ 2.8 on first 3h run  
**Risk**: LOW (guardrails in place, fallback available)  

**Command**: `./run_3h_soak.ps1` (Windows) or `./run_3h_soak.sh` (Linux/Mac)

