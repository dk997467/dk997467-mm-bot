# Soak Artifact Audit Guide

**Script:** `tools/soak/audit_artifacts.py`  
**Purpose:** Comprehensive post-soak analysis and readiness report  
**Status:** ✅ Ready for use

---

## 🎯 What It Does

Analyzes artifacts from `artifacts/soak/latest/` and produces:

1. **Console Report** — Real-time KPI summary with readiness verdict
2. **Markdown Report** — `POST_SOAK_AUDIT_SUMMARY.md` with trends and recommendations
3. **JSON Summary** — `POST_SOAK_AUDIT_SUMMARY.json` with all computed metrics
4. **CSV Table** — `POST_SOAK_ITER_TABLE.csv` with per-iteration data

---

## 📦 Input Files (Expected)

```
artifacts/soak/latest/
├── ITER_SUMMARY_1.json         # Required (16-24 files)
├── ITER_SUMMARY_2.json
├── ...
├── TUNING_REPORT.json          # Optional
├── DELTA_VERIFY_REPORT.md      # Optional
└── reports/
    └── analysis/
        ├── POST_SOAK_SNAPSHOT.json  # Optional (will derive if missing)
        └── warmup_metrics.prom      # Optional
```

**Minimum Required:**
- At least **16 ITER_SUMMARY_*.json** files
- Ideally **24** for full 24-iteration soak

**Optional (but recommended):**
- `POST_SOAK_SNAPSHOT.json` — Pre-computed KPI aggregates
- `TUNING_REPORT.json` — Auto-tuning deltas and guard skips
- `DELTA_VERIFY_REPORT.md` — Delta application verification
- `warmup_metrics.prom` — Prometheus warmup metrics

---

## 🚀 Usage

### **Basic (from repo root):**

```bash
python -m tools.soak.audit_artifacts
```

### **Custom base directory:**

```bash
python -m tools.soak.audit_artifacts --base path/to/soak/artifacts
```

### **Example output:**

```
==============================================================================
SOAK ARTIFACT AUDIT: artifacts/soak/latest
==============================================================================

[1/11] Verifying folder structure...
✓ Base directory exists: /workspace/artifacts/soak/latest
  Files found: 87 (showing first 120)
    - ITER_SUMMARY_1.json: 12.3 KB
    - ITER_SUMMARY_2.json: 12.5 KB
    ...

Key files:
  ✓ POST_SOAK_SNAPSHOT.json
  ✓ TUNING_REPORT.json
  ✓ DELTA_VERIFY_REPORT.md
  ✗ (missing) warmup_metrics.prom

[2/11] Loading ITER_SUMMARY files...
✓ Found 24 ITER_SUMMARY files
✓ Loaded 24 iterations

[3/11] Computing trend statistics...
Trend Statistics:
Metric               Window     Min      Max   Median
------------------------------------------------------------
net_bps              overall    2.34     3.89     3.12
net_bps              steady     2.67     3.89     3.15
net_bps              last8      2.89     3.65     3.18
...

[5/11] Readiness Gate Check (last-8 window)...
Metric               Target          Actual     Status
------------------------------------------------------------
maker_taker_ratio    >= 0.83          0.871     ✓ PASS
net_bps              >= 2.9           3.180     ✓ PASS
p95_latency_ms       <= 330         312.000     ✓ PASS
risk_ratio           <= 0.40          0.352     ✓ PASS

✅ READINESS: OK (all KPIs within thresholds)

[9/11] Generating recommendations...
Recommendations:
  ✓ All KPIs within target ranges; no immediate action needed

[10/11] Creating Markdown report...
✓ Saved CSV: POST_SOAK_ITER_TABLE.csv
✓ Saved Markdown: POST_SOAK_AUDIT_SUMMARY.md
✓ Saved JSON: POST_SOAK_AUDIT_SUMMARY.json

==============================================================================
🎯 FINAL VERDICT: READINESS: OK
==============================================================================
```

---

## 📊 Output Files

### **1. POST_SOAK_AUDIT_SUMMARY.md**

Comprehensive markdown report with:
- File inventory (present/missing)
- Readiness gate table (target vs actual)
- Trend statistics (overall / STEADY / last-8)
- Tuning & delta verification summary
- Actionable recommendations

**Example:**

```markdown
# Post-Soak Audit Summary

**Generated:** 2025-10-19 12:34:56 UTC  
**Iterations:** 24 (max iter: 24)  
**STEADY Window:** iter >= 7  
**Last-8 Window:** iter >= 17  

## Readiness Gate (last-8 window)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| maker_taker_ratio | >= 0.83 | 0.871 | ✓ PASS |
| net_bps | >= 2.9 | 3.180 | ✓ PASS |
| p95_latency_ms | <= 330 | 312.000 | ✓ PASS |
| risk_ratio | <= 0.40 | 0.352 | ✓ PASS |

**Verdict:** ✅ READINESS: OK

## Recommendations

✓ All KPIs within target ranges; no immediate action needed
```

### **2. POST_SOAK_AUDIT_SUMMARY.json**

Machine-readable JSON with all computed stats:

```json
{
  "timestamp": "2025-10-19 12:34:56 UTC",
  "iterations": 24,
  "snapshot_kpis": {
    "maker_taker_ratio": 0.871,
    "net_bps": 3.18,
    "p95_latency_ms": 312.0,
    "risk_ratio": 0.352
  },
  "readiness": {
    "pass": true,
    "failures": []
  },
  "trend_stats": {
    "net_bps": {
      "overall": {"min": 2.34, "max": 3.89, "median": 3.12},
      "steady": {"min": 2.67, "max": 3.89, "median": 3.15},
      "last8": {"min": 2.89, "max": 3.65, "median": 3.18}
    },
    ...
  }
}
```

### **3. POST_SOAK_ITER_TABLE.csv**

Per-iteration KPI table (for Excel/pandas):

```csv
iter,net_bps,risk_ratio,slippage_p95,adverse_p95,latency_p95_ms,maker_taker_ratio
1,2.45,0.38,1.2,2.1,325,0.82
2,2.67,0.36,1.1,2.0,318,0.84
...
24,3.21,0.35,0.9,1.8,310,0.89
```

---

## 🎯 Readiness Thresholds

Default thresholds (as of 2025-10-19):

| Metric | Threshold | Window |
|--------|-----------|--------|
| **maker_taker_ratio** | ≥ 0.83 | last-8 |
| **net_bps** | ≥ 2.9 | last-8 |
| **p95_latency_ms** | ≤ 330 ms | last-8 |
| **risk_ratio** | ≤ 0.40 | last-8 |

**Window definitions:**
- **overall:** All iterations (1..N)
- **STEADY:** Iterations >= 7 (warm-up complete)
- **last-8:** Highest 8 iterations (e.g., 17..24)

---

## 🔍 What Gets Analyzed

### **1. File Inventory**
- Checks presence of key files
- Lists first 120 files with sizes
- Reports missing optional files

### **2. ITER_SUMMARY Files**
- Loads all `ITER_SUMMARY_*.json`
- Extracts KPIs with robust fallbacks:
  - `net_bps` (multiple field names supported)
  - `risk_ratio` (handles `risk_percent` conversion)
  - `maker_taker_ratio` (can compute from maker/taker counts)
  - `p95_latency_ms` (multiple field names)
  - `slippage_p95`, `adverse_p95`
- Builds DataFrame for trend analysis

### **3. Trend Statistics**
- Computes min/max/median for each KPI
- Three windows: overall, STEADY (iter >= 7), last-8
- Identifies regression or improvement

### **4. POST_SOAK_SNAPSHOT**
- Loads existing snapshot (if present)
- Derives from last-8 window (if missing)
- Extracts 4 readiness KPIs

### **5. Readiness Gate**
- Validates last-8 KPIs against thresholds
- Clear PASS/FAIL per metric
- Overall verdict: OK or HOLD

### **6. TUNING_REPORT**
- Aggregates guard skip reasons
- Counts proposed vs applied deltas
- Top 5 skip reasons histogram

### **7. DELTA_VERIFY_REPORT**
- Parses "Full applications: X/Y (Z%)"
- Reports delta application success rate

### **8. warmup_metrics.prom**
- Extracts `exporter_error` count
- Parses `guard_triggers_total{type="..."}`
- Summary of guard activity

### **9. Recommendations**
- Actionable suggestions based on KPI failures
- Specific parameter nudges for maker/taker imbalance
- Considers STEADY adverse_p95 for risk adjustments

---

## 🛠️ Advanced Usage

### **Check if artifacts are ready for audit:**

```bash
# Ensure at least 16 ITER_SUMMARY files exist
ls -1 artifacts/soak/latest/ITER_SUMMARY_*.json | wc -l
# Output: 24 (good!)
```

### **Run audit and save console output:**

```bash
python -m tools.soak.audit_artifacts 2>&1 | tee audit_output.log
```

### **Parse JSON summary for CI:**

```python
import json
from pathlib import Path

summary = json.loads(Path("artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json").read_text())

if summary["readiness"]["pass"]:
    print("✅ READY FOR RELEASE")
    exit(0)
else:
    print("❌ NOT READY:")
    for failure in summary["readiness"]["failures"]:
        print(f"  - {failure}")
    exit(1)
```

### **Load CSV in pandas:**

```python
import pandas as pd

df = pd.read_csv("artifacts/soak/latest/reports/analysis/POST_SOAK_ITER_TABLE.csv")
print(df[["iter", "net_bps", "risk_ratio", "maker_taker_ratio"]].describe())
```

---

## 📋 Typical Workflow

### **After 24-iteration soak:**

```bash
# 1. Check files exist
ls artifacts/soak/latest/ITER_SUMMARY_*.json

# 2. Run audit
python -m tools.soak.audit_artifacts

# 3. Review markdown report
cat artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.md

# 4. If HOLD: review recommendations
grep "Recommendations" -A 20 artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.md

# 5. Adjust parameters and re-run soak (if needed)
```

---

## 🔧 Customization

### **Change thresholds:**

Edit `READINESS_THRESHOLDS` dict in `audit_artifacts.py`:

```python
READINESS_THRESHOLDS = {
    "maker_taker_ratio": (">=", 0.85),  # Stricter
    "net_bps": (">=", 3.0),             # Higher edge
    "p95_latency_ms": ("<=", 300),      # Tighter latency
    "risk_ratio": ("<=", 0.35),         # Lower risk
}
```

### **Change STEADY window:**

```python
STEADY_START_ITER = 5  # Earlier STEADY (default: 7)
```

---

## 🚨 Troubleshooting

### **"No ITER_SUMMARY data loaded"**

**Cause:** Missing or malformed ITER_SUMMARY files  
**Fix:**
```bash
# Check if files exist
ls artifacts/soak/latest/ITER_SUMMARY_*.json

# Validate JSON
python -m json.tool artifacts/soak/latest/ITER_SUMMARY_1.json
```

### **"Only X ITER_SUMMARY files found (expected >= 16)"**

**Cause:** Incomplete soak run  
**Fix:** Re-run soak with `--iterations 24`

### **"POST_SOAK_SNAPSHOT.json not found; deriving..."**

**Not an error!** Script will compute KPIs from ITER_SUMMARY files.  
To generate snapshot explicitly:
```bash
python -m tools.soak.build_reports \
  --src artifacts/soak/latest \
  --out artifacts/soak/latest/reports/analysis \
  --last-n 8
```

### **"pandas not available; using manual tabulation"**

**Not critical.** Script works without pandas (slightly slower).  
To install pandas:
```bash
pip install pandas
```

---

## 📚 Related Tools

| Tool | Purpose |
|------|---------|
| `tools.soak.run` | Run soak test (generates artifacts) |
| `tools.soak.build_reports` | Build POST_SOAK_SNAPSHOT.json |
| `tools.soak.verify_deltas_applied` | Verify delta application |
| `tools.soak.export_warmup_metrics` | Export Prometheus metrics |
| `tools.soak.ci_gates.readiness_gate` | CI readiness validation |
| `tools.soak.audit_artifacts` | **This tool** — comprehensive audit |

---

## 🎉 Example Success Output

```
==============================================================================
🎯 FINAL VERDICT: READINESS: OK
==============================================================================

📄 Full report: artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.md
📊 JSON summary: artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json
📈 CSV table: artifacts/soak/latest/reports/analysis/POST_SOAK_ITER_TABLE.csv

All KPIs within thresholds:
  ✓ maker_taker_ratio: 0.871 >= 0.83
  ✓ net_bps: 3.18 >= 2.9
  ✓ p95_latency_ms: 312 <= 330
  ✓ risk_ratio: 0.352 <= 0.40

✅ READY FOR RELEASE
```

---

**Last Updated:** 2025-10-19  
**Script Version:** 1.0.0  
**Python:** 3.11+  
**Dependencies:** stdlib only (pandas optional)

