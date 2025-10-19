# 🚀 PROMPTS 9-14 INTEGRATION ROADMAP

**Date:** 2025-10-15  
**Status:** 📋 Roadmap Created  
**Type:** Integration & Finalization

---

## 📦 OVERVIEW

These prompts focus on **integrating** all previous work into the main soak test loop:

| Prompt | Focus | Complexity | ETA |
|--------|-------|------------|-----|
| **PROMPT 9** | Guards + KPI Gate Integration | High | 6h |
| **PROMPT 10** | Mock Data Generator (calm/volatile/spike) | Medium | 4h |
| **PROMPT 11** | Idempotency Stress Test (100x) | Low | 2h |
| **PROMPT 12** | Config Precedence Integration Test | Low | 2h |
| **PROMPT 13** | 24h Soak Job + Freeze Snapshot | Medium | 4h |
| **PROMPT 14** | Release Gate Checker | Low | 2h |
| **TOTAL** | | | **20h** |

---

## ✅ PROMPT 9: Guards + KPI Gate + Deterministic I/O Integration

### Status: 🟡 Partial (Framework Created)

### What's Done:
- ✅ `tools/soak/integration_layer.py` — GuardsCoordinator created
- ✅ All components ready (oscillation, velocity, cooldown, kpi_gate, jsonx)

### What's Needed:
1. **Modify `tools/soak/run.py`:**
   ```python
   # Add imports
   from tools.soak.integration_layer import get_coordinator, compute_state_hash
   from tools.common.jsonx import write_json
   from tools.soak.kpi_gate import kpi_gate_check
   
   # In iteration loop (after each iteration):
   coordinator = get_coordinator()
   
   # Check KPI gate
   kpi_result = coordinator.check_kpi_gate(summary)
   if kpi_result["verdict"] == "FAIL" and coordinator.kpi_mode == "hard":
       print(f"❌ KPI Gate FAILED: {kpi_result['reason']}")
       sys.exit(3)
   
   # Compute state hash
   state_hash = compute_state_hash(runtime_overrides_path)
   summary["state_hash"] = state_hash
   
   # Replace all json.dump with jsonx.write_json
   write_json(output_path, data)
   ```

2. **Modify `tools/soak/iter_watcher.py` → `propose_micro_tuning`:**
   ```python
   def propose_micro_tuning(summary, current_overrides, elapsed_hours=1.0):
       coordinator = get_coordinator()
       
       # ... existing logic ...
       
       # Check guards before proposing deltas
       for param, delta in proposed_deltas.items():
           old_value = current_overrides.get(param, 0)
           new_value = old_value + delta
           
           guard_result = coordinator.check_guards(param, old_value, new_value, elapsed_hours)
           
           if not guard_result["allowed"]:
               # Suppress delta
               proposed_deltas[param] = 0.0
               rationale[param] = f"SUPPRESSED: {guard_result['reason']}"
               
               # Add flags to summary
               summary["oscillation_detected"] = guard_result["oscillation_detected"]
               summary["velocity_violation"] = guard_result["velocity_violation"]
               summary["cooldown_active"] = guard_result["cooldown_active"]
       
       return proposed_deltas, rationale
   ```

3. **Environment Variables:**
   - `KPI_GATE_MODE=soft|hard` — Controls KPI gate behavior
   - `ENABLE_GUARDS=1` — Enable oscillation/velocity/cooldown guards

### Acceptance:
- [x] GuardsCoordinator framework created
- [ ] Integration into run.py (requires modification)
- [ ] Integration into propose_micro_tuning (requires modification)
- [ ] All JSON writes use jsonx (requires replacement)
- [ ] KPI gate called after iterations (requires integration)

### Commands:
```bash
# Test with guards enabled
KPI_GATE_MODE=hard ENABLE_GUARDS=1 python -m tools.soak.run --iterations 3 --mock

# Smoke test
SOAK_SLEEP_SECONDS=5 KPI_GATE_MODE=soft pytest -v tests/smoke/test_soak_smoke.py
```

---

## ✅ PROMPT 10: Mock Data Generator (calm/volatile/spike)

### Status: 🔴 Not Started (Concept Only)

### Concept:
```python
# tools/mock/market_gen.py

import random
import math
from typing import Dict, Any

class MarketGenerator:
    """Generate mock market data with different volatility modes."""
    
    def __init__(self, mode="calm", seed=42, sigma=0.01, spike_prob=0.05, gap_bps=10.0):
        self.mode = mode
        self.seed = seed
        self.sigma = sigma
        self.spike_prob = spike_prob
        self.gap_bps = gap_bps
        random.seed(seed)
        
        self.spike_count = 0
        self.gap_events = 0
    
    def generate_metrics(self) -> Dict[str, Any]:
        """Generate mock metrics for one iteration."""
        if self.mode == "calm":
            # Low volatility
            net_bps = 3.0 + random.gauss(0, 0.5)
            adverse_p95 = 2.0 + random.gauss(0, 0.3)
            risk_ratio = 0.30 + random.gauss(0, 0.05)
        
        elif self.mode == "volatile":
            # High volatility
            net_bps = 2.5 + random.gauss(0, 1.5)
            adverse_p95 = 3.0 + random.gauss(0, 1.0)
            risk_ratio = 0.40 + random.gauss(0, 0.15)
        
        elif self.mode == "spike":
            # Occasional spikes
            if random.random() < self.spike_prob:
                # Spike event
                net_bps = 1.0
                adverse_p95 = 8.0
                risk_ratio = 0.70
                self.spike_count += 1
            else:
                # Normal
                net_bps = 3.0 + random.gauss(0, 0.5)
                adverse_p95 = 2.0 + random.gauss(0, 0.3)
                risk_ratio = 0.30 + random.gauss(0, 0.05)
        
        else:
            raise ValueError(f"Unknown mode: {self.mode}")
        
        # Gap event (rare)
        if random.random() < 0.02:  # 2% chance
            net_bps -= self.gap_bps
            self.gap_events += 1
        
        return {
            "net_bps": max(net_bps, -10.0),  # Floor at -10
            "adverse_bps_p95": max(adverse_p95, 0.0),
            "risk_ratio": max(0.0, min(risk_ratio, 1.0)),  # Clamp to [0, 1]
            "maker_taker_ratio": 0.90 + random.gauss(0, 0.03),
            "p95_latency_ms": 250 + random.gauss(0, 50),
            "fills": int(100 + random.gauss(0, 20))
        }
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get generator metadata for ITER_SUMMARY."""
        return {
            "mock_mode": self.mode,
            "mock_seed": self.seed,
            "spike_count": self.spike_count,
            "gap_events": self.gap_events
        }
```

### Environment Variables:
- `USE_MOCK=1` — Enable mock data
- `SOAK_MOCK_MODE=calm|volatile|spike` — Volatility mode
- `SOAK_MOCK_SEED=42` — Random seed (reproducibility)
- `SOAK_MOCK_SIGMA=0.01` — Base volatility
- `SOAK_MOCK_SPIKE_PROB=0.05` — Spike probability (0.0-1.0)
- `SOAK_MOCK_GAP_BPS=10.0` — Gap event size (BPS)

### Integration:
```python
# In tools/soak/run.py

from tools.mock.market_gen import MarketGenerator

# Initialize generator
if os.environ.get("USE_MOCK") == "1":
    mode = os.environ.get("SOAK_MOCK_MODE", "calm")
    seed = int(os.environ.get("SOAK_MOCK_SEED", "42"))
    generator = MarketGenerator(mode=mode, seed=seed)
    
    # In iteration loop:
    mock_metrics = generator.generate_metrics()
    
    # Add metadata to ITER_SUMMARY
    summary.update(generator.get_metadata())
```

### Acceptance:
- [ ] MarketGenerator class implemented
- [ ] Three modes: calm, volatile, spike
- [ ] Reproducible with fixed seed
- [ ] Metadata in ITER_SUMMARY

### Commands:
```bash
# Test with spike mode
USE_MOCK=1 SOAK_MOCK_MODE=spike SOAK_MOCK_SEED=42 \
  python -m tools.soak.run --iterations 6 --mock

# Verify reproducibility
USE_MOCK=1 SOAK_MOCK_MODE=calm SOAK_MOCK_SEED=100 \
  pytest -v tests/mock/test_market_gen.py
```

---

## ✅ PROMPT 11: Idempotency Stress Test (100x apply)

### Status: 🔴 Not Started (Concept Only)

### Concept:
```python
# tests/stress/test_idempotency.py

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.common.jsonx import compute_json_hash

def test_idempotency_100x_apply(tmp_path):
    """
    Test that applying overrides 100x produces same result.
    
    Validates:
    - state_hash remains unchanged
    - No drift in parameters
    - No side effects
    """
    # Setup initial state
    runtime_path = tmp_path / "runtime_overrides.json"
    initial_overrides = {
        "base_spread_bps_delta": 0.14,
        "min_interval_ms": 75,
        "tail_age_ms": 740
    }
    
    from tools.common.jsonx import write_json
    write_json(runtime_path, initial_overrides)
    
    # Compute initial hash
    initial_hash = compute_json_hash(initial_overrides)
    
    # Apply 100 times (should be idempotent)
    for i in range(100):
        # Simulate apply_overrides (read -> write)
        from tools.common.jsonx import read_json
        current = read_json(runtime_path)
        
        # No-op apply (should not change anything)
        write_json(runtime_path, current)
        
        # Verify hash unchanged
        current_hash = compute_json_hash(current)
        assert current_hash == initial_hash, f"Hash changed at iteration {i+1}!"
    
    # Final verification
    final = read_json(runtime_path)
    final_hash = compute_json_hash(final)
    
    assert final == initial_overrides, "Drift detected!"
    assert final_hash == initial_hash, "Final hash mismatch!"
    
    print(f"✅ 100x apply: NO DRIFT (hash={initial_hash[:16]}...)")
```

### Acceptance:
- [ ] Test runs 100 iterations
- [ ] Hash remains stable
- [ ] No drift detected
- [ ] No side effects

### Commands:
```bash
pytest -v tests/stress/test_idempotency.py
```

---

## ✅ PROMPT 12: Config Precedence Integration Test

### Status: 🔴 Not Started (Concept Only)

### Concept:
```python
# tests/integration/test_config_precedence_integration.py

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_config_precedence_integration(tmp_path, monkeypatch):
    """
    End-to-end test for config precedence: CLI > ENV > Profile > Default.
    
    Simulates real soak run with conflicting sources.
    """
    from tools.soak.config_manager import ConfigManager
    
    # Setup
    config_mgr = ConfigManager(tmp_path / "artifacts" / "soak")
    
    # Set env var
    monkeypatch.setenv("MM_RUNTIME_OVERRIDES_JSON", '{"min_interval_ms": 999}')
    
    # Load with profile + CLI override
    overrides = config_mgr.load(
        profile="steady_safe",
        cli_overrides={"tail_age_ms": 888}
    )
    
    # Verify precedence
    # CLI wins for tail_age_ms
    assert overrides["tail_age_ms"] == 888
    
    # ENV wins for min_interval_ms (no CLI override)
    assert overrides["min_interval_ms"] == 999
    
    # Profile wins for impact_cap_ratio (no ENV/CLI override)
    assert overrides["impact_cap_ratio"] == 0.08  # From steady_safe
    
    # Verify sources logged
    sources = overrides.get("_sources", {})
    assert sources["tail_age_ms"] == "cli"
    assert sources["min_interval_ms"] == "env"
    assert sources["impact_cap_ratio"] == "profile:steady_safe"
    
    print("✅ Config precedence: CLI > ENV > Profile VERIFIED")
```

### Acceptance:
- [ ] Test verifies all 4 layers (CLI, ENV, Profile, Default)
- [ ] Sources correctly logged
- [ ] Conflicts resolved per precedence

### Commands:
```bash
pytest -v tests/integration/test_config_precedence_integration.py
```

---

## ✅ PROMPT 13: 24h Soak Job + Freeze Snapshot

### Status: 🔴 Not Started (Concept Only)

### Concept:
```yaml
# .github/workflows/soak-24h.yml

name: Soak 24h (Production Validation)

on:
  workflow_dispatch:
  schedule:
    - cron: "0 0 * * 0"  # Every Sunday at midnight

jobs:
  soak-24h:
    runs-on: [self-hosted, windows, soak]
    timeout-minutes: 1500  # 25 hours (24h + buffer)
    env:
      PYTHON_EXE: python
      KPI_GATE_MODE: hard
      ENABLE_GUARDS: "1"
      
    steps:
      # ... setup steps ...
      
      - name: Run 24h soak with steady-SAFE profile
        run: |
          & $env:PYTHON_EXE -m tools.soak.run \
            --iterations 24 \
            --profile steady_safe \
            --auto-tune \
            --mock
          
          # Sleep 60 minutes between iterations
          $env:SOAK_SLEEP_SECONDS = "3600"
      
      - name: Check freeze snapshot
        run: |
          # Verify freeze was activated
          $latestDir = "artifacts/soak/latest"
          $tuningReport = Get-Content "$latestDir/TUNING_REPORT.json" | ConvertFrom-Json
          
          # Check for freeze activation
          $freezeActivated = $false
          foreach ($iter in $tuningReport.iterations) {
            if ($iter.freeze_active) {
              $freezeActivated = $true
              Write-Host "✅ Freeze activated at iteration $($iter.iteration)"
              Write-Host "   Reason: $($iter.freeze_reason)"
              Write-Host "   Signature: $($iter.signature_hash)"
              break
            }
          }
          
          if (-not $freezeActivated) {
            Write-Warning "⚠️ No freeze activation detected"
          }
      
      - name: Generate freeze snapshot
        run: |
          # Create production-ready snapshot
          & $env:PYTHON_EXE -m tools.freeze_config \
            --input artifacts/soak/runtime_overrides.json \
            --output artifacts/soak/PRODUCTION_SNAPSHOT.json \
            --profile steady_safe
      
      - name: Create trend report
        run: |
          # Generate STEADY_TREND.md
          & $env:PYTHON_EXE -m tools.soak.trend_report \
            --input artifacts/soak/latest \
            --output artifacts/soak/STEADY_TREND.md
      
      - name: Upload artifacts (90 days)
        uses: actions/upload-artifact@v4
        with:
          name: soak-24h-${{ github.run_id }}
          path: |
            artifacts/soak/**
          retention-days: 90
```

### Acceptance:
- [ ] Job runs 24 iterations (1h sleep each)
- [ ] KPI gate hard mode enforced
- [ ] Freeze snapshot created on stability
- [ ] Trend report generated
- [ ] Artifacts uploaded (90 days retention)

---

## ✅ PROMPT 14: Release Gate Checker

### Status: 🔴 Not Started (Concept Only)

### Concept:
```python
# tools/soak/check_release_gate.py

#!/usr/bin/env python3
"""
Release Gate Checker.

Validates final ITER_SUMMARY against production thresholds.
Fails CI if any KPI violated.
"""

import sys
import json
from pathlib import Path

# Production thresholds (stricter than soak)
RELEASE_THRESHOLDS = {
    "maker_taker_ratio": 0.85,  # Min 85%
    "risk_ratio": 0.42,          # Max 42%
    "net_bps": 2.7,              # Min 2.7 BPS
    "p95_latency_ms": 350        # Max 350ms
}

def check_release_gate(iter_summary_path: Path) -> bool:
    """
    Check if iteration passes release gate.
    
    Returns:
        True if all KPIs pass, False otherwise
    """
    if not iter_summary_path.exists():
        print(f"❌ File not found: {iter_summary_path}")
        return False
    
    with open(iter_summary_path, 'r') as f:
        data = json.load(f)
    
    summary = data.get("summary", {})
    
    # Extract metrics
    maker_taker = summary.get("maker_taker_ratio", 0.0)
    risk = summary.get("risk_ratio", 1.0)
    net = summary.get("net_bps", 0.0)
    latency = summary.get("p95_latency_ms", 9999)
    
    violations = []
    
    # Check thresholds
    if maker_taker < RELEASE_THRESHOLDS["maker_taker_ratio"]:
        violations.append(f"maker_taker {maker_taker:.2f} < {RELEASE_THRESHOLDS['maker_taker_ratio']}")
    
    if risk > RELEASE_THRESHOLDS["risk_ratio"]:
        violations.append(f"risk {risk:.2f} > {RELEASE_THRESHOLDS['risk_ratio']}")
    
    if net < RELEASE_THRESHOLDS["net_bps"]:
        violations.append(f"net_bps {net:.2f} < {RELEASE_THRESHOLDS['net_bps']}")
    
    if latency > RELEASE_THRESHOLDS["p95_latency_ms"]:
        violations.append(f"p95_latency {latency:.0f} > {RELEASE_THRESHOLDS['p95_latency_ms']}")
    
    # Print results
    print("=" * 60)
    print("RELEASE GATE CHECK")
    print("=" * 60)
    print(f"Maker/Taker: {maker_taker:.2%} (threshold: {RELEASE_THRESHOLDS['maker_taker_ratio']:.2%})")
    print(f"Risk: {risk:.2%} (threshold: {RELEASE_THRESHOLDS['risk_ratio']:.2%})")
    print(f"Net BPS: {net:.2f} (threshold: {RELEASE_THRESHOLDS['net_bps']:.2f})")
    print(f"P95 Latency: {latency:.0f}ms (threshold: {RELEASE_THRESHOLDS['p95_latency_ms']:.0f}ms)")
    print("=" * 60)
    
    if violations:
        print(f"❌ RELEASE GATE FAILED ({len(violations)} violations):")
        for v in violations:
            print(f"  - {v}")
        return False
    
    print("✅ RELEASE GATE PASSED")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tools.soak.check_release_gate <ITER_SUMMARY.json>")
        return 1
    
    iter_summary_path = Path(sys.argv[1])
    passed = check_release_gate(iter_summary_path)
    
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

### Integration:
```yaml
# In .github/workflows/ci.yml and soak-24h.yml

- name: Check Release Gate
  run: |
    python -m tools.soak.check_release_gate \
      artifacts/soak/latest/ITER_SUMMARY_final.json
```

### Acceptance:
- [ ] Checker validates all 4 KPIs
- [ ] Exit code 0 on pass, 1 on fail
- [ ] Clear violation messages
- [ ] Integrated into CI

### Commands:
```bash
# Manual check
python -m tools.soak.check_release_gate artifacts/soak/latest/ITER_SUMMARY_6.json

# In CI
pytest -v tests/release/test_release_gate.py
```

---

## 📋 IMPLEMENTATION CHECKLIST

### PROMPT 9: Guards Integration
- [x] GuardsCoordinator created
- [ ] Integrate into run.py (modify iteration loop)
- [ ] Integrate into propose_micro_tuning (add guard checks)
- [ ] Replace all json.dump with jsonx.write_json
- [ ] Add state_hash to ITER_SUMMARY
- [ ] Add KPI gate check after iterations
- [ ] Test with KPI_GATE_MODE=hard

### PROMPT 10: Mock Generator
- [ ] Create MarketGenerator class
- [ ] Implement calm/volatile/spike modes
- [ ] Add env var support
- [ ] Integrate into run.py
- [ ] Add metadata to ITER_SUMMARY
- [ ] Test reproducibility with seed

### PROMPT 11: Idempotency Stress
- [ ] Create test_idempotency.py
- [ ] Test 100x apply loop
- [ ] Verify hash stability
- [ ] Verify no drift

### PROMPT 12: Config Precedence Integration
- [ ] Create test_config_precedence_integration.py
- [ ] Test all 4 layers
- [ ] Verify sources logged
- [ ] Run end-to-end

### PROMPT 13: 24h Soak Job
- [ ] Create .github/workflows/soak-24h.yml
- [ ] Configure 24 iterations × 1h sleep
- [ ] Add KPI gate hard mode
- [ ] Add freeze snapshot step
- [ ] Add trend report generation
- [ ] Configure artifact upload (90 days)

### PROMPT 14: Release Gate
- [ ] Create check_release_gate.py
- [ ] Define production thresholds
- [ ] Integrate into ci.yml
- [ ] Integrate into soak-24h.yml
- [ ] Test with violations

---

## 🎯 PRIORITY ORDER

### Phase 1 (Critical):
1. **PROMPT 9** — Guards integration (enables all safety features)
2. **PROMPT 14** — Release gate (CI safety)

### Phase 2 (Important):
3. **PROMPT 10** — Mock generator (testing capability)
4. **PROMPT 11** — Idempotency stress (reliability validation)

### Phase 3 (Nice-to-have):
5. **PROMPT 12** — Config precedence test (documentation)
6. **PROMPT 13** — 24h soak job (production validation)

---

## 📚 FILES SUMMARY

**Created:**
- ✅ `tools/soak/integration_layer.py` (200 lines)
- ✅ `PROMPTS_9_14_INTEGRATION_ROADMAP.md` (this file)

**To Create:**
- `tools/mock/market_gen.py` (~150 lines)
- `tests/stress/test_idempotency.py` (~80 lines)
- `tests/integration/test_config_precedence_integration.py` (~100 lines)
- `tools/soak/check_release_gate.py` (~120 lines)
- `.github/workflows/soak-24h.yml` (~150 lines)

**To Modify:**
- `tools/soak/run.py` — Add guards integration
- `tools/soak/iter_watcher.py` — Add guard checks in propose_micro_tuning

**Total Estimated:** ~800 lines of new code + ~200 lines of modifications

---

## ✅ NEXT STEPS

### Immediate:
1. Review this roadmap
2. Decide on implementation priority
3. Start with PROMPT 9 (guards integration)

### This Week:
- Complete PROMPT 9 (6h)
- Complete PROMPT 14 (2h)
- Test integration

### Next Week:
- Complete PROMPTS 10-13 (12h)
- Full end-to-end validation
- Production readiness review

---

*Roadmap Created: 2025-10-15*  
*Estimated Total Time: 20h*  
*Status: Ready for Implementation*

