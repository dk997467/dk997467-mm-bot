# POST-SOAK ANALYZER — Implementation Complete

## Overview

Полнофункциональный анализатор результатов soak-тестов с поддержкой:
- ✅ Путей с пробелами (e.g., `artifacts/soak/latest 1/soak/latest`)
- ✅ Грациозной деградации при отсутствии файлов
- ✅ Детерминированной генерации отчетов (Markdown + JSON)
- ✅ KPI мониторинга и валидации
- ✅ Guard-анализа (oscillation, velocity, cooldown, freeze)
- ✅ Генерации рекомендаций по параметрам
- ✅ ASCII sparklines для визуализации
- ✅ Только stdlib (без внешних зависимостей)

---

## Implementation

### 📁 File: `tools/soak/analyze_post_soak.py`

**Lines:** ~600+ lines  
**Dependencies:** stdlib only (`glob`, `json`, `statistics`, `datetime`, `pathlib`, `re`, `itertools`, `sys`)

### 🎯 Key Features

#### 1. Data Loading (`load_iter_summaries`)
- Scans `ITER_SUMMARY_*.json` files with glob
- Handles paths with spaces correctly
- Sorts by iteration number
- Graceful error handling

#### 2. KPI Analysis (`check_kpi`, `compute_last8_stats`)
- **Hard Thresholds:**
  - `risk_ratio` ≤ 0.42
  - `maker_taker_ratio` ≥ 0.85
  - `net_bps` ≥ 2.7
  - `p95_latency_ms` ≤ 350
- **PASS Criteria:** Last 8 iterations, ≥6 pass all KPI + freeze_triggered at least once

#### 3. Guard Analysis (`scan_guards`)
- Counts oscillation, velocity, cooldown activations
- Tracks freeze events with reasons
- Detects stability patterns

#### 4. Signature Analysis (`detect_signatures`)
- Extracts runtime signatures/state hashes
- Detects A→B→A oscillation loops (3-window)
- Reports unique configurations

#### 5. Anomaly Detection (`detect_anomalies`)
- **Latency spikes:** > p95_threshold + 50ms
- **Risk jumps:** Δrisk > +0.15 vs previous iteration
- **Maker/Taker drops:** < 0.75

#### 6. Parameter Recommendations (`make_deltas`)
Deterministic delta logic based on KPI violations:

```python
# Risk too high
risk > 0.42 → base_spread_bps += 0.03, min_interval_ms += 35

# Maker/Taker too low
maker_taker < 0.85 → base_spread_bps += 0.015, replace_rate *= 0.85

# Latency too high
p95_latency > 350 → concurrency_limit *= 0.85, tail_age_ms += 75

# Oscillation detected
oscillation > 1 → cooldown_iters += 1, max_delta_per_hour *= 0.8

# Velocity violation
velocity > 0 → max_delta_per_hour *= 0.9

# Net BPS low BUT risk good
net < 2.7 && risk ≤ 0.40 → base_spread_bps -= 0.01, min_interval_ms -= 20
```

#### 7. Visualization (`render_ascii_sparkline`)
- ASCII sparklines using block characters: `▁▂▃▄▅▆▇█`
- Width-adjustable (default: 40 chars)
- Handles empty/constant sequences

---

## Generated Reports

### 1. `POST_SOAK_AUDIT.md`

Full analysis with:
- **Overview:** Total iterations, time range, KPI_GATE verdict
- **Iteration Matrix:** CSV table with all KPI + guard flags
- **KPI Trends:** Statistics table (mean, median, min, max, stdev)
- **Visual Trends:** ASCII sparklines for risk_ratio and net_bps
- **Guards & Stability:** Activation counts and freeze events
- **Runtime Signatures:** Unique configs and A→B→A loops
- **Edge Decomposition:** Driver breakdown (if available)
- **Anomalies:** Detected issues with iteration references
- **Verdict & Actions:** PASS/WARN/FAIL + freeze decision + prod gate

### 2. `RECOMMENDATIONS.md`

Parameter tuning guidance:
- **KPI Summary:** Last 8 iterations stats
- **Proposed Deltas:** Table with current → proposed + rationale
- **Freeze Decision:** READY_TO_FREEZE ✅ or HOLD ❌

### 3. `FAILURES.md` (only if FAIL verdict)

Detailed failure analysis:
- **KPI Violations:** Per-iteration breakdown with references
- **Anomalies:** All detected issues

---

## Usage

### Basic Usage

```bash
# Default path (with space)
python -m tools.soak.analyze_post_soak

# Custom path
python -m tools.soak.analyze_post_soak --path "artifacts/soak/my_run/latest"
```

### Exit Codes

```
0 = PASS or WARN
1 = FAIL or critical error (no data)
```

### Example Output

```
[analyze_post_soak] Analyzing soak results from: C:\Users\...\artifacts\soak\latest 1\soak\latest
[analyze_post_soak] Loaded 24 iteration summaries
[analyze_post_soak] Verdict: PASS (pass_count=7/8, freeze=True)
[analyze_post_soak] Generating reports...
[analyze_post_soak] ✅ Written: C:\...\POST_SOAK_AUDIT.md
[analyze_post_soak] ✅ Written: C:\...\RECOMMENDATIONS.md

================================================================================
POST_SOAK: PASS (pass_count=7/8, freeze=True)
================================================================================
```

---

## Example Reports

### Iteration Matrix (CSV Block)

```csv
iteration,timestamp,risk_ratio,maker_taker,net_bps,p95_ms,applied,deltas_count,cooldown,velocity,oscillation,freeze,signature
1,2025-10-16T12:00:00,0.380,0.92,3.15,280,True,3,False,False,False,False,a1b2c3d4 # PASS
2,2025-10-16T12:05:00,0.390,0.90,3.05,295,True,2,False,False,False,False,e5f6g7h8 # PASS
3,2025-10-16T12:10:00,0.450,0.88,2.80,310,False,0,True,False,False,False,a1b2c3d4 # FAIL
...
```

### KPI Trends Table

```
Metric               Mean       Median     Min        Max        StDev      Threshold    Pass?
------------------------------------------------------------------------------------------------------
Risk Ratio           0.395      0.390      0.350      0.450      0.028      <= 0.42      ✅
Maker/Taker          0.893      0.900      0.850      0.920      0.022      >= 0.85      ✅
Net BPS              3.021      3.050      2.700      3.150      0.145      >= 2.7       ✅
P95 Latency (ms)     298.125    295.000    280.000    350.000    21.342     <= 350       ✅
```

### ASCII Sparklines

```
Risk Ratio:  ▃▄▅▇█▇▆▅▄▃▃▄▅▆▇▇▆▅▄▃▂▂▃▄
Net BPS:     ▆▇█▇▆▅▄▃▄▅▆▇█▇▆▅▄▅▆▇█▇▆▅
```

### Parameter Deltas

```
Parameter                 Current      Proposed Delta       Rationale
----------------------------------------------------------------------------------------------------
base_spread_bps           unknown      +0.015               maker_taker_ratio=0.893 < 0.85
replace_rate_per_min      unknown      *0.85                Reduce replace rate to stay on book longer
max_delta_per_hour        unknown      *0.9                 velocity_violation=2 times
```

---

## Technical Details

### Path Handling (Spaces)

```python
# Uses Path + glob for robustness
pattern = str(base_path / "ITER_SUMMARY_*.json")
files = glob.glob(pattern)

# Works correctly with:
# - "artifacts/soak/latest 1/soak/latest"
# - "C:\Users\My Name\mm-bot\artifacts\..."
```

### Graceful Degradation

```python
# Missing files → warn, don't crash
if not summaries:
    print("[ERROR] No ITER_SUMMARY_*.json files found!", file=sys.stderr)
    return "FAIL (no_data)", 1

# Missing fields → default values
risk = s.get("risk_ratio", 0)  # Default to 0
latency = s.get("p95_latency_ms", 9999)  # Default to high value
```

### Deterministic Output

All reports use:
- **Markdown:** UTF-8 encoding, consistent formatting
- **JSON:** (if added) `sort_keys=True`, `separators=(',', ':')`, `ensure_ascii=True`

---

## Integration with CI/CD

### GitHub Actions Step

```yaml
- name: Analyze soak results
  id: post-soak
  if: always()
  run: |
    python -m tools.soak.analyze_post_soak --path "artifacts/soak/latest"
    echo "EXIT_CODE=$?" >> $GITHUB_OUTPUT

- name: Check soak verdict
  if: always()
  run: |
    if [ "${{ steps.post-soak.outputs.EXIT_CODE }}" != "0" ]; then
      echo "❌ Soak test FAILED - review POST_SOAK_AUDIT.md"
      exit 1
    fi
```

### Artifact Upload

```yaml
- name: Upload soak analysis
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: soak-analysis-${{ github.run_id }}
    path: |
      artifacts/soak/latest/POST_SOAK_AUDIT.md
      artifacts/soak/latest/RECOMMENDATIONS.md
      artifacts/soak/latest/FAILURES.md
    retention-days: 30
```

---

## Testing

### Unit Tests (Recommended)

Create `tests/soak/test_analyze_post_soak.py`:

```python
import pytest
from pathlib import Path
from tools.soak.analyze_post_soak import (
    check_kpi, compute_last8_stats, scan_guards,
    detect_signatures, render_ascii_sparkline
)

def test_check_kpi_pass():
    summary = {
        "risk_ratio": 0.35,
        "maker_taker_ratio": 0.90,
        "net_bps": 3.0,
        "p95_latency_ms": 300,
    }
    result = check_kpi({"summary": summary})
    assert result["all_pass"] is True

def test_check_kpi_fail_risk():
    summary = {
        "risk_ratio": 0.50,  # > 0.42
        "maker_taker_ratio": 0.90,
        "net_bps": 3.0,
        "p95_latency_ms": 300,
    }
    result = check_kpi({"summary": summary})
    assert result["all_pass"] is False
    assert result["risk_ratio"] is False

def test_ascii_sparkline():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    sparkline = render_ascii_sparkline(values, width=9)
    assert len(sparkline) == 9
    assert "▁" in sparkline
    assert "█" in sparkline
```

### Integration Test (Manual)

1. Run mini-soak:
   ```bash
   python -m tools.soak.run --iterations 8 --mock --auto-tune
   ```

2. Analyze results:
   ```bash
   python -m tools.soak.analyze_post_soak --path artifacts/soak/latest
   ```

3. Verify reports generated:
   ```bash
   ls -l artifacts/soak/latest/POST_SOAK_AUDIT.md
   ls -l artifacts/soak/latest/RECOMMENDATIONS.md
   ```

---

## Troubleshooting

### Problem: "No ITER_SUMMARY_*.json files found"

**Solution:** Verify path is correct and files exist:
```bash
ls "artifacts/soak/latest 1/soak/latest"/ITER_SUMMARY_*.json
```

### Problem: "Path does not exist"

**Solution:** Check for typos in path, especially with spaces:
```bash
# Use quotes for paths with spaces
python -m tools.soak.analyze_post_soak --path "my path/with spaces"
```

### Problem: Missing KPI fields

**Solution:** Analyzer uses defaults, but verify `ITER_SUMMARY_*.json` structure:
```json
{
  "iteration": 1,
  "summary": {
    "risk_ratio": 0.35,
    "maker_taker_ratio": 0.90,
    "net_bps": 3.0,
    "p95_latency_ms": 280
  },
  "tuning": {
    "applied": true,
    "proposed_deltas": {},
    "cooldown_active": false,
    "velocity_violation": false,
    "oscillation_detected": false,
    "freeze_triggered": false,
    "signature": "a1b2c3d4"
  }
}
```

---

## Future Enhancements

### Potential Additions

1. **JSON Output:** Add `--json` flag for machine-readable output
2. **Interactive Mode:** `--interactive` for parameter tuning wizard
3. **Historical Comparison:** Compare current run vs baseline
4. **Slack/Telegram Notifications:** Auto-send reports on FAIL
5. **HTML Reports:** Rich visualizations with charts
6. **Trend Analysis:** Multi-run comparison over time

### Example: JSON Output

```python
# Add to main()
if args.json:
    json_report = {
        "verdict": verdict,
        "exit_code": exit_code,
        "stats": stats,
        "guards": guards,
        "deltas": deltas,
        "freeze_decision": freeze_decision,
    }
    with open(base_path / "POST_SOAK_REPORT.json", "w") as f:
        json.dump(json_report, f, indent=2, sort_keys=True)
```

---

## Acceptance Criteria

- [x] **Loads ITER_SUMMARY_*.json from path with spaces**
- [x] **Computes KPI stats for last 8 iterations**
- [x] **Detects guard activations (oscillation, velocity, cooldown, freeze)**
- [x] **Generates deterministic parameter deltas**
- [x] **Detects A→B→A signature loops**
- [x] **Identifies anomalies (latency spikes, risk jumps, maker/taker drops)**
- [x] **Renders ASCII sparklines for visualization**
- [x] **Generates POST_SOAK_AUDIT.md with full analysis**
- [x] **Generates RECOMMENDATIONS.md with deltas**
- [x] **Generates FAILURES.md (only on FAIL verdict)**
- [x] **Returns correct exit codes (0=PASS/WARN, 1=FAIL)**
- [x] **Uses only stdlib (no external dependencies)**
- [x] **Handles missing files gracefully (degradation)**

---

## Status

✅ **IMPLEMENTATION COMPLETE**

**Files Created:**
- `tools/soak/analyze_post_soak.py` (~600 lines, fully functional)
- `POST_SOAK_ANALYZER_COMPLETE.md` (this document)

**Ready for:**
- Integration testing with real soak data
- CI/CD pipeline integration
- Production use

---

## Quick Reference

### Command

```bash
python -m tools.soak.analyze_post_soak [--path PATH]
```

### Inputs

```
artifacts/soak/latest 1/soak/latest/
├── ITER_SUMMARY_1.json
├── ITER_SUMMARY_2.json
├── ...
├── ITER_SUMMARY_24.json
├── TUNING_REPORT.json (optional)
├── TUNING_STATE.json (optional)
└── ../artifacts/
    ├── EDGE_REPORT.json (optional)
    └── KPI_GATE.json (optional)
```

### Outputs

```
artifacts/soak/latest 1/soak/latest/
├── POST_SOAK_AUDIT.md       (always)
├── RECOMMENDATIONS.md        (always)
└── FAILURES.md               (only if FAIL)
```

### Exit Codes

```
0 = PASS or WARN
1 = FAIL or error
```

---

**Author:** AI Assistant  
**Date:** 2025-10-16  
**Version:** 1.0  
**Status:** ✅ Complete

