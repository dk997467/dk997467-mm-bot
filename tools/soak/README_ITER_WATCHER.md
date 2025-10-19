# 🔍 ITERATION WATCHER — Driver-Aware Soak Monitoring

## Overview

The **Iteration Watcher** is a stdlib-only monitoring system that tracks soak test performance after each iteration and provides driver-aware micro-tuning recommendations.

**Key features:**
- ✅ Per-iteration metrics collection (net_bps, adverse, slippage, blocks)
- ✅ Driver-aware tuning suggestions (slippage vs adverse vs blocks)
- ✅ Cumulative TUNING_REPORT.json for full soak history
- ✅ Integrated with GitHub Actions CI/CD
- ✅ KPI Gate enforcement (fail job on FAIL verdict)
- ✅ No external dependencies (stdlib only)

---

## Architecture

```
tools/soak/
├── default_overrides.json      ← Default runtime parameters
├── iter_watcher.py              ← Per-iteration monitoring logic
├── run.py                       ← Main soak runner (with watcher integration)
└── analyze_edge_fix.py          ← Post-soak analysis (generates AUDIT_EDGE_FIX.md)

artifacts/soak/latest/
├── ITER_SUMMARY_1.json          ← Iteration 1 summary
├── ITER_SUMMARY_2.json          ← Iteration 2 summary
├── ...
├── TUNING_REPORT.json           ← Cumulative tuning log
└── artifacts/
    ├── EDGE_REPORT.json         ← Current edge metrics
    ├── KPI_GATE.json            ← Pass/fail verdict
    ├── EDGE_SENTINEL.json       ← Auto-tune advice
    └── audit.jsonl              ← Block reasons log
```

---

## Usage

### Local Development

**Run mini-soak with auto-tuning:**
```powershell
# 6 iterations (~30 min each) with auto-tune enabled
python -m tools.soak.run --iterations 6 --auto-tune --mock

# Output:
# | iter_watch | SUMMARY | iter=1 net=2.5 drivers=['slippage_bps'] kpi=WARN |
# | iter_watch | SUGGEST | {"base_spread_bps_delta": 0.02, "tail_age_ms": 30} |
# | iter_watch | RATIONALE | slippage_bps=3.50 (driver) → widen spread +0.02, tail +30ms |
```

**View iteration summaries:**
```powershell
Get-Content artifacts\soak\latest\ITER_SUMMARY_1.json
Get-Content artifacts\soak\latest\TUNING_REPORT.json
```

**Post-soak analysis:**
```powershell
python -m tools.soak.analyze_edge_fix
Get-Content artifacts\soak\latest\AUDIT_EDGE_FIX.md
```

---

### GitHub Actions CI/CD

**Trigger mini-soak workflow:**
1. Go to Actions → "Soak (Windows self-hosted, 24-72h)"
2. Click "Run workflow"
3. Configure inputs:
   - `iterations`: 6 (for 3-hour test)
   - `auto_tune`: true
   - `overrides_json`: (leave empty for defaults)

**Workflow behavior:**
- ✅ Seeds default overrides from `tools/soak/default_overrides.json`
- ✅ Runs `python -m tools.soak.run --iterations 6 --auto-tune --mock`
- ✅ After each iteration, logs `| iter_watch | SUMMARY |` markers
- ✅ Checks `KPI_GATE.json` verdict at the end
- ✅ Fails job if `verdict == "FAIL"`
- ✅ Uploads all artifacts (EDGE, KPI, TUNING, ITER_SUMMARY_*)

**Example workflow log:**
```
[ITER 1/6] Starting iteration
================================================
| seed | overrides | default_overrides.json |
| soak_iter_tune | OK | ADJUSTMENTS=2 net_bps=2.50 |
  - slippage driver detected → widen spread +0.03
  - min_interval blocks high → increase +15ms
| iter_watch | SUMMARY | iter=1 net=2.5 drivers=['slippage_bps'] kpi=WARN |
| iter_watch | SUGGEST | {"base_spread_bps_delta": 0.02, "tail_age_ms": 30} |
| iter_watch | RATIONALE | slippage_bps=3.50 (driver) → widen spread +0.02, tail +30ms |
[ITER 2/6] Starting iteration
...
[MINI-SOAK COMPLETE] 6 iterations with auto-tuning
================================================
| kpi_gate | verdict=PASS | reasons=[] |
✅ KPI Gate: PASS
```

---

## Iteration Watcher API

### `summarize_iteration(artifacts_dir: Path) -> Dict`

Reads artifacts and extracts key metrics.

**Input:** Directory containing `EDGE_REPORT.json`, `KPI_GATE.json`, `audit.jsonl`

**Output:**
```json
{
  "runtime_utc": "2025-10-13T12:00:00Z",
  "net_bps": 2.5,
  "gross_bps": 10.0,
  "adverse_bps": 12.0,
  "slippage_bps": 3.5,
  "neg_edge_drivers": ["slippage_bps", "adverse_bps"],
  "blocks": {
    "ratios": {"min_interval": 15.0, "concurrency": 12.0, "allowed": 73.0}
  },
  "kpi_verdict": "WARN"
}
```

---

### `propose_micro_tuning(summary: Dict, current_overrides: Dict) -> Dict`

Suggests parameter adjustments based on drivers and blocks.

**Driver-aware logic:**
- `slippage_bps` is driver → `base_spread_bps_delta +0.02`, `tail_age_ms +30`
- `adverse_bps > 10` → `impact_cap_ratio -0.01`, `max_delta_ratio -0.01`
- `min_interval blocks > 35%` → `min_interval_ms +10`
- `concurrency blocks > 30%` → `replace_rate_per_min -30`

**Output:**
```json
{
  "deltas": {
    "base_spread_bps_delta": 0.02,
    "tail_age_ms": 30
  },
  "rationale": "slippage_bps=3.50 (driver) → widen spread +0.02, tail +30ms",
  "applied": false,
  "conditions": {
    "net_bps": 2.5,
    "slippage_bps": 3.5,
    "min_interval_pct": 15.0
  }
}
```

---

### `process_iteration(iteration_idx, artifacts_dir, output_dir, ...)`

All-in-one function: summarize → suggest tuning → write outputs → print markers.

**Usage in `tools/soak/run.py`:**
```python
from tools.soak import iter_watcher

# After each iteration:
iter_watcher.process_iteration(
    iteration_idx=iteration + 1,
    artifacts_dir=Path("artifacts/soak/latest/artifacts"),
    output_dir=Path("artifacts/soak/latest"),
    current_overrides=current_overrides,
    print_markers=True
)
```

---

## Default Overrides

**File:** `tools/soak/default_overrides.json`

```json
{
  "base_spread_bps_delta": 0.14,
  "impact_cap_ratio": 0.09,
  "max_delta_ratio": 0.14,
  "min_interval_ms": 65,
  "replace_rate_per_min": 280,
  "tail_age_ms": 620
}
```

**When used:**
- GitHub Actions workflow (if `overrides_json` input is empty)
- Local testing (via `MM_RUNTIME_OVERRIDES_JSON` env var)

**How to update:**
1. Edit `tools/soak/default_overrides.json`
2. Commit to repo
3. Next CI run will use new defaults

---

## KPI Gate Enforcement

**File:** `artifacts/soak/latest/artifacts/KPI_GATE.json`

**Structure:**
```json
{
  "verdict": "PASS",  // or "WARN", "FAIL"
  "reasons": [],
  "runtime": {"utc": "2025-10-13T12:00:00Z", "version": "0.1.0"}
}
```

**CI Behavior:**
- `verdict == "FAIL"` → Job exits with code 1 (fails)
- `verdict == "WARN"` → Job continues with warning
- `verdict == "PASS"` → Job succeeds

**Log marker:**
```
| kpi_gate | verdict=FAIL | reasons=[EDGE, LATENCY] |
❌ KPI Gate: FAIL - Terminating job
```

---

## Artifacts

### Per-Iteration

**`ITER_SUMMARY_N.json`** — Full summary for iteration N:
```json
{
  "iteration": 1,
  "summary": { ... },
  "tuning": {
    "deltas": { ... },
    "rationale": "...",
    "applied": false
  }
}
```

### Cumulative

**`TUNING_REPORT.json`** — All iterations in one file:
```json
[
  {
    "iteration": 1,
    "runtime_utc": "...",
    "net_bps": 2.5,
    "kpi_verdict": "WARN",
    "suggested_deltas": {...},
    "rationale": "...",
    "applied": false
  },
  {
    "iteration": 2,
    "runtime_utc": "...",
    "net_bps": 2.8,
    "kpi_verdict": "PASS",
    "suggested_deltas": {},
    "rationale": "No micro-adjustments needed",
    "applied": false
  }
]
```

---

## Log Markers

**Format:**
```
| iter_watch | SUMMARY | iter=N net=X.XX drivers=[...] kpi=VERDICT |
| iter_watch | SUGGEST | {...} |
| iter_watch | RATIONALE | ... |
```

**Examples:**
```
| iter_watch | SUMMARY | iter=1 net=2.5 drivers=['slippage_bps'] kpi=WARN |
| iter_watch | SUGGEST | {"base_spread_bps_delta": 0.02, "tail_age_ms": 30} |
| iter_watch | RATIONALE | slippage_bps=3.50 (driver) → widen spread +0.02, tail +30ms |

| iter_watch | SUMMARY | iter=2 net=2.8 drivers=[] kpi=PASS |
| iter_watch | SUGGEST | (none) |
```

**Searchable patterns:**
- `grep "iter_watch.*SUMMARY" artifacts/soak/logs/*.log`
- `grep "iter_watch.*SUGGEST" artifacts/soak/logs/*.log`

---

## Testing

**Mock mode (no real data):**
```powershell
python -m tools.soak.run --iterations 3 --auto-tune --mock
```

**Manual watcher test:**
```python
from pathlib import Path
from tools.soak import iter_watcher

# Create mock artifacts
artifacts_dir = Path("artifacts/soak/latest/artifacts")
artifacts_dir.mkdir(parents=True, exist_ok=True)

# Summarize
summary = iter_watcher.summarize_iteration(artifacts_dir)
print(summary)

# Suggest tuning
tuning = iter_watcher.propose_micro_tuning(summary, current_overrides={})
print(tuning)
```

---

## Acceptance Criteria

✅ **Local:**
- `python -m tools.soak.run --iterations 6 --auto-tune --mock` succeeds
- Log shows `| iter_watch | SUMMARY |` markers after each iteration
- `artifacts/soak/latest/ITER_SUMMARY_*.json` files created
- `artifacts/soak/latest/TUNING_REPORT.json` contains all iterations

✅ **CI/CD:**
- Workflow input `iterations=6` triggers mini-soak mode
- `tools/soak/default_overrides.json` used if `overrides_json` empty
- Job fails if `KPI_GATE.json` verdict == "FAIL"
- All artifacts uploaded to Actions artifacts

---

## Troubleshooting

**Issue: `ModuleNotFoundError: No module named 'tools.soak.iter_watcher'`**
- **Fix:** Ensure `PYTHONPATH` includes project root: `$env:PYTHONPATH = "$PWD;$PWD\src"`

**Issue: No `| iter_watch |` markers in log**
- **Check:** `iter_watcher` import failed (check Python version ≥ 3.10 for `|` type hints)
- **Check:** `--auto-tune` flag is set
- **Check:** `--iterations` > 0

**Issue: KPI Gate check fails but no file found**
- **Check:** `artifacts/soak/latest/artifacts/KPI_GATE.json` exists
- **Reason:** Watcher generates mock KPI_GATE in `--mock` mode
- **Fix:** Ensure iteration completed successfully

---

## Next Steps

1. **Run local test:** `python -m tools.soak.run --iterations 3 --auto-tune --mock`
2. **Check outputs:** Review `ITER_SUMMARY_*.json` and `TUNING_REPORT.json`
3. **Trigger CI:** Run GitHub Actions workflow with `iterations=6`
4. **Monitor:** Check for `| iter_watch |` markers in CI logs
5. **Download artifacts:** Review uploaded TUNING_REPORT and EDGE_REPORT

---

**Version:** 1.0  
**Last Updated:** 2025-10-13  
**Maintainer:** mm-bot team

