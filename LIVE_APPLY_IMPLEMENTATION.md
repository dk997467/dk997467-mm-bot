# 🔧 LIVE-APPLY MECHANISM — Implementation Complete

## Overview

Реализован механизм **live-apply** для автоматического применения дельт настроек между итерациями mini-soak. Теперь рекомендации из `iter_watcher` **реально применяются** к `runtime_overrides.json`, а не остаются "на бумаге".

## What Changed

### Before (PROMPT 1 - BEFORE)
```
iter_watcher → ITER_SUMMARY_N.json (tuning.deltas, applied=false)
                              ↓
                        (дельты НЕ применяются)
                              ↓
                   runtime_overrides.json (не меняется)
```

### After (PROMPT 1 - AFTER)
```
iter_watcher → ITER_SUMMARY_N.json (tuning.deltas, applied=false)
                              ↓
                   apply_tuning_deltas(N)
                              ↓
                   runtime_overrides.json (ОБНОВЛЯЕТСЯ с bounds checking)
                              ↓
                   ITER_SUMMARY_N.json (applied=true)
```

---

## Implementation Details

### New Function: `apply_tuning_deltas(iter_idx)`

**Location:** `tools/soak/run.py`

**Purpose:** Читает дельты из `ITER_SUMMARY_{iter_idx}.json` и применяет их к `runtime_overrides.json` с строгими ограничениями.

**Signature:**
```python
def apply_tuning_deltas(iter_idx: int) -> bool:
    """
    Apply tuning deltas from ITER_SUMMARY_{iter_idx}.json to runtime_overrides.json.
    
    Returns:
        True if deltas were applied, False otherwise
    """
```

**Algorithm:**
1. Прочитать `artifacts/soak/latest/ITER_SUMMARY_{iter_idx}.json`
2. Проверить `tuning.applied == false` и `tuning.deltas` не пусто
3. Загрузить `artifacts/soak/runtime_overrides.json`
4. Применить дельты с **bounds checking** (см. APPLY_BOUNDS ниже)
5. Сохранить обновленный `runtime_overrides.json`
6. Проставить `applied=true` в `ITER_SUMMARY_{iter_idx}.json`
7. Залогировать изменения в формате `| iter_watch | APPLY | ... |`

---

## Strict Bounds (APPLY_BOUNDS)

Более консервативные ограничения по сравнению с `LIMITS` в `compute_tuning_adjustments()`:

| Parameter                | Old LIMITS (EdgeSentinel) | New APPLY_BOUNDS (live-apply) | Reason                          |
|--------------------------|---------------------------|-----------------------------|----------------------------------|
| `min_interval_ms`        | 50-300                    | **40-80**                   | Prevent excessive throttling     |
| `impact_cap_ratio`       | 0.04-0.12                 | **0.08-0.12**               | Floor raised for safety          |
| `max_delta_ratio`        | *(not in LIMITS)*         | **0.10-0.16**               | Prevent over-aggressive sizing   |
| `base_spread_bps_delta`  | 0.0-0.6                   | **0.08-0.25**               | Floor+cap for realistic spreads  |
| `tail_age_ms`            | 400-1000                  | **500-800**                 | Prevent stale orders             |
| `replace_rate_per_min`   | 120-360                   | **200-320**                 | Moderate replacement frequency   |

**Rationale:**
- **Tighter bounds** reduce risk of parameter drift into unsafe zones
- **Floor constraints** prevent overly aggressive strategies
- **Cap constraints** prevent excessive conservatism

---

## Integration with Mini-Soak Loop

### Before (old code):
```python
iter_watcher.process_iteration(...)
# Deltas computed but NOT applied

current_overrides = new_overrides  # From compute_tuning_adjustments
```

### After (new code):
```python
iter_watcher.process_iteration(...)
# Deltas computed and written to ITER_SUMMARY_N.json

# PROMPT 1: Apply deltas to runtime_overrides.json
apply_tuning_deltas(iteration + 1)

# Reload overrides after live-apply
if overrides_path_reload.exists():
    with open(overrides_path_reload, 'r', encoding='utf-8') as f:
        current_overrides = json.load(f)
```

**Key change:** `current_overrides` теперь загружается из файла **после** применения дельт, а не из `compute_tuning_adjustments()`.

---

## Log Markers

### Success (deltas applied):
```
| iter_watch | APPLY | iter=1 params=3 |
  min_interval_ms: 65 → 70 (Δ=+5)
  base_spread_bps_delta: 0.14 → 0.16 (Δ=+0.02)
  tail_age_ms: 620 → 650 (Δ=+30)
```

### Bound hit (capped/floored):
```
| iter_watch | APPLY | iter=2 params=2 |
  min_interval_ms: 78 → 80 (Δ=+5) [cap]
  impact_cap_ratio: 0.09 → 0.08 (Δ=-0.02) [floor]
```

### Skip (already applied):
```
| iter_watch | APPLY | SKIP | iter=3 already_applied=true |
```

### Skip (no deltas):
```
| iter_watch | APPLY | SKIP | iter=4 no deltas |
```

### Self-check (first 2 iterations only):
```
| iter_watch | SELF_CHECK | Diff for runtime_overrides.json (iter 1) |
  - base_spread_bps_delta: 0.14 → 0.16
  - min_interval_ms: 65 → 70
  - tail_age_ms: 620 → 650
```

---

## PITFALLS & Recommendations

### ⚠️ PITFALL 1: Unbounded Drift
**Risk:** Parameters могут постепенно дрейфовать к экстремальным значениям за много итераций.

**Mitigation:**
- ✅ Реализовано: `APPLY_BOUNDS` с жёсткими ограничениями
- ✅ Реализовано: Bounds checking на каждую дельту
- ✅ Реализовано: Логирование `[cap]`/`[floor]` при достижении границ

**Additional safeguards (future):**
- Добавить счетчик consecutive caps/floors (например, если 3 раза подряд упираемся в cap → прекратить дельты)
- Добавить "reversion gate": если net_bps падает 2 итерации подряд после apply → откатить последние изменения

---

### ⚠️ PITFALL 2: Oscillation (Колебания)
**Risk:** Параметры могут начать колебаться: +5 → -5 → +5 → -5...

**Example:**
```
Iter 1: min_interval_ms = 60 (risk high → +5)
Iter 2: min_interval_ms = 65 (risk low → -5)
Iter 3: min_interval_ms = 60 (risk high → +5)
...
```

**Mitigation:**
- ✅ Реализовано: `iter_watcher` использует **hysteresis** (разные пороги для увеличения/уменьшения)
- ✅ Реализовано: Дельты применяются только когда `should_apply = (net_bps < 3.2) or (risk_ratio >= 0.50)`

**Additional safeguards (future):**
- Добавить EMA smoothing: не применять дельты мгновенно, а накапливать EMA-сглаженные дельты
- Добавить cooldown period: после apply дельты → пропустить 1 итерацию перед следующим apply

---

### ⚠️ PITFALL 3: Cumulative Spread Explosion
**Risk:** `base_spread_bps_delta` может расти без ограничений, если каждая итерация добавляет +0.02.

**Example:**
```
Iter 1: 0.14 → 0.16 (+0.02)
Iter 2: 0.16 → 0.18 (+0.02)
Iter 3: 0.18 → 0.20 (+0.02)
Iter 4: 0.20 → 0.22 (+0.02)
Iter 5: 0.22 → 0.24 (+0.02)
Iter 6: 0.24 → 0.25 (+0.02) [cap]
```

**Mitigation:**
- ✅ Реализовано: `APPLY_BOUNDS["base_spread_bps_delta"] = (0.08, 0.25)` — жёсткий cap 0.25
- ✅ Реализовано: `iter_watcher` применяет spread дельты только если `slippage_p95 > 2.5`

**Additional safeguards (future):**
- Добавить "spread delta budget": max суммарное изменение spread за N итераций (например, max +0.10 за 5 итераций)
- Добавить "spread alarm": если spread > 0.20 → WARN в логах, если > 0.23 → автопауза apply

---

### ⚠️ PITFALL 4: Conflicting Deltas
**Risk:** `compute_tuning_adjustments()` и `iter_watcher.propose_micro_tuning()` могут давать **противоречивые** рекомендации.

**Example:**
```
compute_tuning_adjustments(): min_interval_ms +20 (cancel_ratio high)
iter_watcher:                 min_interval_ms -5  (risk low, age high)
```

**Current behavior:**
- `compute_tuning_adjustments()` НЕ применяется (закомментировано `if not iter_watcher: current_overrides = new_overrides`)
- Только `iter_watcher` дельты применяются через `apply_tuning_deltas()`

**Mitigation:**
- ✅ Реализовано: `iter_watcher` имеет приоритет (более детальная логика)
- ✅ Реализовано: `compute_tuning_adjustments()` используется только в legacy fallback mode

**Additional safeguards (future):**
- Добавить "conflict detector": если знаки дельт противоположны → не применять ни одну, залогировать CONFLICT
- Добавить "merge strategy": усреднить дельты или взять минимальную по модулю

---

### ⚠️ PITFALL 5: Late Iteration Dominance
**Risk:** Если дельты применяются на последних итерациях (5-6), они не успевают "доказать" эффект.

**Example:**
```
Iter 5: apply spread +0.02
Iter 6: metrics еще не отразили изменение → apply spread +0.02 again
Final: spread завышен без подтверждения
```

**Mitigation:**
- ⚠️ Частично реализовано: `should_apply` проверяет условия перед apply
- ❌ Не реализовано: нет защиты для поздних итераций

**Additional safeguards (recommended):**
- Добавить "late iteration guard": если `iteration > (total_iterations - 2)` → не применять дельты (только наблюдать)
- Добавить "confirmation gate": дельты применяются только если условие сохраняется 2 итерации подряд

---

### ⚠️ PITFALL 6: File Race Conditions
**Risk:** Если несколько процессов/threads пишут в `runtime_overrides.json` одновременно → corruption.

**Mitigation:**
- ✅ Реализовано: mini-soak запускается в **одном процессе** (sequential iterations)
- ✅ Реализовано: `save_runtime_overrides()` перезаписывает файл атомарно (write → rename)

**Additional safeguards (if needed for production):**
- Добавить file locking: `fcntl.flock()` на Linux, `msvcrt.locking()` на Windows
- Добавить версионирование: `runtime_overrides_v2.json`, `runtime_overrides_v3.json`

---

## Testing & Verification

### Demo Script
```bash
python demo_live_apply.py
```

**Expected output:**
1. ✅ 3 iterations completed
2. ✅ `ITER_SUMMARY_1.json`, `ITER_SUMMARY_2.json`, `ITER_SUMMARY_3.json` created
3. ✅ `applied=true` in all ITER_SUMMARY files (if deltas present)
4. ✅ `runtime_overrides.json` evolves between iterations
5. ✅ Diff shown for first 2 iterations
6. ✅ `| iter_watch | APPLY | ...` log markers present

### Manual Testing
```bash
# Run mini-soak with auto-tuning
python -m tools.soak.run --iterations 6 --auto-tune --mock

# Check applied flags
jq '.tuning.applied' artifacts/soak/latest/ITER_SUMMARY_*.json

# Check deltas
jq '.tuning.deltas' artifacts/soak/latest/ITER_SUMMARY_*.json

# Check final overrides
cat artifacts/soak/runtime_overrides.json
```

---

## CI/CD Integration

### GitHub Actions Workflow (soak-windows.yml)

**Already configured:**
- `MM_RUNTIME_OVERRIDES_JSON` seeded from `tools/soak/default_overrides.json`
- `--auto-tune` flag enabled by default
- Iteration summaries uploaded as artifacts

**No changes needed** — live-apply works automatically when `--auto-tune` is enabled.

---

## Summary Table

| Feature                          | Status | Location                                      |
|----------------------------------|--------|-----------------------------------------------|
| `apply_tuning_deltas()` function | ✅     | `tools/soak/run.py:493`                       |
| Strict bounds (APPLY_BOUNDS)     | ✅     | `tools/soak/run.py:515`                       |
| Bounds checking per delta        | ✅     | `tools/soak/run.py:580`                       |
| Mark `applied=true`              | ✅     | `tools/soak/run.py:624`                       |
| Log applied changes              | ✅     | `tools/soak/run.py:634`                       |
| Self-check diff (first 2 iters)  | ✅     | `tools/soak/run.py:659`                       |
| Integration with mini-soak loop  | ✅     | `tools/soak/run.py:949`                       |
| Reload overrides after apply     | ✅     | `tools/soak/run.py:952`                       |
| Final summary message            | ✅     | `tools/soak/run.py:991`                       |
| Demo script                      | ✅     | `demo_live_apply.py`                          |
| Documentation                    | ✅     | `LIVE_APPLY_IMPLEMENTATION.md` (this file)    |

---

## Recommended Next Steps (Optional Enhancements)

### Phase 2: Advanced Safeguards
1. **Oscillation detector** — track parameter direction changes, pause apply if oscillating
2. **Cumulative delta budget** — limit total change per parameter across all iterations
3. **Late iteration guard** — disable apply for last 2 iterations
4. **Conflict detector** — merge/resolve conflicting deltas from multiple sources

### Phase 3: Observability
1. **Delta effectiveness tracker** — measure Δnet_bps after each apply
2. **Parameter drift alarm** — WARN if parameter changes > X% from baseline
3. **Apply history log** — structured JSONL log of all applied deltas

### Phase 4: Rollback Capability
1. **Snapshot before apply** — save `runtime_overrides_backup_{iter}.json`
2. **Auto-rollback gate** — if 2 consecutive net_bps drops → revert last apply
3. **Manual rollback command** — `python -m tools.soak.rollback --to-iter N`

---

## References

- **PROMPT 1** (this implementation): Live-apply mechanism with strict bounds
- **MEGA-PROMPT**: Driver-aware tuning logic in `compute_tuning_adjustments()`
- **PROMPT H**: Extended EDGE_REPORT diagnostics (neg_edge_drivers, block_reasons)
- **PROMPT F**: Age relief logic (order_age > 330 → speed up)
- **PROMPT G**: KPI gate enforcement (FAIL verdict → exit 1)

---

## Change Log

### 2025-10-14 — PROMPT 1 Implementation
- ✅ Created `apply_tuning_deltas()` with strict APPLY_BOUNDS
- ✅ Integrated into mini-soak loop (after iter_watcher, before sleep)
- ✅ Added self-check diff for first 2 iterations
- ✅ Added final summary message: `| iter_watch | SUMMARY | steady apply complete |`
- ✅ Created demo script `demo_live_apply.py`
- ✅ Documented PITFALLS and safeguards

---

## Conclusion

✅ **Live-apply mechanism successfully implemented!**

Дельты из `iter_watcher` теперь **реально применяются** между итерациями с:
- Строгими bounds checking
- Логированием изменений
- Проверкой applied=true
- Self-check diff для отладки

Следующий запуск mini-soak с `--auto-tune` покажет эволюцию параметров в реальном времени.

🎯 **Mission accomplished!**

