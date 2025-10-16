# EXTRACT POST-SOAK SNAPSHOT — Implementation Complete

## Overview

Компактная утилита для извлечения JSON-снапшота из результатов soak-тестов.

**Features:**
- ✅ Читает `POST_SOAK_SUMMARY.json` (если есть) или вычисляет из `ITER_SUMMARY_*.json`
- ✅ Генерирует детерминированный JSON с фиксированной структурой
- ✅ Сохраняет как `POST_SOAK_SNAPSHOT.json`
- ✅ Поддержка путей с пробелами
- ✅ Stdlib только (~170 lines)
- ✅ Один файл — легко портировать

---

## Implementation

### 📁 File: `tools/soak/extract_post_soak_snapshot.py`

**Lines:** ~170 lines  
**Dependencies:** stdlib only (`glob`, `json`, `statistics`, `pathlib`, `re`, `sys`)

### 🎯 Key Functions

```python
_load_json_safe(path)           # Safe JSON loading
_iter_files(base_path)          # Find & sort ITER_SUMMARY_*.json
_load_last8(base_path)          # Load last 8 iterations
_stats(values)                  # Compute mean/median
_count_guards(summaries)        # Count guard activations
_kpi_pass(summary)              # Check KPI thresholds
_extract_from_summary(path)     # Extract from POST_SOAK_SUMMARY.json
_extract_from_iters(path)       # Compute from ITER_SUMMARY_*.json
extract_snapshot(path)          # Main extraction function
main()                          # CLI entry point
```

---

## Output Structure

```json
{
  "verdict": "PASS|WARN|FAIL",
  "pass_count_last8": 0,
  "freeze_seen": false,
  "kpi_last8": {
    "risk_ratio": { "mean": 0.0, "median": 0.0 },
    "maker_taker_ratio": { "mean": 0.0, "median": 0.0 },
    "net_bps": { "mean": 0.0, "median": 0.0 },
    "p95_latency_ms": { "mean": 0.0, "median": 0.0 }
  },
  "guards_last8": {
    "oscillation_count": 0,
    "velocity_count": 0,
    "cooldown_count": 0,
    "freeze_events": 0
  }
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | string | PASS/WARN/FAIL based on KPI thresholds |
| `pass_count_last8` | int | Number of passing iterations (last 8) |
| `freeze_seen` | bool | True if freeze_triggered at least once |
| `kpi_last8.*` | object | Mean/median for each KPI metric |
| `guards_last8.*` | int | Guard activation counts |

---

## Usage

### Basic Usage

```bash
# Default path (with space support)
python -m tools.soak.extract_post_soak_snapshot

# Custom path
python -m tools.soak.extract_post_soak_snapshot --path "artifacts/soak/my_run/latest"
```

### Output Locations

**1. stdout:** Single-line JSON (for piping/parsing)
```bash
python -m tools.soak.extract_post_soak_snapshot | jq .
```

**2. File:** `POST_SOAK_SNAPSHOT.json` in same directory
```
artifacts/soak/latest 1/soak/latest/POST_SOAK_SNAPSHOT.json
```

---

## Data Sources

### Priority 1: POST_SOAK_SUMMARY.json (if exists)

Extracts fields directly:
- `verdict`, `pass_count_last8`, `freeze_seen`
- `kpi.*.mean`, `kpi.*.median`
- `guards.oscillation_count`, `guards.velocity_count`, etc.

### Priority 2: ITER_SUMMARY_*.json (fallback)

Computes from last 8 iterations:
1. **KPI values:** Extract from `summary.risk_ratio`, `summary.net_bps`, etc.
2. **Stats:** Calculate `mean()` and `median()` using `statistics` module
3. **Guards:** Count `tuning.oscillation_detected`, `tuning.velocity_violation`, etc.
4. **Pass count:** Apply KPI thresholds to each iteration
5. **Freeze seen:** Check if any `tuning.freeze_triggered == true`
6. **Verdict:** Heuristic based on pass count and freeze

---

## KPI Thresholds

```python
KPI_THRESHOLDS = {
    "risk_ratio": 0.42,         # max
    "maker_taker_ratio": 0.85,  # min
    "net_bps": 2.7,             # min
    "p95_latency_ms": 350,      # max
}
```

**Pass Criteria (per iteration):**
```
risk_ratio ≤ 0.42 AND
maker_taker_ratio ≥ 0.85 AND
net_bps ≥ 2.7 AND
p95_latency_ms ≤ 350
```

---

## Verdict Logic

```python
if pass_count >= 6 and freeze_seen:
    verdict = "PASS"
elif pass_count >= 5:
    verdict = "WARN"
else:
    verdict = "FAIL"
```

---

## Test Results

### Input: 24 test iterations

```bash
$ python -m tools.soak.extract_post_soak_snapshot --path "artifacts/soak/test_run/latest"
```

### Output (stdout):

```json
{"freeze_seen":true,"guards_last8":{"cooldown_count":1,"freeze_events":3,"oscillation_count":0,"velocity_count":1},"kpi_last8":{"maker_taker_ratio":{"mean":0.9,"median":0.9},"net_bps":{"mean":3.138,"median":3.15},"p95_latency_ms":{"mean":305.0,"median":305.0},"risk_ratio":{"mean":0.41,"median":0.41}},"pass_count_last8":6,"verdict":"PASS"}
```

### Output (file): `POST_SOAK_SNAPSHOT.json`

```json
{
  "freeze_seen": true,
  "guards_last8": {
    "cooldown_count": 1,
    "freeze_events": 3,
    "oscillation_count": 0,
    "velocity_count": 1
  },
  "kpi_last8": {
    "maker_taker_ratio": {
      "mean": 0.9,
      "median": 0.9
    },
    "net_bps": {
      "mean": 3.138,
      "median": 3.15
    },
    "p95_latency_ms": {
      "mean": 305.0,
      "median": 305.0
    },
    "risk_ratio": {
      "mean": 0.41,
      "median": 0.41
    }
  },
  "pass_count_last8": 6,
  "verdict": "PASS"
}
```

**Verification:** ✅ Matches analyze_post_soak.py results

---

## Integration Examples

### CI/CD Pipeline

```yaml
- name: Extract soak snapshot
  id: snapshot
  run: |
    python -m tools.soak.extract_post_soak_snapshot --path "artifacts/soak/latest"
    
    # Parse verdict
    VERDICT=$(python -c "import json; print(json.load(open('artifacts/soak/latest/POST_SOAK_SNAPSHOT.json'))['verdict'])")
    echo "VERDICT=$VERDICT" >> $GITHUB_OUTPUT

- name: Check verdict
  if: steps.snapshot.outputs.VERDICT != 'PASS'
  run: |
    echo "Soak test verdict: ${{ steps.snapshot.outputs.VERDICT }}"
    exit 1
```

### Python Script

```python
import json
import subprocess

# Extract snapshot
result = subprocess.run(
    ["python", "-m", "tools.soak.extract_post_soak_snapshot"],
    capture_output=True,
    text=True
)

snapshot = json.loads(result.stdout)

# Check verdict
if snapshot["verdict"] != "PASS":
    print(f"[WARN] Soak verdict: {snapshot['verdict']}")
    print(f"Pass count: {snapshot['pass_count_last8']}/8")
    print(f"Freeze seen: {snapshot['freeze_seen']}")
```

### Shell Script

```bash
#!/bin/bash

# Extract and parse
SNAPSHOT=$(python -m tools.soak.extract_post_soak_snapshot)
VERDICT=$(echo "$SNAPSHOT" | jq -r '.verdict')

if [ "$VERDICT" != "PASS" ]; then
    echo "❌ Soak test failed: $VERDICT"
    exit 1
fi

echo "✅ Soak test passed"
```

---

## Technical Details

### Deterministic JSON

```python
json.dumps(
    snapshot,
    sort_keys=True,          # Stable key ordering
    separators=(",", ":"),   # Compact format
    ensure_ascii=True        # No Unicode issues
)
```

**Benefits:**
- ✅ Reproducible output (no dict randomness)
- ✅ Git-friendly (stable diffs)
- ✅ Easy parsing (consistent structure)

### Path Handling (Spaces)

```python
base_path = Path(args.path).resolve()
pattern = str(base_path / "ITER_SUMMARY_*.json")
files = glob.glob(pattern)
```

Works correctly with:
- `"artifacts/soak/latest 1/soak/latest"`
- `"C:\Users\My Name\mm-bot\artifacts\..."`

### Graceful Degradation

```python
# Missing summary → compute from iterations
if not summary_path.exists():
    snapshot = _extract_from_iters(base_path)

# No data at all → error
if not snapshot:
    print("[ERROR] No data found", file=sys.stderr)
    sys.exit(1)
```

---

## Comparison with analyze_post_soak.py

| Feature | analyze_post_soak.py | extract_post_soak_snapshot.py |
|---------|---------------------|-------------------------------|
| **Purpose** | Full analysis + recommendations | Compact summary for automation |
| **Output** | 3 Markdown files (4+ KB) | 1 JSON file (~300 bytes) |
| **Lines** | ~600 | ~170 |
| **Use case** | Human review, detailed diagnostics | CI/CD, monitoring, alerts |
| **Data** | All 24 iterations + trends | Last 8 iterations only |
| **Reports** | POST_SOAK_AUDIT.md, RECOMMENDATIONS.md, FAILURES.md | POST_SOAK_SNAPSHOT.json |

**Recommendation:** Use both tools together:
1. `analyze_post_soak.py` → Full human-readable analysis
2. `extract_post_soak_snapshot.py` → Machine-parseable summary for automation

---

## Troubleshooting

### Problem: "No data found"

**Solution:** Verify ITER_SUMMARY_*.json files exist:
```bash
ls "artifacts/soak/latest 1/soak/latest"/ITER_SUMMARY_*.json
```

### Problem: "Path does not exist"

**Solution:** Check path spelling and use quotes for spaces:
```bash
python -m tools.soak.extract_post_soak_snapshot --path "my path/with spaces"
```

### Problem: Incorrect KPI values

**Solution:** Verify ITER_SUMMARY_*.json structure:
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
    "cooldown_active": false,
    "velocity_violation": false,
    "oscillation_detected": false,
    "freeze_triggered": false
  }
}
```

---

## Future Enhancements

### Potential Additions

1. **Historical Trending:**
   ```python
   # Compare with previous runs
   --compare "artifacts/soak/baseline/POST_SOAK_SNAPSHOT.json"
   ```

2. **Alert Thresholds:**
   ```python
   # Custom thresholds for WARN/FAIL
   --warn-threshold 5 --fail-threshold 4
   ```

3. **Slack/Telegram Integration:**
   ```python
   # Auto-send snapshot on FAIL
   --notify slack --webhook-url "https://..."
   ```

4. **Prometheus Export:**
   ```python
   # Export metrics for monitoring
   --prometheus-pushgateway "http://localhost:9091"
   ```

---

## Acceptance Criteria

- [x] **Reads POST_SOAK_SUMMARY.json if exists**
- [x] **Computes from ITER_SUMMARY_*.json as fallback**
- [x] **Outputs exact JSON structure (as specified)**
- [x] **Saves to POST_SOAK_SNAPSHOT.json**
- [x] **Deterministic JSON (sort_keys, separators)**
- [x] **Supports paths with spaces**
- [x] **Uses only stdlib (no external deps)**
- [x] **Handles missing data gracefully**
- [x] **~170 lines (compact, readable)**
- [x] **Correct exit codes (0=success, 1=error)**

---

## Status

✅ **IMPLEMENTATION COMPLETE**

**Files Created:**
- `tools/soak/extract_post_soak_snapshot.py` (~170 lines, fully functional)
- `EXTRACT_POST_SOAK_SNAPSHOT_COMPLETE.md` (this document)

**Tested:**
- ✅ Extract from 24 test iterations
- ✅ Verdict: PASS (matches analyze_post_soak.py)
- ✅ KPI stats computed correctly
- ✅ Guards counted correctly
- ✅ Deterministic JSON output
- ✅ File saved successfully

**Ready for:**
- Production use
- CI/CD integration
- Monitoring dashboards
- Automated alerts

---

## Quick Reference

### Command

```bash
python -m tools.soak.extract_post_soak_snapshot [--path PATH]
```

### Inputs

```
artifacts/soak/latest 1/soak/latest/
├── POST_SOAK_SUMMARY.json (optional, priority 1)
├── ITER_SUMMARY_1.json
├── ITER_SUMMARY_2.json
├── ...
└── ITER_SUMMARY_24.json
```

### Outputs

```
stdout:
{"verdict":"PASS","pass_count_last8":6,...}

file:
artifacts/soak/latest 1/soak/latest/POST_SOAK_SNAPSHOT.json
```

### Exit Codes

```
0 = Success
1 = Error (no data found)
```

---

**Author:** AI Assistant  
**Date:** 2025-10-16  
**Version:** 1.0  
**Status:** ✅ Complete

