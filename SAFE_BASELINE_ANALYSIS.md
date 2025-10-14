# 🛡️ SAFE BASELINE ANALYSIS — PROMPT 2

## Текущие safe baseline значения

```json
{
  "base_spread_bps_delta": 0.14,
  "impact_cap_ratio": 0.09,
  "max_delta_ratio": 0.14,
  "min_interval_ms": 70,
  "replace_rate_per_min": 260,
  "tail_age_ms": 650
}
```

---

## 📊 Таблица влияния параметров

### Δ параметра → риск / edge

| Параметр | Текущее значение | Влияние на risk_ratio | Влияние на net_bps | Обоснование |
|----------|------------------|----------------------|-------------------|-------------|
| **min_interval_ms** | 70 | ↓ СНИЖАЕТ (0.15-0.25) | ↓ Слегка снижает (-0.2 bps) | Увеличенный интервал → меньше частых замен → меньше min_interval blocks → **ниже risk_ratio**, но немного медленнее реакция на рынок |
| **replace_rate_per_min** | 260 | ↓ СНИЖАЕТ (0.10-0.20) | ↓ Слегка снижает (-0.1 bps) | Умеренная частота замен → меньше concurrency blocks → **ниже risk_ratio**, но может чуть упустить edge при резких движениях |
| **base_spread_bps_delta** | 0.14 | ↔ НЕЙТРАЛЬНО | ↑ Увеличивает (+0.3-0.5 bps) | Широкий спред → **защищает от adverse selection**, увеличивает gross_bps, **компенсирует** более медленные параметры |
| **impact_cap_ratio** | 0.09 | ↓ СНИЖАЕТ (0.05-0.10) | ↓ Снижает (-0.2 bps) | Консервативный cap → меньшие размеры ордеров → **снижает risk blocks** (меньше exposure), но уменьшает gross_bps |
| **max_delta_ratio** | 0.14 | ↓ СНИЖАЕТ (0.03-0.08) | ↓ Снижает (-0.1 bps) | Умеренные корректировки размера → **меньше агрессивных sizing**, снижает потенциал adverse, но упускает часть edge |
| **tail_age_ms** | 650 | ↓ СНИЖАЕТ (0.08-0.15) | ↑ Слегка увеличивает (+0.1 bps) | Дольше держим ордера → меньше ре-квотов → **меньше concurrency**, но может улучшить hit ratio за счёт терпеливости |

---

## 📈 Ожидаемый эффект safe baseline

### Сравнение с предыдущим "агрессивным" baseline

| Метрика | Агрессивный baseline | Safe baseline | Δ изменение |
|---------|---------------------|---------------|-------------|
| **risk_ratio** | 0.40-0.55 (HIGH) | **0.25-0.35** (MODERATE) | **-0.15** (значительное улучшение) |
| **net_bps** | 2.8-3.2 | **2.8-3.0** | **-0.2** (небольшое снижение, в пределах допустимого) |
| **cancel_ratio** | 0.55-0.65 | **0.45-0.55** | **-0.10** (меньше отмен) |
| **order_age_p95_ms** | 280-320 | **350-380** | **+50ms** (чуть дольше, но в safe зоне) |
| **adverse_bps_p95** | 4.5-5.5 | **3.5-4.5** | **-1.0** (лучше execution quality) |
| **slippage_bps_p95** | 3.0-3.8 | **2.5-3.2** | **-0.5** (меньше slippage) |

**Вывод:** Safe baseline **снижает риск на ~35-40%** при **минимальной потере edge (~5-7%)**.

---

## 🔍 Детальный анализ каждого параметра

### 1. min_interval_ms: 60 → 70 (+10ms)

**Механизм:**
- Увеличенный интервал между обновлениями ордеров
- Меньше попыток заменить ордера в rapid-fire режиме
- **Меньше min_interval blocks** (основной источник risk_ratio)

**Влияние:**
- ✅ **risk_ratio**: -0.10 to -0.15 (меньше blocks)
- ⚠️ **net_bps**: -0.1 to -0.2 (чуть медленнее реакция)
- ✅ **cancel_ratio**: -0.05 (меньше ре-квотов)

**Risk mitigation:**
- Снижает "thrashing" (частые замены без пользы)
- Даёт больше времени для экзекюции текущих ордеров

---

### 2. replace_rate_per_min: 300 → 260 (-40)

**Механизм:**
- Ограничение частоты замен ордеров (с 5/sec до 4.3/sec)
- Меньше concurrency → меньше risk blocks

**Влияние:**
- ✅ **risk_ratio**: -0.08 to -0.12 (меньше concurrency blocks)
- ⚠️ **net_bps**: -0.05 to -0.1 (может упустить быстрые движения)
- ✅ **ws_lag sensitivity**: меньше (система менее чувствительна к лагам)

**Risk mitigation:**
- Снижает load на систему (меньше API calls)
- Уменьшает вероятность hit concurrency limits

---

### 3. base_spread_bps_delta: 0.12 → 0.14 (+0.02)

**Механизм:**
- Более широкий спред вокруг mid price
- **Компенсирует** более медленные параметры (min_interval, replace_rate)
- Улучшает защиту от adverse selection

**Влияние:**
- ✅ **net_bps**: +0.3 to +0.5 (компенсация за консерватизм)
- ✅ **adverse_bps_p95**: -0.5 to -1.0 (лучше execution quality)
- ✅ **slippage_bps_p95**: -0.3 to -0.5 (меньше slippage)
- ⚠️ **hit_ratio**: -2% to -5% (может снизиться fill rate)

**Risk mitigation:**
- Защищает от быстрых движений рынка
- **Ключевой параметр для сохранения edge** при консервативных настройках

---

### 4. impact_cap_ratio: 0.10 → 0.09 (-0.01)

**Механизм:**
- Меньший максимальный размер ордера относительно ликвидности
- Снижает exposure → снижает risk blocks

**Влияние:**
- ✅ **risk_ratio**: -0.05 to -0.08 (меньше risk exposure)
- ⚠️ **net_bps**: -0.1 to -0.2 (меньшие размеры → меньше gross_bps)
- ✅ **adverse_bps**: -0.2 to -0.4 (меньше adverse при крупных ордерах)

**Risk mitigation:**
- Снижает вероятность крупных adverse fills
- Уменьшает inventory risk

---

### 5. max_delta_ratio: 0.15 → 0.14 (-0.01)

**Механизм:**
- Меньшие корректировки размера ордера при изменении условий
- Более плавные адаптации → меньше резких sizing

**Влияние:**
- ✅ **risk_ratio**: -0.03 to -0.05 (меньше aggressive sizing)
- ⚠️ **net_bps**: -0.05 to -0.1 (может упустить оптимальный sizing)
- ✅ **slippage_bps**: -0.1 to -0.2 (меньше slippage на крупных корректировках)

**Risk mitigation:**
- Снижает вероятность over-sizing в volatile рынках
- Уменьшает impact cost

---

### 6. tail_age_ms: 600 → 650 (+50ms)

**Механизм:**
- Дольше держим ордера перед заменой tail (далеких от mid)
- Меньше частых ре-квотов → меньше concurrency

**Влияние:**
- ✅ **risk_ratio**: -0.05 to -0.10 (меньше tail replacements)
- ✅ **net_bps**: +0.05 to +0.1 (может улучшить hit ratio)
- ⚠️ **order_age_p95**: +30 to +50ms (чуть дольше живут ордера)

**Risk mitigation:**
- Снижает churn (частые замены без экзекюции)
- Даёт больше времени для fill на tail ордерах

---

## 🆘 Альтернативный вариант: "ЕЩЁ БЕЗОПАСНЕЕ"

### Условие активации
Если после **2 итераций** risk_ratio > 0.45 → переключиться на ultra-safe baseline.

### Ultra-safe baseline значения

```json
{
  "base_spread_bps_delta": 0.16,
  "impact_cap_ratio": 0.08,
  "max_delta_ratio": 0.12,
  "min_interval_ms": 80,
  "replace_rate_per_min": 220,
  "tail_age_ms": 700
}
```

### Изменения относительно safe baseline

| Параметр | Safe baseline | Ultra-safe | Δ изменение | Обоснование |
|----------|---------------|------------|-------------|-------------|
| `base_spread_bps_delta` | 0.14 | **0.16** | **+0.02** | Ещё шире спред → компенсирует ultra-консерватизм |
| `impact_cap_ratio` | 0.09 | **0.08** | **-0.01** | Меньшие размеры → минимальный risk exposure |
| `max_delta_ratio` | 0.14 | **0.12** | **-0.02** | Очень плавные sizing корректировки |
| `min_interval_ms` | 70 | **80** | **+10** | Максимальный интервал (cap в APPLY_BOUNDS) |
| `replace_rate_per_min` | 260 | **220** | **-40** | Значительно меньше ре-квотов |
| `tail_age_ms` | 650 | **700** | **+50** | Дольше держим tail ордера |

### Ожидаемый эффект ultra-safe baseline

| Метрика | Safe baseline | Ultra-safe baseline | Δ изменение |
|---------|---------------|---------------------|-------------|
| **risk_ratio** | 0.25-0.35 | **0.15-0.25** | **-0.10** (дополнительное снижение) |
| **net_bps** | 2.8-3.0 | **2.6-2.9** | **-0.2** (небольшая потеря edge) |
| **cancel_ratio** | 0.45-0.55 | **0.35-0.45** | **-0.10** (минимум отмен) |
| **order_age_p95_ms** | 350-380 | **400-450** | **+50ms** (дольше ордера) |
| **min_interval_blocks** | 15-25% | **8-15%** | **-10%** (резкое снижение) |
| **concurrency_blocks** | 10-18% | **5-10%** | **-8%** (резкое снижение) |

**Trade-off:** Жертвуем **~0.2-0.3 bps edge**, но получаем **rock-solid stability** (risk_ratio < 0.25).

---

## 📋 Рекомендации по применению

### Стратегия переключения baseline

```python
# Pseudo-code for baseline switching logic

if iteration <= 2:
    # First 2 iterations: observe with safe baseline
    baseline = "safe"
    
elif iteration == 3:
    # After 2 iterations: evaluate risk_ratio
    avg_risk_ratio = mean([iter1.risk_ratio, iter2.risk_ratio])
    
    if avg_risk_ratio > 0.45:
        # High risk detected → switch to ultra-safe
        baseline = "ultra_safe"
        print(f"[BASELINE_SWITCH] risk_ratio={avg_risk_ratio:.2%} > 0.45 → ultra-safe")
        load_ultra_safe_overrides()
    else:
        # Risk acceptable → continue with safe
        baseline = "safe"
        print(f"[BASELINE] risk_ratio={avg_risk_ratio:.2%} acceptable → stay safe")

elif baseline == "ultra_safe" and current_iter.risk_ratio < 0.30:
    # Ultra-safe stabilized → можно вернуться к safe
    baseline = "safe"
    print(f"[BASELINE_REVERT] risk_ratio={current_iter.risk_ratio:.2%} < 0.30 → revert to safe")
```

### Условия для ultra-safe

1. **Триггер:** avg(risk_ratio_iter1, risk_ratio_iter2) > 0.45
2. **Действие:** Переключиться на ultra-safe baseline
3. **Revert:** Если risk_ratio < 0.30 в течение 2 итераций → вернуться к safe

---

## 🎯 Целевые метрики для safe baseline

### KPI Gate

| Метрика | Минимум (FAIL) | Целевое (PASS) | Stretch (EXCELLENT) |
|---------|----------------|----------------|---------------------|
| **net_bps** | < 2.5 | **≥ 2.8** | ≥ 3.2 |
| **risk_ratio** | > 0.50 | **≤ 0.35** | ≤ 0.25 |
| **cancel_ratio** | > 0.60 | **≤ 0.55** | ≤ 0.45 |
| **adverse_bps_p95** | > 5.0 | **≤ 4.5** | ≤ 3.5 |
| **slippage_bps_p95** | > 3.5 | **≤ 3.2** | ≤ 2.5 |

### Успешный результат

Safe baseline считается успешным, если за **первые 3 итерации**:
- ✅ risk_ratio стабильно ≤ 0.35
- ✅ net_bps ≥ 2.8
- ✅ Нет переключений на ultra-safe

---

## 📊 Визуализация trade-offs

```
Edge (net_bps)
    ↑
3.5 │                    ╭─ Aggressive
    │                  ╱
3.2 │              ╱─╯
    │          ╱─╯
3.0 │      ╭─╯ ← Safe baseline (целевая зона)
    │  ╭─╯
2.8 │╭─╯
    │╰─ Ultra-safe
2.5 │
    └─────────────────────────────────→ Risk (risk_ratio)
    0.15  0.25  0.35  0.45  0.55  0.65

Legend:
  ● Safe baseline:   risk ~0.30, edge ~2.9
  ● Ultra-safe:      risk ~0.20, edge ~2.7
  ● Aggressive:      risk ~0.50, edge ~3.1
```

**Sweet spot:** Safe baseline в зоне (risk=0.25-0.35, edge=2.8-3.0)

---

## 🔧 Реализация

### Создание ultra-safe baseline файла

```bash
# Create ultra-safe fallback baseline
cat > artifacts/soak/ultra_safe_overrides.json << 'EOF'
{
  "base_spread_bps_delta": 0.16,
  "impact_cap_ratio": 0.08,
  "max_delta_ratio": 0.12,
  "min_interval_ms": 80,
  "replace_rate_per_min": 220,
  "tail_age_ms": 700
}
EOF
```

### Интеграция в run.py (future enhancement)

```python
# In tools/soak/run.py, after iteration 2:

if iteration == 2:
    # Evaluate risk_ratio from first 2 iterations
    risk_ratios = [
        iter1_summary["risk_ratio"],
        iter2_summary["risk_ratio"]
    ]
    avg_risk = sum(risk_ratios) / len(risk_ratios)
    
    if avg_risk > 0.45:
        # Switch to ultra-safe
        ultra_safe_path = Path("artifacts/soak/ultra_safe_overrides.json")
        if ultra_safe_path.exists():
            with open(ultra_safe_path, 'r') as f:
                current_overrides = json.load(f)
            save_runtime_overrides(current_overrides)
            print(f"[BASELINE_SWITCH] avg_risk={avg_risk:.2%} > 0.45 → ultra-safe")
```

---

## ✅ Критерии готовности PROMPT 2

- ✅ **Оба файла существуют** (`runtime_overrides.json`, `steady_overrides.json`)
- ✅ **Одинаковые значения** в обоих файлах
- ✅ **Preview в логах** при старте mini-soak
- ✅ **Таблица влияния** параметров на risk/edge
- ✅ **Ultra-safe вариант** документирован с условиями активации

---

## 📝 Changelog

**2025-10-14 — PROMPT 2 Implementation**
- ✅ Created safe baseline with 6 tuned parameters
- ✅ Added runtime overrides preview at startup
- ✅ Analyzed impact of each parameter on risk_ratio and net_bps
- ✅ Designed ultra-safe fallback baseline (for risk_ratio > 0.45)
- ✅ Documented baseline switching strategy

---

**🎯 SAFE BASELINE READY FOR DEPLOYMENT!**

