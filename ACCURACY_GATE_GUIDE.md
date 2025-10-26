# Accuracy Gate: Shadow ↔ Dry-Run Comparison Guide

**Purpose:** Validate consistency between Shadow Mode and Dry-Run Mode by comparing KPI accuracy.

**Goal:** Block PR merges when Shadow and Dry-Run results diverge beyond acceptable thresholds (MAPE, median delta).

---

## Overview

The **Accuracy Gate** compares KPI metrics (`edge_bps`, `maker_taker_ratio`, `p95_latency_ms`, `risk_ratio`) between:
- **Shadow Mode:** Real-time feed processing (or mock)
- **Dry-Run Mode:** Historical replay/mock simulation

If discrepancies exceed thresholds, the PR is blocked to prevent regressions.

---

## Metrics

### 1. MAPE (Mean Absolute Percentage Error)

**Formula:**
```
MAPE = (1/N) * Σ |actual - predicted| / |actual| * 100
```

**Interpretation:**
- **< 5%:** Excellent accuracy
- **5-10%:** Good accuracy
- **10-15%:** Acceptable accuracy (default threshold)
- **> 15%:** **FAIL** - significant divergence

**Default Threshold:** `15%` (0.15)

### 2. Median Absolute Delta

**Formula:**
```
Median Δ = median(|shadow[i] - dryrun[i]| for all i)
```

**Interpretation (for `edge_bps`):**
- **< 0.5 BPS:** Excellent
- **0.5-1.5 BPS:** Acceptable (default threshold)
- **> 1.5 BPS:** **WARN** - review recommended

**Default Threshold:** `1.5 BPS`

---

## Thresholds & Exit Codes

### Exit Codes

| Exit Code | Verdict | Meaning | Action |
|-----------|---------|---------|--------|
| `0` | **PASS** | All thresholds met | Allow PR merge |
| `1` | **FAIL** | Critical threshold violated | **Block PR merge** |
| `2` | **WARN** | Soft threshold violated | Log warning, allow merge (informational) |

### Threshold Configuration

**Default Values (Production):**
- `--mape-threshold 0.15` (15%)
- `--median-delta-threshold-bps 1.5`
- `--min-windows 24` (minimum data points)
- `--max-age-min 90` (data freshness)

**Strict CI Mode:**
- Same as production (enforced in `make accuracy-ci`)

**Development Override:**
```bash
MAPE_THRESHOLD=0.20 make accuracy-compare
```

---

## Usage

### Local Testing

**Basic Comparison:**
```bash
make accuracy-compare
```

**Custom Parameters:**
```bash
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT \
MIN_WINDOWS=48 \
MAPE_THRESHOLD=0.10 \
make accuracy-compare
```

### CI Integration

**Workflow:** `.github/workflows/accuracy.yml`

**Trigger:**
- PR changes to `tools/shadow/**`, `tools/dryrun/**`, `tools/accuracy/**`
- Manual dispatch

**Steps:**
1. Run Shadow Mode (24 iterations, mock)
2. Run Dry-Run Mode (24 iterations, mock/redis)
3. Compare KPIs using `compare_shadow_dryrun.py`
4. Post PR comment with verdict + table
5. Fail PR if verdict = FAIL

**Manual Trigger:**
```bash
gh workflow run accuracy.yml -f min_windows=48 -f mape_threshold=0.10
```

---

## Reading Reports

### ACCURACY_REPORT.md

**Structure:**
```markdown
# Accuracy Gate: Shadow ↔ Dry-Run Comparison

**Verdict:** PASS

## Thresholds
- MAPE threshold: 15.0%
- Median Δ threshold: 1.5 BPS

## Per-Symbol Comparison

### BTCUSDT
| KPI | MAPE (%) | Median Δ | Shadow N | Dryrun N | Status |
|-----|----------|----------|----------|----------|--------|
| edge_bps | 5.23 | 0.82 | 24 | 24 | ✅ OK |
| maker_taker_ratio | 3.15 | 0.01 | 24 | 24 | ✅ OK |
| p95_latency_ms | 8.72 | 12.50 | 24 | 24 | ✅ OK |
| risk_ratio | 4.01 | 0.02 | 24 | 24 | ✅ OK |

### ETHUSDT
...
```

**Legend:**
- ✅ **OK:** Thresholds met
- 🟡 **WARN:** Soft threshold violated (informational)
- 🔴 **FAIL:** Critical threshold violated (blocks PR)

### ACCURACY_SUMMARY.json

**Machine-Readable Format:**
```json
{
  "verdict": "PASS",
  "generated_at_utc": "2025-10-26T14:30:00Z",
  "thresholds": {
    "mape_pct": 15.0,
    "median_delta_bps": 1.5
  },
  "symbols": {
    "BTCUSDT": {
      "edge_bps": {
        "mape_pct": 5.23,
        "median_delta": 0.8200,
        "shadow_count": 24,
        "dryrun_count": 24,
        "status": "OK"
      },
      ...
    }
  },
  "meta": {
    "symbols_count": 2,
    "fail_count": 0,
    "warn_count": 0
  }
}
```

---

## Troubleshooting

### Common FAIL Scenarios

#### 1. Shadow/Dry-Run Logic Divergence

**Symptom:** MAPE > 15% for `edge_bps`

**Causes:**
- Bug in Shadow feed processing
- Incorrect dry-run replay logic
- Timing/slippage differences

**Action:**
1. Check recent changes to `tools/shadow/**` or `tools/dryrun/**`
2. Review ITER_SUMMARY files manually:
   ```bash
   jq '.BTCUSDT.edge_bps' artifacts/shadow/latest/ITER_SUMMARY_001.json
   jq '.BTCUSDT.edge_bps' artifacts/dryrun/latest/ITER_SUMMARY_001.json
   ```
3. Run local comparison with `--verbose` for debugging

**Fix:** Align Shadow/Dry-Run logic

#### 2. Insufficient Data Windows

**Symptom:** Exit code 1, error "Insufficient Shadow windows: 12 < 24"

**Causes:**
- Shadow/Dry-Run run didn't produce enough iterations
- Data too old (filtered by `--max-age-min`)

**Action:**
1. Verify iteration count:
   ```bash
   ls artifacts/shadow/latest/ITER_SUMMARY_*.json | wc -l
   ```
2. Increase iterations in CI workflow or local run
3. Check `--max-age-min` setting if data is stale

**Fix:** Ensure ≥ 24 iterations, fresh data (< 90 min old)

#### 3. Non-Overlapping Time Windows

**Symptom:** All KPIs show `mape_pct: null`, `median_delta: null`

**Causes:**
- Shadow and Dry-Run ran at different times
- No common symbols between runs
- Empty symbol data

**Action:**
1. Check symbol overlap:
   ```bash
   jq 'keys' artifacts/shadow/latest/ITER_SUMMARY_001.json
   jq 'keys' artifacts/dryrun/latest/ITER_SUMMARY_001.json
   ```
2. Verify both runs use same `--symbols` parameter

**Fix:** Run Shadow and Dry-Run with matching symbols and time alignment

#### 4. Threshold Too Strict

**Symptom:** Frequent FAIL verdicts, but manual review shows acceptable accuracy

**Causes:**
- Default thresholds (15% MAPE, 1.5 BPS) too strict for noisy markets
- High volatility periods

**Action:**
1. Review historical MAPE values:
   ```bash
   jq '.symbols.BTCUSDT.edge_bps.mape_pct' reports/analysis/ACCURACY_SUMMARY.json
   ```
2. Check if MAPE consistently near threshold

**Fix (Temporary):**
```bash
MAPE_THRESHOLD=0.20 make accuracy-compare
```

**Fix (Permanent):**
- Update default in `compare_shadow_dryrun.py` (requires approval)
- Document rationale in commit message

### Common WARN Scenarios

#### 1. Acceptable Median Delta Deviation

**Symptom:** Verdict = WARN, `median_delta > 1.5 BPS` for `edge_bps`

**Interpretation:**
- MAPE is OK (< 15%), but absolute delta slightly high
- Often due to small systematic bias

**Action:**
- Review if bias is acceptable (e.g., conservative estimates)
- Check if trend is increasing over time

**Fix:** Usually informational only, no action unless trend worsens

---

## Best Practices

### 1. Run Accuracy Gate Before Merge

**Workflow:**
```bash
# 1. Generate fresh Shadow data
python -m tools.shadow.run_shadow --iterations 24 --mock

# 2. Generate fresh Dry-Run data
python -m tools.dryrun.run_dryrun --iterations 24 --symbols BTCUSDT,ETHUSDT

# 3. Compare
make accuracy-compare

# 4. Review report
cat reports/analysis/ACCURACY_REPORT.md
```

### 2. Monitor Accuracy Trends Over Time

**Collect Metrics:**
```bash
# Archive ACCURACY_SUMMARY.json with PR number
cp reports/analysis/ACCURACY_SUMMARY.json \
   artifacts/accuracy/PR_${PR_NUMBER}_$(date +%Y%m%d).json
```

**Analyze Trends:**
```python
import json
import glob

summaries = [json.load(open(f)) for f in glob.glob("artifacts/accuracy/PR_*.json")]
mape_values = [s["symbols"]["BTCUSDT"]["edge_bps"]["mape_pct"] for s in summaries]

print(f"Mean MAPE: {sum(mape_values) / len(mape_values):.2f}%")
print(f"Max MAPE: {max(mape_values):.2f}%")
```

### 3. Update Thresholds Based on Data

**Review Quarterly:**
1. Collect 100+ PR accuracy results
2. Compute 95th percentile MAPE
3. Set threshold = 95th percentile + 5% buffer

**Example:**
```python
import numpy as np

mape_values = [5.2, 8.1, 12.3, 7.5, 9.0, ...]  # From historical PRs
p95 = np.percentile(mape_values, 95)
new_threshold = p95 * 1.05

print(f"Recommended threshold: {new_threshold:.2f}%")
```

### 4. Document Accuracy Exceptions

**When to Override:**
- Known architectural change (e.g., Shadow uses new feed source)
- Intentional logic update (e.g., improved slippage model)

**Process:**
1. Document reason in PR description
2. Run accuracy comparison locally
3. Attach ACCURACY_REPORT.md to PR
4. Get approval from 2+ reviewers
5. Merge with `--no-verify` (bypass gate) if justified

---

## CLI Reference

### tools/accuracy/compare_shadow_dryrun.py

**Synopsis:**
```bash
python -m tools.accuracy.compare_shadow_dryrun \
  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json" \
  [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--shadow` | str | *required* | Shadow ITER_SUMMARY glob pattern |
| `--dryrun` | str | *required* | Dry-Run ITER_SUMMARY glob pattern |
| `--symbols` | str | `BTCUSDT,ETHUSDT` | Comma-separated symbols |
| `--min-windows` | int | `24` | Minimum data points required |
| `--max-age-min` | int | `90` | Max age of data (minutes) |
| `--mape-threshold` | float | `0.15` | MAPE threshold (fraction) |
| `--median-delta-threshold-bps` | float | `1.5` | Median Δ threshold (BPS) |
| `--out-dir` | Path | `reports/analysis` | Output directory |
| `--verbose` | flag | - | Enable debug logging |

**Examples:**

**Basic Usage:**
```bash
python -m tools.accuracy.compare_shadow_dryrun \
  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json"
```

**Custom Thresholds:**
```bash
python -m tools.accuracy.compare_shadow_dryrun \
  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json" \
  --mape-threshold 0.10 \
  --median-delta-threshold-bps 1.0 \
  --verbose
```

**Specific Symbols:**
```bash
python -m tools.accuracy.compare_shadow_dryrun \
  --shadow "artifacts/shadow/latest/ITER_SUMMARY_*.json" \
  --dryrun "artifacts/dryrun/latest/ITER_SUMMARY_*.json" \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --min-windows 48
```

---

## Makefile Shortcuts

### `make accuracy-compare`

**Description:** Run accuracy comparison with default settings

**Overrides:**
```bash
SYMBOLS=BTCUSDT,ETHUSDT \
MIN_WINDOWS=48 \
MAPE_THRESHOLD=0.10 \
make accuracy-compare
```

### `make accuracy-ci`

**Description:** Run accuracy comparison in strict CI mode (fails on FAIL verdict)

**Behavior:**
- Uses hardcoded production thresholds
- Exits with code 1 on FAIL
- Exits with code 0 on PASS/WARN

**Usage:**
```bash
make accuracy-ci
```

---

## FAQ

### Q: What if Shadow and Dry-Run use different data sources?

**A:** That's expected! The goal is to compare *processing logic*, not data sources. If MAPE is high due to source differences (e.g., live vs replay), adjust thresholds or document the exception.

### Q: Can I disable Accuracy Gate for my PR?

**A:** Yes, but requires justification:
1. Add `[skip-accuracy]` to PR title
2. Document reason in PR description
3. Attach manual ACCURACY_REPORT.md showing divergence is acceptable
4. Get 2+ approvals from maintainers

### Q: How often should thresholds be updated?

**A:** Quarterly review recommended. Collect 100+ PR results, compute 95th percentile MAPE, and update thresholds accordingly.

### Q: What if only one symbol fails?

**A:** Investigate that symbol specifically:
- Check for symbol-specific bugs
- Review recent changes to symbol handling
- Consider per-symbol thresholds (future enhancement)

### Q: Can I run Accuracy Gate locally without CI?

**A:** Yes! Run:
```bash
# 1. Generate data
python -m tools.shadow.run_shadow --iterations 24 --mock
python -m tools.dryrun.run_dryrun --iterations 24

# 2. Compare
make accuracy-compare

# 3. Review
cat reports/analysis/ACCURACY_REPORT.md
```

---

## Sanity Check (One-Shot)

**Purpose:** Fast, reproducible sanity check for Accuracy Gate edge cases and formatting.

**What it checks:**
1. **Empty/Non-overlapping symbols** → Expected: WARN (no data to compare), not FAIL
2. **Max-Age filtering** → Expected: Exit 1 (insufficient windows) or WARN
3. **Formatting (many symbols)** → Expected: Table renders correctly without breaking markdown

### Running Sanity Check

**Basic Run:**
```bash
make accuracy-sanity
```

**Review Report:**
```bash
cat reports/analysis/ACCURACY_SANITY.md
```

**Strict Mode** (fails if any scenario doesn't pass):
```bash
make accuracy-sanity-strict
```

**Custom Parameters:**
```bash
MIN_WINDOWS=48 \
MAX_AGE_MIN=60 \
MAPE_THRESHOLD=0.12 \
MEDIAN_DELTA_BPS=1.0 \
make accuracy-sanity
```

### CI Integration

**Manual Trigger (Sanity Mode):**
```bash
gh workflow run accuracy.yml -f sanity_mode=true
```

This will:
- Run Shadow Mode (24 iterations)
- Run Dry-Run Mode (24 iterations)
- Execute 3 sanity scenarios
- Post PR comment with sanity verdict
- Upload artifacts with scenario-specific reports

**Artifacts Structure:**
```
reports/analysis/
├── ACCURACY_SANITY.md          # Main sanity report
├── sanity_empty/               # Scenario 1 reports
│   ├── ACCURACY_REPORT.md
│   └── ACCURACY_SUMMARY.json
├── sanity_maxage/              # Scenario 2 reports
│   ├── ACCURACY_REPORT.md
│   └── ACCURACY_SUMMARY.json
└── sanity_format/              # Scenario 3 reports
    ├── ACCURACY_REPORT.md
    └── ACCURACY_SUMMARY.json
```

### Interpreting Results

**Scenario 1: Empty/Non-overlap**
- **Expected:** WARN or PASS (no overlapping data means no comparison possible)
- **❌ FAIL if:** Comparison crashes or returns FAIL verdict
- **✅ PASS if:** Comparison returns WARN or PASS

**Scenario 2: Max-Age Filter**
- **Expected:** Exit 1 ("Insufficient windows") or WARN
- **❌ FAIL if:** Comparison doesn't filter old data
- **✅ PASS if:** Old data is filtered and comparison exits gracefully

**Scenario 3: Formatting Check**
- **Expected:** PASS (perfect match), table renders without breaking
- **❌ FAIL if:** Markdown table lines exceed 300 chars or break formatting
- **✅ PASS if:** Table renders correctly with many symbols

**Overall Verdict:**
- **✅ SANITY: PASS** — All scenarios behaved as expected
- **⚠️ SANITY: ATTENTION** — Some scenarios need review (use `--strict` to fail)

### Use Cases

**Before Merging Accuracy Gate Changes:**
```bash
# 1. Run sanity check locally
make accuracy-sanity

# 2. Review report
cat reports/analysis/ACCURACY_SANITY.md

# 3. If all scenarios pass, proceed with PR
```

**After Updating Comparison Logic:**
```bash
# Run strict sanity check
make accuracy-sanity-strict

# This will exit 1 if any scenario fails
```

**CI Self-Check (daily):**
```bash
# Add to cron or scheduled workflow
gh workflow run accuracy.yml -f sanity_mode=true
```

### Troubleshooting

**Scenario 1 Fails (Non-overlap)**

**Symptom:** Scenario 1 returns FAIL instead of WARN

**Causes:**
- Comparison logic doesn't handle missing data gracefully
- FAIL verdict returned when no data to compare

**Action:**
1. Check `compare_shadow_dryrun.py` logic for empty symbol arrays
2. Verify that `mape_pct: null` and `median_delta: null` result in OK status, not FAIL

**Scenario 2 Fails (Max-Age)**

**Symptom:** Scenario 2 doesn't filter old data

**Causes:**
- `max-age-min` parameter not respected
- Timestamp parsing broken

**Action:**
1. Check `parse_iter_files()` logic in `compare_shadow_dryrun.py`
2. Verify timestamp format in ITER_SUMMARY files

**Scenario 3 Fails (Formatting)**

**Symptom:** Scenario 3 reports "Table Formatting: ❌ BROKEN"

**Causes:**
- Markdown table lines exceed 300 chars
- Column alignment broken with many symbols

**Action:**
1. Check `generate_markdown_report()` in `compare_shadow_dryrun.py`
2. Consider truncating long values or adjusting column widths

### Quick Reference

| Command | Purpose | Exit Code |
|---------|---------|-----------|
| `make accuracy-sanity` | Run sanity check (informational) | Always 0 |
| `make accuracy-sanity-strict` | Run sanity check (strict) | 1 if any scenario fails |
| `gh workflow run accuracy.yml -f sanity_mode=true` | CI sanity check | Always 0 (informational) |

---

## Changelog

### v1.0.0 (2025-10-26)

**Initial Release:**
- MAPE and median delta metrics
- Shadow ↔ Dry-Run comparison for 4 KPIs
- CI integration with PR comments
- Makefile shortcuts (`accuracy-compare`, `accuracy-ci`)
- Comprehensive unit tests (12 test cases)

**Thresholds:**
- MAPE: 15% (default)
- Median Δ: 1.5 BPS (default)
- Min windows: 24
- Max age: 90 minutes

---

**Questions? Issues?**

- File bug reports: `issues/accuracy-gate`
- Slack channel: `#accuracy-gate`
- Maintainers: @team-core

---

**Related Guides:**
- [Shadow Mode Guide](SHADOW_MODE_GUIDE.md)
- [Dry-Run Guide](DRYRUN_GUIDE.md)
- [Soak Analyzer Guide](SOAK_ANALYZER_GUIDE.md)

