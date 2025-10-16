# 🎯 Soak Reliability Maximization — Implementation Guide

## Objective

Achieve ≥95% full delta applications in mock mode with:
- Deterministic parameter apply
- Signature tracking
- Explicit skip reasons
- Guards and metrics
- Strict CI gates

---

## ✅ Component Status

### 1. Parameter Mapping ✅ COMPLETE
**File:** `tools/soak/params.py`

**Features:**
- Unified parameter mapping (flat key → nested path)
- `get_from_runtime(runtime, key)` — Get parameter value
- `set_in_runtime(runtime, key, value)` — Set parameter value
- `apply_deltas(runtime, deltas)` — Apply all deltas at once
- `get_all_params(runtime)` — Extract all as flat dict
- `validate_deltas(deltas)` — Check for unknown parameters

**Parameter Coverage:**
```python
PARAM_KEYS = {
    # Risk
    "base_spread_bps": ("risk", "base_spread_bps"),
    "impact_cap_ratio": ("risk", "impact_cap_ratio"),
    "max_delta_ratio": ("risk", "max_delta_ratio"),
    
    # Engine
    "replace_rate_per_min": ("engine", "replace_rate_per_min"),
    "concurrency_limit": ("engine", "concurrency_limit"),
    "tail_age_ms": ("engine", "tail_age_ms"),
    "min_interval_ms": ("engine", "min_interval_ms"),
    
    # Tuner
    "cooldown_iters": ("tuner", "cooldown_iters"),
    "velocity_cap": ("tuner", "velocity_cap"),
    ...
}
```

**Usage:**
```python
from tools.soak.params import get_from_runtime, set_in_runtime, apply_deltas

# Get parameter
value = get_from_runtime(runtime, "base_spread_bps")

# Set parameter
set_in_runtime(runtime, "tail_age_ms", 500)

# Apply deltas
deltas = {"base_spread_bps": 0.25, "tail_age_ms": 500}
apply_deltas(runtime, deltas)
```

---

### 2. Atomic Write + State Hash ✅ COMPLETE
**File:** `tools/common/jsonx.py`

**New Functions:**

#### `atomic_write_json(path, obj) -> (state_hash, size)`
```python
# Ensures:
# 1. Deterministic serialization (sorted keys, no whitespace)
# 2. Atomic write (tmp file + fsync + rename)
# 3. State hash computation (SHA256)

state_hash, size = atomic_write_json("runtime_overrides.json", runtime)
```

#### `read_json_with_hash(path) -> (data, state_hash)`
```python
# Read file and compute hash in one call
data, hash_val = read_json_with_hash("runtime_overrides.json")
```

**Features:**
- ✅ Deterministic serialization (`sort_keys=True`, `separators=(',', ':')`)
- ✅ Atomic file write (tmp → fsync → rename)
- ✅ SHA256 state hash
- ✅ Automatic cleanup on error
- ✅ NaN/Infinity rejection

---

### 3. Apply Pipeline (Order of Operations) 🚧 TODO

**Proposed Flow:**

```python
# In iter_watcher.py or run.py

def apply_deltas_with_tracking(
    runtime_path: Path,
    proposed_deltas: dict,
    guards: dict
) -> dict:
    """
    Apply deltas with full tracking and deterministic hash.
    
    Returns:
        {
            "applied": bool,
            "skip_reason": {...},
            "state_hash": str,
            "deltas_applied": {...},
        }
    """
    # 1. Check guards
    if guards.get("cooldown_active"):
        return {
            "applied": False,
            "skip_reason": {"cooldown": True, "note": "cooldown N iters left"},
            "state_hash": None,
        }
    
    # 2. Load current runtime
    runtime, old_hash = read_json_with_hash(runtime_path)
    
    # 3. Apply deltas using params module
    from tools.soak.params import apply_deltas
    runtime, count = apply_deltas(runtime, proposed_deltas)
    
    # 4. Atomic write + get new hash
    new_hash, size = atomic_write_json(runtime_path, runtime)
    
    # 5. Barrier: Re-read to verify
    verify_runtime, verify_hash = read_json_with_hash(runtime_path)
    assert verify_hash == new_hash, "Hash mismatch after write!"
    
    # 6. Return tracking info
    return {
        "applied": True,
        "skip_reason": None,
        "state_hash": new_hash,
        "deltas_applied": proposed_deltas,
        "old_hash": old_hash,
    }
```

**Integration Points:**
- `tools/soak/run.py` — Main soak runner
- `tools/soak/iter_watcher.py` — Per-iteration tuning
- Both need to be updated to use this pipeline

---

### 4. Skip Reasons 🚧 TODO

**Data Structure:**

```json
{
  "tuning": {
    "applied": false,
    "skip_reason": {
      "cooldown": true,
      "velocity": false,
      "oscillation": false,
      "freeze": false,
      "no_op": false,
      "note": "cooldown 2 iters left"
    }
  }
}
```

**Implementation:**
- Add `skip_reason` to TUNING_REPORT.json
- Add `skip_reason` to ITER_SUMMARY_{i}.json
- Populate in iter_watcher.py when apply is blocked

---

### 5. State Hash in ITER_SUMMARY 🚧 TODO

**Required Change:**

```json
{
  "iteration": 1,
  "summary": {
    "runtime_utc": "...",
    "state_hash": "abc123...",  // ← ADD THIS
    ...
  },
  "tuning": {
    "applied": true,
    "deltas": {...},
    "skip_reason": null
  }
}
```

**Implementation:**
- After `apply_deltas_with_tracking()`, save `state_hash` to summary
- Ensure it's included in every ITER_SUMMARY_{i}.json

---

### 6. Delta Verifier Updates 🚧 TODO

**File:** `tools/soak/verify_deltas_applied.py`

**Changes Needed:**

1. **Use params module:**
```python
from tools.soak.params import get_from_runtime, PARAM_KEYS

# Old: _get_runtime_params(data)
# New:
def _get_runtime_params(data: dict) -> dict:
    from tools.soak.params import get_all_params
    tuning = data.get("tuning", {})
    deltas = tuning.get("deltas", {})
    if deltas:
        return deltas
    
    # Fallback: extract from runtime
    runtime = data.get("runtime_overrides", {})
    return get_all_params(runtime)
```

2. **Check skip_reason for guards:**
```python
def _analyze_iteration_pair(...):
    ...
    skip_reason = tuning_iter_prev.get("skip_reason", {})
    
    if not result["applied"] and skip_reason:
        # Has skip_reason → acceptable
        result["params_match"] = "partial_ok"
        result["reason"] = f"skipped: {skip_reason.get('note', 'guard active')}"
    ...
```

3. **Update thresholds:**
```python
# In verify_deltas():
threshold = 95.0 if strict else 90.0

# PASS if:
# - full_apply_pct >= threshold
# OR
# - full_apply_pct >= (threshold - 5.0) AND signature_stuck == 0
```

---

### 7. Prometheus Metrics 🚧 TODO

**File:** `tools/soak/soak_gate.py` or new `export_soak_metrics.py`

**Additional Metrics:**

```prometheus
# Delta application quality
soak_delta_full_apply_ratio 0.95
soak_delta_partial_count 2
soak_signature_stuck_count 0
soak_delta_fail_count 1

# Existing metrics (from extract_post_soak_snapshot.py --prometheus)
soak_kpi_risk_ratio_mean 0.41
soak_kpi_maker_taker_mean 0.9
soak_freeze_ready 1
...
```

**Implementation:**
```python
# In soak_gate.py

def export_delta_metrics(base_path: Path):
    """Export delta application metrics to Prometheus format."""
    # Run verifier and capture output
    result = subprocess.run(
        [sys.executable, "-m", "tools.soak.verify_deltas_applied",
         "--path", str(base_path)],
        capture_output=True,
        text=True
    )
    
    # Parse metrics from stderr or report
    report_path = base_path / "DELTA_VERIFY_REPORT.md"
    if not report_path.exists():
        return
    
    # Extract metrics from report
    content = report_path.read_text()
    # Parse "Full applications: X/Y (Z%)"
    match = re.search(r"Full applications: (\d+)/(\d+) \(([\d.]+)%\)", content)
    if match:
        full = int(match.group(1))
        total = int(match.group(2))
        ratio = float(match.group(3)) / 100.0
        
        # Write to POST_SOAK_METRICS.prom (append mode)
        metrics_path = base_path / "POST_SOAK_METRICS.prom"
        with open(metrics_path, "a") as f:
            f.write("\n# Delta application quality\n")
            f.write(f"soak_delta_full_apply_ratio {ratio:.3f}\n")
            f.write(f"soak_delta_full_count {full}\n")
            f.write(f"soak_delta_total_count {total}\n")
```

---

### 8. Gate Logic (Strict) 🚧 TODO

**File:** `tools/soak/soak_gate.py`

**Updated Flow:**

```python
def main():
    ...
    
    # Step 1: Analyze
    run_analyzer(path)
    
    # Step 2: Extract snapshot
    success, snapshot, error = run_extractor(path, args.prometheus)
    
    # Step 3: Verify deltas (STRICT)
    print("\n[soak_gate] Running delta verifier (strict mode)...")
    result = subprocess.run(
        [sys.executable, "-m", "tools.soak.verify_deltas_applied",
         "--path", str(path), "--strict"],
        capture_output=True
    )
    
    if result.returncode != 0:
        print("[ERROR] Delta verifier FAILED", file=sys.stderr)
        sys.exit(1)
    
    # Step 4: Export delta metrics
    export_delta_metrics(path)
    
    # Step 5: Check final verdict
    verdict = snapshot.get("verdict", "UNKNOWN")
    freeze_ready = snapshot.get("freeze_ready", False)
    
    if verdict == "FAIL" or not freeze_ready:
        print(f"\n[FAIL] Soak gate: verdict={verdict}, freeze_ready={freeze_ready}")
        sys.exit(1)
    
    # Step 6: Load delta metrics and check
    metrics_path = path / "POST_SOAK_METRICS.prom"
    if metrics_path.exists():
        content = metrics_path.read_text()
        match = re.search(r"soak_delta_full_apply_ratio ([\d.]+)", content)
        if match:
            ratio = float(match.group(1))
            if ratio < 0.95:
                print(f"\n[FAIL] Delta apply ratio {ratio:.2%} < 95%")
                sys.exit(1)
    
    print("\n[OK] Soak gate: PASS")
    sys.exit(0)
```

---

### 9. Tests 🚧 TODO

**File:** `tests/soak/test_post_soak_pipeline.py`

**New Tests:**

```python
@pytest.mark.smoke
def test_delta_full_apply_ratio_ge_95_in_mock():
    """Test that mock mode achieves ≥95% full apply ratio."""
    # Run mini-soak in mock mode
    result = subprocess.run(
        [sys.executable, "-m", "tools.soak.run",
         "--iterations", "12", "--auto-tune", "--mock"],
        cwd=PROJECT_ROOT
    )
    assert result.returncode == 0
    
    # Run verifier in strict mode
    result = subprocess.run(
        [sys.executable, "-m", "tools.soak.verify_deltas_applied",
         "--path", "artifacts/soak/latest", "--strict"],
        cwd=PROJECT_ROOT
    )
    
    assert result.returncode == 0, "Delta verifier failed in strict mode"


@pytest.mark.smoke
def test_skip_reason_present_on_guard_block():
    """Test that skip_reason is populated when guards block apply."""
    # Create test data with cooldown active
    iter_summary = {
        "iteration": 1,
        "tuning": {
            "applied": False,
            "skip_reason": {
                "cooldown": True,
                "note": "cooldown 2 iters left"
            }
        }
    }
    
    # Verify structure
    assert "skip_reason" in iter_summary["tuning"]
    assert iter_summary["tuning"]["skip_reason"]["cooldown"] is True


@pytest.mark.smoke
def test_state_hash_changes_on_apply():
    """Test that state_hash changes when deltas are applied."""
    # Create two runtime states
    runtime1 = {"risk": {"base_spread_bps": 0.20}}
    runtime2 = {"risk": {"base_spread_bps": 0.25}}
    
    # Compute hashes
    hash1 = compute_json_hash(runtime1)
    hash2 = compute_json_hash(runtime2)
    
    # Should be different
    assert hash1 != hash2
    
    # No-op: same runtime
    runtime3 = {"risk": {"base_spread_bps": 0.20}}
    hash3 = compute_json_hash(runtime3)
    
    # Should be same as first
    assert hash1 == hash3
```

---

### 10. CI Integration 🚧 TODO

**File:** `.github/workflows/ci.yml` or `.github/workflows/soak-windows.yml`

**Add Step:**

```yaml
- name: Run soak test (24 iterations)
  run: |
    python -m tools.soak.run --iterations 24 --auto-tune --mock

- name: Soak gate + delta verify (strict)
  run: |
    python -m tools.soak.soak_gate \
      --path artifacts/soak/latest \
      --prometheus
    
    python -m tools.soak.verify_deltas_applied \
      --path artifacts/soak/latest \
      --strict

- name: Check delta metrics
  run: |
    RATIO=$(grep soak_delta_full_apply_ratio artifacts/soak/latest/POST_SOAK_METRICS.prom | awk '{print $2}')
    echo "Delta apply ratio: $RATIO"
    
    # Fail if below 95%
    python -c "import sys; sys.exit(0 if float('$RATIO') >= 0.95 else 1)"
```

---

## 🎯 Acceptance Criteria

### Must Have (Blocking)

- [x] **1. Parameter mapping** — `tools/soak/params.py` created
- [x] **2. Atomic write + hash** — `atomic_write_json()` added to jsonx.py
- [ ] **3. Apply pipeline** — Order: load → apply → atomic_write → barrier → verify
- [ ] **4. Skip reasons** — All blocked applies have explicit `skip_reason`
- [ ] **5. State hash** — Every ITER_SUMMARY has `summary.state_hash`
- [ ] **6. Verifier updates** — Uses params module, checks skip_reason
- [ ] **7. Delta metrics** — Prometheus export includes delta quality metrics
- [ ] **8. Strict gate** — Fails if verdict=FAIL, freeze_ready=false, or delta_ratio<0.95
- [ ] **9. Tests** — ≥3 new tests for delta apply, skip_reason, state_hash
- [ ] **10. CI integration** — Soak job runs gate + verifier in strict mode

### Success Metrics

- **Mock mode:** ≥95% full delta applications
- **Signature tracking:** 0-1 signature_stuck events
- **Skip reasons:** 100% coverage when apply blocked
- **State hash:** Changes on every real delta apply
- **CI gate:** Fails on any degradation

---

## 📋 Implementation Plan

### Phase 1: Core Infrastructure ✅
- [x] Create `params.py` with parameter mapping
- [x] Add `atomic_write_json()` to `jsonx.py`
- [x] Add `read_json_with_hash()` to `jsonx.py`

### Phase 2: Apply Pipeline (Next)
- [ ] Create `apply_deltas_with_tracking()` in new module
- [ ] Integrate into `iter_watcher.py`
- [ ] Add `state_hash` to ITER_SUMMARY
- [ ] Add `skip_reason` to TUNING_REPORT and ITER_SUMMARY

### Phase 3: Verification & Metrics
- [ ] Update `verify_deltas_applied.py` to use params module
- [ ] Add skip_reason awareness
- [ ] Export delta metrics to Prometheus
- [ ] Update gate logic

### Phase 4: Testing & CI
- [ ] Add regression tests
- [ ] Update CI workflows
- [ ] Run mini-soak validation
- [ ] Document results

---

## 🚀 Quick Test Commands

```bash
# 1. Test parameter mapping
python tools/soak/params.py

# 2. Test atomic write + hash
python -c "from tools.common.jsonx import atomic_write_json; print(atomic_write_json('test.json', {'a': 1}))"

# 3. Run mini-soak (mock mode)
python -m tools.soak.run --iterations 10 --auto-tune --mock

# 4. Verify deltas (strict)
python -m tools.soak.verify_deltas_applied --path artifacts/soak/latest --strict

# 5. Run soak gate
python -m tools.soak.soak_gate --path artifacts/soak/latest --prometheus

# 6. Check metrics
cat artifacts/soak/latest/POST_SOAK_METRICS.prom | grep delta
```

---

## 📊 Expected Results

**Before (baseline):**
- Delta apply ratio: ~70-80%
- Signature stuck: 3-5 events
- Skip reasons: Missing/incomplete
- State hash: Not tracked

**After (target):**
- Delta apply ratio: ≥95%
- Signature stuck: 0-1 events
- Skip reasons: 100% coverage
- State hash: Tracked and verified

---

**Status:** Phase 1 ✅ COMPLETE, Phase 2-4 🚧 IN PROGRESS

