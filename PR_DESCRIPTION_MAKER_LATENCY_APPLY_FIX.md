# feat(soak): Fix mock maker/taker fallback + USE_MOCK env var

## 🎯 Summary

Phase 1 of comprehensive soak reliability improvements: Fix mock mode to properly use maker/taker ratio = 0.80 (was falling through to 0.60) and enable optimization logic testing.

## 📊 What's Fixed

### 1. Mock Fallback Value (Commit d4879db)
**File:** `tools/soak/iter_watcher.py`

```python
# Before:
summary["maker_taker_ratio"] = 0.9  # Too high, no room for optimization

# After:
summary["maker_taker_ratio"] = 0.80  # Shows clear gap to target (0.85)
```

**Impact:**
- Allows maker/taker optimization logic to trigger (threshold: 0.85)
- More realistic testing of optimization deltas
- Better smoke test coverage

### 2. USE_MOCK Environment Variable (Commit c116514)
**File:** `tools/soak/run.py`

**Issue:**
- `run.py` accepts `--mock` flag but doesn't set `USE_MOCK` env var
- `iter_watcher.py` checks `os.getenv("USE_MOCK")` for mock mode
- Result: maker_taker falls through to general fallback (0.60) instead of mock (0.80)

**Fix:**
```python
# At start of mini-soak loop:
if args.mock:
    os.environ["USE_MOCK"] = "1"
    print("| soak | MOCK_MODE | USE_MOCK=1 |")
```

**Impact:**
- Mock runs now correctly use `maker_taker_ratio = 0.80` ✅
- Consistent behavior across all mock runs
- Proper testing of optimization thresholds

## ✅ Verification

```bash
# Run mock mini-soak
$ python -m tools.soak.run --iterations 2 --auto-tune --mock

# Output shows:
| soak | MOCK_MODE | USE_MOCK=1 (for iter_watcher maker/taker calculation) |

# Check ITER_SUMMARY:
$ python -c "import json; print(json.load(open('artifacts/soak/latest/ITER_SUMMARY_1.json'))['summary']['maker_taker_ratio'])"
0.8  # ✅ Correct!

# Source is mock_default (not fallback):
$ python -c "import json; print(json.load(open('artifacts/soak/latest/ITER_SUMMARY_1.json'))['summary']['maker_taker_source'])"
mock_default  # ✅ Correct!
```

## 📁 Files Changed

- `tools/soak/iter_watcher.py` — Mock fallback: 0.90 → 0.80
- `tools/soak/run.py` — Set USE_MOCK env var when --mock flag is used
- `SOAK_MAKER_LATENCY_APPLY_FIX_SUMMARY.md` (NEW) — Comprehensive documentation

## 🧪 Testing

**Smoke Test (2 iterations):**
```bash
python -m tools.soak.run --iterations 2 --auto-tune --mock
```
- ✅ USE_MOCK env var set correctly
- ✅ maker_taker_ratio = 0.80
- ✅ maker_taker_source = "mock_default"
- ✅ All artifacts generated correctly

## 🚀 What's Complete (from previous PRs)

This PR builds on top of already-merged infrastructure:
- ✅ Apply pipeline (`apply_deltas_with_tracking`)
- ✅ Maker/taker real calculation with fills data
- ✅ Maker/taker optimization logic (risk ≤ 0.40, mt < 0.85)
- ✅ Latency buffer (soft: 330-360ms, hard: >360ms)
- ✅ Delta verification with `--json` flag
- ✅ Soak gate with delta quality checks
- ✅ Pipeline scripts (`run_mini_soak_24.sh/ps1`)
- ✅ Tests (`test_reliability_pipeline.py`)

## 🚧 What's Pending (future PRs)

**Separated for safety and review clarity:**
1. **Live-apply integration in run.py** — Critical path, needs careful testing
2. **Test updates** — Add tracking field assertions
3. **24-iteration validation** — Full pipeline run

**Rationale for Phased Approach:**
- Safety: Live-apply is critical path
- Testing: Needs isolated validation
- Review: Easier to review smaller changes
- Rollback: Easier to revert if issues

## 📖 Related Documentation

- `SOAK_MAKER_LATENCY_APPLY_FIX_SUMMARY.md` — Full implementation details
- `MAKER_TAKER_LATENCY_COMPLETE.md` — Previous implementation guide
- `SOAK_RELIABILITY_PHASES_2_4_COMPLETE.md` — Overall roadmap

## ✅ Checklist

- [x] Code changes implemented
- [x] Smoke tests passing
- [x] Documentation updated
- [x] Verification commands tested
- [x] All commits pushed
- [x] Ready for review

---

**Branch:** `feat/soak-maker-latency-apply-fix`  
**Base:** `feat/soak-ci-chaos-release-toolkit`  
**Commits:** 3 (d4879db, c116514, 46d10e3)

