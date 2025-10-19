# 🛡️ RISK-AWARE BASELINE OVERRIDES

## Overview
New safer baseline profile to reduce risk-blocks from ~68% to ≤40% while maintaining edge ≥3.0.

---

## 📊 Baseline Runtime Overrides

**File:** `artifacts/soak/runtime_overrides.json`

```json
{
  "base_spread_bps_delta": 0.12,
  "impact_cap_ratio": 0.10,
  "max_delta_ratio": 0.15,
  "min_interval_ms": 60,
  "replace_rate_per_min": 300,
  "tail_age_ms": 650
}
```

### Rationale:
- **`min_interval_ms: 60`** — Slightly slower pacing to reduce min_interval blocks
- **`tail_age_ms: 650`** — Fresh quotes to reduce slippage
- **`base_spread_bps_delta: 0.12`** — Moderate base spread (not too wide, not too narrow)
- **`impact_cap_ratio: 0.10`** — Conservative impact cap to reduce adverse selection
- **`max_delta_ratio: 0.15`** — Moderate max delta
- **`replace_rate_per_min: 300`** — Balanced replacement rate

---

## 🎯 Expected Metrics (3-6 iterations)

| Metric | Before | Target | Notes |
|--------|--------|--------|-------|
| `risk_ratio` | ~0.68 | ≤0.40 | **Primary goal** |
| `net_bps` | 3.3 | 2.8-3.4 | Hold current edge |
| `adverse_bps_p95` | ? | ≤3.0 | Reduce adverse selection |
| `slippage_bps_p95` | ? | ≤2.5 | Keep slippage low |
| `order_age_p95_ms` | ? | ≤330 | Maintain freshness |

---

## 🔧 Risk-Aware Tuning Logic

### Priority 1: Risk Blocks
- **risk ≥ 60%** (CRITICAL):
  - `min_interval_ms += 5` (cap 90)
  - `base_spread_bps_delta += 0.02` (cap 0.20)
  - `impact_cap_ratio -= 0.01` (floor 0.08)
  - `tail_age_ms = max(tail_age_ms, 680)`

- **risk 40-60%** (HIGH):
  - `min_interval_ms += 5` (cap 80)
  - `impact_cap_ratio -= 0.01` (floor 0.09)

- **risk ≤ 40% AND order_age > 360ms** (speed up):
  - `min_interval_ms -= 5` (floor 50)

### Priority 2: Driver-Aware
- **adverse_p95 > 3.5**:
  - `impact_cap_ratio -= 0.01`
  - `max_delta_ratio -= 0.01`

- **slippage_p95 > 2.5**:
  - `base_spread_bps_delta += 0.02`
  - `tail_age_ms += 30`

### Tuning Decision
- Apply suggestions only if:
  - `net_bps < 3.2` OR `risk_ratio ≥ 0.50`

---

## 📝 New Artifacts

After each iteration, these files are generated in `artifacts/soak/latest/`:

1. **`ITER_SUMMARY_{N}.json`** — Full summary for iteration N
2. **`TUNING_REPORT.json`** — Cumulative list of all iterations + suggestions
3. **`summary.txt`** — Wall-clock duration and iterations completed

---

## ✅ Acceptance Criteria

### Log Markers:
```
| iter_watch | SUMMARY | iter=1 net=3.2 risk=0.45 kpi=PASS |
| iter_watch | SUGGEST | {"min_interval_ms": 5, "impact_cap_ratio": -0.01} |
```

### File Checks:
- ✓ `ITER_SUMMARY_*.json` exists
- ✓ `TUNING_REPORT.json` exists
- ✓ `summary.txt` contains "REAL DURATION (wall-clock)"
- ✓ `summary.txt` contains "ITERATIONS COMPLETED"

### Fail-Safes:
- Job fails if `iter_done == 0`
- Job fails if `KPI_GATE.json: verdict == "FAIL"`

---

## 🚀 Launch Commands

### Windows (PowerShell):
```powershell
$env:MM_PROFILE = "S1"
$env:MM_ALLOW_MISSING_SECRETS = "1"
$env:PYTHONPATH = "$PWD;$PWD\src"

python -m tools.soak.run --iterations 6 --auto-tune --mock
```

### Linux/Mac (Bash):
```bash
export MM_PROFILE=S1
export MM_ALLOW_MISSING_SECRETS=1
export PYTHONPATH="$PWD:$PWD/src"

python -m tools.soak.run --iterations 6 --auto-tune --mock
```

---

## 📊 CI Workflow

The workflow automatically:
1. Seeds default overrides from `tools/soak/default_overrides.json` if not provided
2. Runs mini-soak with `--iterations` and `--auto-tune`
3. Verifies `ITER_SUMMARY_1.json` and `TUNING_REPORT.json` exist
4. Enforces KPI gate (fail on FAIL)
5. Uploads all artifacts to `artifacts/**`

---

## 🎯 Success Metrics

After 3-6 iterations, we expect:
- **Risk blocks** drop from ~68% → ≤40%
- **Net BPS** stable at 2.8-3.4 (target: 3.0+)
- **Adverse p95** ≤ 3.0
- **Slippage p95** ≤ 2.5
- **Order age p95** ≤ 330ms
- **KPI Gate** = PASS or WARN (not FAIL)

---

**Commit:** `71da5e1` — feat(soak): risk-aware mini-soak tuning; enforce iter_watcher; wall-clock summary; fail-safes; safer baseline overrides

