# Readiness Score - Production Readiness Assessment

**Purpose:** Calculate and report production readiness score based on soak test metrics.

## Overview

The `readiness_score.py` tool analyzes soak test reports and calculates a weighted score across 6 categories:

1. **Edge** (30 pts) - Net BPS performance
2. **Latency** (25 pts) - Order age p95
3. **Taker** (15 pts) - Taker share percentage
4. **Guards** (10 pts) - Reg guard and drift stops
5. **Chaos** (10 pts) - Chaos engineering results
6. **Tests** (10 pts) - Bug bash results

**Total:** 100 points maximum

## Deterministic Output

The tool outputs **deterministic JSON** to stdout with:

- Sorted keys (`sort_keys=True`)
- Compact format (`separators=(",",":")`)
- No whitespace between elements

### Output Schema

```json
{
  "runtime": {
    "utc": "ISO8601 timestamp",
    "version": "semver from VERSION file"
  },
  "score": 0.0,
  "sections": {
    "chaos": 0.0,
    "edge": 0.0,
    "guards": 0.0,
    "latency": 0.0,
    "taker": 0.0,
    "tests": 0.0
  },
  "verdict": "GO" | "HOLD"
}
```

### Verdict Logic

- **GO**: Score exactly 100.0 (perfect)
- **HOLD**: Score < 100.0

## Time Fixation (Deterministic Testing)

The tool supports deterministic timestamps via environment variables:

**Priority order:**
1. `CI_FAKE_UTC` - Primary override for this tool
2. `MM_FREEZE_UTC_ISO` - Fallback (common runtime.py compatibility)
3. Real UTC time from `datetime.now(timezone.utc)`

### Example

```bash
# Deterministic output for testing
CI_FAKE_UTC="1970-01-01T00:00:00Z" python -m tools.release.readiness_score

# Output (compact, no spaces):
{"runtime":{"utc":"1970-01-01T00:00:00Z","version":"0.1.0"},"score":60.0,"sections":{"chaos":10.0,"edge":0.0,"guards":0.0,"latency":25.0,"taker":15.0,"tests":10.0},"verdict":"HOLD"}
```

## Version Reading

The tool reads version from:

1. `VERSION` file in repo root (if exists)
2. Fallback: `"0.1.0"` (development default)

## Usage

### Basic Usage

```bash
# Run with default paths
python -m tools.release.readiness_score

# Specify input/output paths
python -m tools.release.readiness_score \
  --dir artifacts \
  --out-json artifacts/READINESS_SCORE.json
```

### CI/CD Pipeline Usage

```bash
# Generate deterministic readiness score
CI_FAKE_UTC="1970-01-01T00:00:00Z" \
  python -m tools.release.readiness_score > artifacts/reports/readiness.json

# Parse and check verdict
VERDICT=$(jq -r '.verdict' artifacts/reports/readiness.json)
if [ "$VERDICT" != "GO" ]; then
  echo "Production readiness check failed: $VERDICT"
  exit 1
fi
```

## Input Format

The tool reads soak reports from `{dir}/REPORT_SOAK_*.json`:

- Takes last 7 reports by filename order
- Expects standard soak report structure with metrics:
  - `edge_net_bps`
  - `order_age_p95_ms`
  - `taker_share_pct`
  - `reg_guard.reason`
  - `drift.reason`
  - `chaos_result`
  - `bug_bash`

## Output Files

1. **JSON Report** (`{out-json}`):
   - Deterministic JSON structure
   - Atomically written (uses `.tmp` → rename)
   - ASCII-only encoding

2. **Markdown Report** (`{out-json}.md`):
   - Human-readable summary
   - Includes score breakdown table
   - Same basename as JSON, `.md` extension

3. **Stdout**:
   - Deterministic JSON (same as file)
   - Suitable for piping to `jq` or other tools

## Scoring Details

### Edge Score (30 pts)

- Full 30 points at `edge_net_bps >= 2.5`
- Linear scaling below: `30 * (edge_net_bps / 2.5)`

### Latency Score (25 pts)

- Full 25 points at `order_age_p95_ms <= 350`
- Scaled above: `25 * (350 / order_age_p95_ms)`

### Taker Score (15 pts)

- Full 15 points at `taker_share_pct <= 15%`
- Scaled above: `15 * (15 / taker_share_pct)`

### Guards Score (10 pts)

- 10 points per day with no guard breaches
- Scored as: `10 * (ok_days / 7)`
- No breach: `reg_guard.reason == 'NONE'` AND `drift.reason in ['', 'NONE']`

### Chaos Score (10 pts)

- 10 points if all days have `chaos_result == 'OK'`
- 0 points otherwise

### Tests Score (10 pts)

- 10 points if all days have `'OK'` in `bug_bash`
- 0 points otherwise

## Testing

### E2E Tests

**File:** `tests/e2e/test_readiness_score_e2e.py`

```bash
# Run E2E tests
python tests/e2e/test_readiness_score_e2e.py

# With pytest
pytest -q tests/e2e/test_readiness_score_e2e.py
```

**Tests:**
- `test_readiness_json_deterministic()` - Verifies deterministic output with fixed UTC
- `test_readiness_json_format()` - Verifies compact JSON format (no spaces)

## Implementation Notes

- **stdlib-only**: No external dependencies
- **Deterministic**: Output is bit-for-bit reproducible with `CI_FAKE_UTC`
- **Atomic writes**: Uses `.tmp` files + rename for crash safety
- **ASCII-only**: All output is pure ASCII (no Unicode)

## Integration Checklist

- [ ] Set `CI_FAKE_UTC` in CI for reproducible builds
- [ ] Parse JSON output with `jq` or equivalent
- [ ] Check `verdict` field for GO/HOLD decision
- [ ] Monitor `score` field for trends
- [ ] Alert on `score < 90.0` (warning threshold)
- [ ] Fail deployment on `verdict != "GO"`

---

**Status:** Production ready  
**Last Updated:** 2025-10-11

