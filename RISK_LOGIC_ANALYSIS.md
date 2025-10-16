# 🎯 RISK LOGIC ANALYSIS — PROMPT 3

## Точная risk-логика в iter_watcher

**Цель:** Микротюнинг от реальных метрик риска из EDGE_REPORT для аккуратного снижения risk_ratio до **30-35%**.

---

## 📊 Сводная таблица: Зона риска → Дельты → Эффект

### ZONE 1: AGGRESSIVE (risk_ratio >= 60%)

**Триггер:** `risk_ratio >= 0.60`

**Цель:** Быстро снизить риск через консервативные параметры.

| Параметр | Дельта | Ограничения | Ожидаемый эффект на risk | Ожидаемый эффект на edge |
|----------|--------|-------------|--------------------------|--------------------------|
| **min_interval_ms** | +5 | cap 80 | **-10% to -15%** (меньше min_interval blocks) | -0.1 to -0.2 bps (чуть медленнее реакция) |
| **impact_cap_ratio** | -0.01 | floor 0.08 | **-5% to -8%** (меньше risk exposure) | -0.15 to -0.25 bps (меньшие размеры) |
| **tail_age_ms** | +30 | cap 800 | **-3% to -5%** (меньше churn) | +0.05 to +0.10 bps (больше fills) |
| **ИТОГО** | — | — | **-18% to -28%** | **-0.30 to -0.35 bps** |

**Сценарий применения:**
```
Iteration 1: risk_ratio=0.68, net_bps=2.5
→ AGGRESSIVE: min_interval +5 (65→70), impact_cap -0.01 (0.09→0.08), tail_age +30 (650→680)

Iteration 2: risk_ratio=0.52, net_bps=2.6
→ MODERATE: (переход в зону 2)
```

**Ожидаемый результат:**
- risk_ratio: 0.68 → 0.52 → 0.38 за 2-3 итерации
- net_bps: 2.5 → 2.6 → 2.7 (постепенное восстановление)

---

### ZONE 2: MODERATE (40% <= risk_ratio < 60%)

**Триггер:** `0.40 <= risk_ratio < 0.60`

**Цель:** Плавное снижение риска без резких изменений.

| Параметр | Дельта | Ограничения | Ожидаемый эффект на risk | Ожидаемый эффект на edge |
|----------|--------|-------------|--------------------------|--------------------------|
| **min_interval_ms** | +5 | cap 75 | **-8% to -12%** | -0.1 to -0.15 bps |
| **impact_cap_ratio** | -0.005 | floor 0.09 | **-3% to -5%** | -0.08 to -0.12 bps |
| **ИТОГО** | — | — | **-11% to -17%** | **-0.18 to -0.27 bps** |

**Отличия от AGGRESSIVE:**
- Меньшая дельта для impact_cap: **-0.005** vs **-0.01** (более плавно)
- Более низкий cap для min_interval: **75** vs **80** (меньше throttling)
- Нет изменения tail_age (избегаем накопления дельт)

**Сценарий применения:**
```
Iteration 3: risk_ratio=0.48, net_bps=2.7
→ MODERATE: min_interval +5 (70→75), impact_cap -0.005 (0.08→0.075) [floored to 0.09]

Iteration 4: risk_ratio=0.38, net_bps=2.8
→ (risk < 0.40, переход к нормализации или стабильности)
```

**Ожидаемый результат:**
- risk_ratio: 0.48 → 0.38 → 0.32 за 2 итерации
- net_bps: 2.7 → 2.8 → 2.9 (восстановление edge)

---

### ZONE 3: NORMALIZE (risk < 35% AND net_bps >= 3.0)

**Триггер:** `risk_ratio < 0.35 AND net_bps >= 3.0`

**Цель:** Немного увеличить агрессивность для улучшения edge (low risk + good edge → можно ускориться).

| Параметр | Дельта | Ограничения | Ожидаемый эффект на risk | Ожидаемый эффект на edge |
|----------|--------|-------------|--------------------------|--------------------------|
| **min_interval_ms** | -3 | floor 50 | **+3% to +5%** (больше активности) | **+0.15 to +0.25 bps** (быстрее реакция) |
| **impact_cap_ratio** | +0.005 | cap 0.10 | **+2% to +3%** (чуть больше exposure) | **+0.10 to +0.15 bps** (большие размеры) |
| **ИТОГО** | — | — | **+5% to +8%** | **+0.25 to +0.40 bps** |

**Важно:** Нормализация **НЕ применяется** если:
- `risk_ratio >= 0.35` (еще не достигли целевой зоны)
- `net_bps < 3.0` (edge недостаточно хороший для рискования)

**Сценарий применения:**
```
Iteration 5: risk_ratio=0.28, net_bps=3.1
→ NORMALIZE: min_interval -3 (75→72), impact_cap +0.005 (0.09→0.095)

Iteration 6: risk_ratio=0.32, net_bps=3.2
→ (небольшой рост risk acceptable, edge улучшился)
```

**Ожидаемый результат:**
- risk_ratio: 0.28 → 0.32 (небольшой рост в пределах целевой зоны 30-35%)
- net_bps: 3.1 → 3.2 → 3.3 (улучшение edge)

---

### ZONE 4: STABLE (risk < 40% AND net_bps >= 3.0, но не NORMALIZE условия)

**Триггер:** `risk_ratio < 0.40 AND net_bps >= 3.0` НО `risk_ratio >= 0.35`

**Действие:** Нет изменений (система стабильна).

| Параметр | Дельта | Обоснование |
|----------|--------|-------------|
| **Все** | 0 | Риск в целевой зоне (30-40%), edge хороший (>= 3.0) → не трогать |

**Лог:**
```
| iter_watch | TUNE | (no deltas) |
STABLE: risk=0.32 < 40% + net_bps=3.05 >= 3.0 -> no changes
```

---

## 🎯 Дополнительные драйверы (DRIVER-AWARE)

### Driver 1: High adverse_bps_p95

**Триггер:** `adverse_p95 > 3.5`

**Проблема:** Высокая adverse selection → плохое execution quality.

| Параметр | Дельта | Ограничения | Эффект |
|----------|--------|-------------|--------|
| **impact_cap_ratio** | -0.01 | floor 0.08 | Меньше exposure → меньше adverse fills |
| **max_delta_ratio** | -0.01 | floor 0.10 | Плавный sizing → меньше резких корректировок |

**Лог:**
```
DRIVER: adverse_p95=4.2 > 3.5 -> impact_cap -0.01 (floor 0.08)
DRIVER: adverse_p95=4.2 > 3.5 -> max_delta -0.01 (floor 0.10)
```

---

### Driver 2: High slippage_bps_p95

**Триггер:** `slippage_p95 > 2.5`

**Проблема:** Высокий slippage → теряем edge на execution.

| Параметр | Дельта | Ограничения | Эффект |
|----------|--------|-------------|--------|
| **base_spread_bps_delta** | +0.02 | cap 0.25 | Шире спред → меньше slippage |
| **tail_age_ms** | +30 | cap 800 | Дольше держим ордера → больше fills по хорошим ценам |

**Лог:**
```
DRIVER: slippage_p95=3.2 > 2.5 -> spread +0.02 (cap 0.25)
DRIVER: slippage_p95=3.2 > 2.5 -> tail_age +30ms (cap 800)
```

---

## 🔐 Ограничения и safeguards

### Caps и floors

| Параметр | Floor (min) | Cap (max) | Обоснование |
|----------|-------------|-----------|-------------|
| **min_interval_ms** | 50 | 80 (AGGRESSIVE), 75 (MODERATE) | 50 = минимум для реакции, 80 = максимум throttling |
| **impact_cap_ratio** | 0.08 | 0.10 | 0.08 = минимальный exposure, 0.10 = стандартный |
| **max_delta_ratio** | 0.10 | 0.16 | 0.10 = очень плавный, 0.16 = умеренный |
| **base_spread_bps_delta** | 0.08 | 0.25 | 0.08 = минимальная защита, 0.25 = APPLY_BOUNDS cap |
| **tail_age_ms** | 500 | 800 | 500 = минимум для fills, 800 = максимум (избегаем stale) |

### Conflict resolution

**Вопрос:** Что если risk_ratio в ZONE 1, но slippage_p95 > 2.5?

**Ответ:** Оба триггера применяются **независимо**:
1. ZONE 1 (AGGRESSIVE): `min_interval +5, impact_cap -0.01, tail_age +30`
2. DRIVER (slippage): `spread +0.02, tail_age +30`

**Результат:** `tail_age +30` применяется **только один раз** (проверка `if "tail_age_ms" not in deltas`).

**Финальные дельты:**
```
{
  "min_interval_ms": +5,
  "impact_cap_ratio": -0.01,
  "tail_age_ms": +30,
  "base_spread_bps_delta": +0.02
}
```

---

## 🚨 SOFT-CAPS: Если risk не снижается за 2 итерации

### Проблема

**Сценарий:** 
```
Iteration N:   risk_ratio=0.65 → apply AGGRESSIVE
Iteration N+1: risk_ratio=0.63 → apply AGGRESSIVE again
Iteration N+2: risk_ratio=0.64 (не снизился!)
```

**Риск:** Параметры упираются в caps/floors, но risk не падает → застряли.

---

### Решение 1: Spread Boost (Emergency Widening)

**Условие:** Если risk_ratio **НЕ снижается** за 2 consecutive итерации в ZONE 1/2.

**Действие:** Резко расширить spread для немедленной защиты.

```python
# Pseudo-code for spread boost
consecutive_high_risk = 0

if risk_ratio >= 0.40:
    consecutive_high_risk += 1
else:
    consecutive_high_risk = 0

if consecutive_high_risk >= 2:
    # Check if risk NOT declining
    if risk_history[-1] >= risk_history[-2]:
        # SPREAD BOOST: emergency +0.05 spread
        spread_boost = 0.05
        new_spread = min(current_spread + spread_boost, 0.30)  # Emergency cap 0.30
        deltas["base_spread_bps_delta"] = spread_boost
        reasons.append(f"SOFT_CAP: spread_boost +{spread_boost:.2f} (risk not declining)")
```

**Эффект:**
- **Immediate:** Широкий спред защищает от adverse/slippage
- **Trade-off:** Снижение hit ratio (-5% to -10%), но защита edge
- **Expected:** risk_ratio падает на -10% to -15% за 1 итерацию

**Лог:**
```
| iter_watch | SOFT_CAP | spread_boost +0.05 (risk=0.64 not declining for 2 iters) |
```

---

### Решение 2: Replace Rate Reduction (Calm Down)

**Условие:** Если risk_ratio >= 0.50 за 3 consecutive итерации.

**Действие:** Резко снизить replace_rate для уменьшения concurrency blocks.

```python
if consecutive_high_risk >= 3 and risk_ratio >= 0.50:
    # CALM DOWN: reduce replace rate by 20%
    replace_reduction = int(current_replace_rate * 0.20)
    new_replace = max(current_replace_rate - replace_reduction, 200)  # Floor 200
    deltas["replace_rate_per_min"] = new_replace - current_replace_rate
    reasons.append(f"SOFT_CAP: calm_down (replace_rate -{replace_reduction}, risk high for 3 iters)")
```

**Эффект:**
- **Immediate:** Меньше concurrency/min_interval blocks
- **Trade-off:** Медленнее реакция на рынок
- **Expected:** risk_ratio падает на -15% to -20% за 1-2 итерации

**Лог:**
```
| iter_watch | SOFT_CAP | calm_down (replace_rate -60, risk=0.52 high for 3 iters) |
```

---

### Решение 3: Impact Cap Floor Override (Ultra-Conservative)

**Условие:** Если risk_ratio >= 0.60 за 4 consecutive итерации (extreme case).

**Действие:** Временно снизить impact_cap **ниже** floor 0.08 до 0.06.

```python
if consecutive_high_risk >= 4 and risk_ratio >= 0.60:
    # ULTRA_CONSERVATIVE: override floor
    emergency_impact = 0.06  # Below normal floor 0.08
    deltas["impact_cap_ratio"] = emergency_impact - current_impact_cap
    reasons.append(f"SOFT_CAP: ultra_conservative (impact_cap={emergency_impact}, risk extreme for 4 iters)")
```

**Эффект:**
- **Immediate:** Минимальный exposure, максимальная защита
- **Trade-off:** Значительное снижение gross_bps (-0.3 to -0.5 bps)
- **Expected:** risk_ratio падает на -20% to -30% за 1-2 итерации

**Лог:**
```
| iter_watch | SOFT_CAP | ultra_conservative (impact_cap=0.06, risk=0.62 extreme for 4 iters) |
```

---

### Решение 4: Hybrid Mode (Combined Emergency)

**Условие:** Если risk_ratio >= 0.70 за 2 consecutive итерации (critical).

**Действие:** Применить **все 3 меры** одновременно.

```python
if consecutive_high_risk >= 2 and risk_ratio >= 0.70:
    # HYBRID: all emergency measures
    deltas["base_spread_bps_delta"] = +0.05  # Spread boost
    deltas["replace_rate_per_min"] = -60     # Calm down
    deltas["impact_cap_ratio"] = 0.06 - current_impact_cap  # Ultra-conservative
    reasons.append("SOFT_CAP: hybrid_emergency (risk=0.72 critical for 2 iters)")
```

**Эффект:**
- **Immediate:** Максимальная защита по всем фронтам
- **Trade-off:** Значительное снижение edge (-0.4 to -0.6 bps)
- **Expected:** risk_ratio падает на -30% to -40% за 1 итерацию

**Лог:**
```
| iter_watch | SOFT_CAP | hybrid_emergency (risk=0.72 critical for 2 iters) |
```

---

## 📋 Рекомендации по интеграции soft-caps

### Добавить в `tools/soak/run.py` (после итерации)

```python
# Track risk history for soft-cap detection
risk_history = []  # Global или persist в файл

for iteration in range(args.iterations):
    # ... run iteration ...
    
    # Get risk_ratio from ITER_SUMMARY
    iter_summary_path = Path(f"artifacts/soak/latest/ITER_SUMMARY_{iteration+1}.json")
    if iter_summary_path.exists():
        with open(iter_summary_path, 'r') as f:
            iter_data = json.load(f)
        
        risk_ratio = iter_data["summary"]["risk_ratio"]
        risk_history.append(risk_ratio)
        
        # SOFT-CAP DETECTOR
        if len(risk_history) >= 2:
            # Check if risk not declining
            if risk_history[-1] >= risk_history[-2] and risk_ratio >= 0.60:
                # Trigger soft-cap (spread boost)
                print(f"[SOFT_CAP] Risk not declining: {risk_history[-2]:.2%} -> {risk_history[-1]:.2%}")
                print(f"[SOFT_CAP] Applying emergency spread boost")
                
                # Load runtime overrides
                with open("artifacts/soak/runtime_overrides.json", 'r') as f:
                    overrides = json.load(f)
                
                # Apply spread boost
                overrides["base_spread_bps_delta"] = min(overrides.get("base_spread_bps_delta", 0.14) + 0.05, 0.30)
                
                # Save
                with open("artifacts/soak/runtime_overrides.json", 'w') as f:
                    json.dump(overrides, f, indent=2)
```

---

## ✅ Критерии готовности PROMPT 3

### 1. В ITER_SUMMARY появляются реальные метрики ✅

```bash
jq '.summary | {risk_ratio, adverse_bps_p95, slippage_bps_p95, order_age_p95_ms}' \
  artifacts/soak/latest/ITER_SUMMARY_*.json
```

**Ожидаемый вывод:**
```json
{
  "risk_ratio": 0.68,
  "adverse_bps_p95": 4.2,
  "slippage_bps_p95": 3.5,
  "order_age_p95_ms": 340
}
```

---

### 2. Для каждой зоны риска триггерятся правильные дельты ✅

**ZONE 1 (risk >= 0.60):**
```json
{
  "deltas": {
    "min_interval_ms": 5,
    "impact_cap_ratio": -0.01,
    "tail_age_ms": 30
  },
  "rationale": "AGGRESSIVE: risk=68.0% >= 60% -> ..."
}
```

**ZONE 2 (0.40 <= risk < 0.60):**
```json
{
  "deltas": {
    "min_interval_ms": 5,
    "impact_cap_ratio": -0.005
  },
  "rationale": "MODERATE: risk=45.0% >= 40% -> ..."
}
```

**ZONE 3 (risk < 0.35 AND net_bps >= 3.0):**
```json
{
  "deltas": {
    "min_interval_ms": -3,
    "impact_cap_ratio": 0.005
  },
  "rationale": "NORMALIZE: risk=28.0% < 35% + net_bps=3.10 >= 3.0 -> ..."
}
```

---

## 📊 Целевая зона риска

```
risk_ratio (%)
    ↑
70  │ ╔════════════════╗
    │ ║   ZONE 1       ║
60  │ ║  AGGRESSIVE    ║
    │ ╚════════════════╝
    │
50  │ ┌────────────────┐
    │ │   ZONE 2       │
40  │ │  MODERATE      │
    │ └────────────────┘
    │
35  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ← ЦЕЛЕВАЯ ЗОНА (30-35%)
30  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
    │
    │ ┌────────────────┐
25  │ │   ZONE 3       │
    │ │  NORMALIZE     │
20  │ │  (if edge good)│
    │ └────────────────┘
    │
    └────────────────────────────→ Iterations
```

**Успешный сценарий:**
```
Iter 1: 68% (ZONE 1) → apply AGGRESSIVE
Iter 2: 52% (ZONE 2) → apply MODERATE
Iter 3: 38% (ZONE 2) → apply MODERATE
Iter 4: 32% (ЦЕЛЕВАЯ ЗОНА) → STABLE
Iter 5-6: 30-35% (мониторинг, малые корректировки)
```

---

## 📝 Changelog

**2025-10-14 — PROMPT 3 Implementation**
- ✅ Реализованы точные thresholds для 3 зон риска
- ✅ Обновлены драйверы: adverse_p95 > 3.5, slippage_p95 > 2.5
- ✅ Добавлено логирование `| iter_watch | TUNE | risk=... net=... action={...} |`
- ✅ Создана таблица "зона риска → дельты → эффект"
- ✅ Предложены 4 стратегии soft-caps для застревания risk

---

**🎯 RISK LOGIC READY FOR PRECISE TUNING!**

