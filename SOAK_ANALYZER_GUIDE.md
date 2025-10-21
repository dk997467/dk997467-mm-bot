# Post-Soak Analyzer V2 — User Guide

## 📌 Overview

**Post-Soak Analyzer V2** — комплексный инструмент для анализа результатов soak-тестирования с поддержкой:
- ✅ **Трендов** (линейная регрессия для edge, maker/taker, latency, risk)
- ✅ **Sparklines** (ASCII-визуализация динамики метрик)
- ✅ **Violations** (WARN/CRIT пороги с детальными логами)
- ✅ **Recommendations** (специфичные действия на русском языке для каждого символа)

---

## 🚀 Quick Start

### Локальный запуск

```bash
# Basic analysis
make soak-analyze

# With custom thresholds
python -m tools.soak.analyze_post_soak \
  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
  --min-windows 24 \
  --warn-edge 2.5 --crit-edge 2.0 \
  --warn-maker 0.80 --crit-maker 0.75 \
  --warn-lat 350 --crit-lat 400 \
  --warn-risk 0.45 --crit-risk 0.50 \
  --exit-on-crit
```

### CI Integration

Analyzer автоматически запускается в GitHub Actions workflows:
- `.github/workflows/soak-windows.yml` (Windows self-hosted)
- `.github/workflows/soak.yml` (Linux)

Шаг: **"Post-Soak Analyzer V2 (trends, sparklines, violations)"**

---

## 📊 Metrics & Rules

### 1. **edge_bps** (Edge в базисных пунктах)

| Threshold | Value | Status | Action |
|-----------|-------|--------|---------|
| CRIT | < 2.0 | ❌ CRIT | Критический убыток! Остановить торговлю |
| WARN | < 2.5 | ⚠️ WARN | Маржа ниже целевой, требуется оптимизация |
| OK | ≥ 2.5 | ✅ OK | Нормальная маржа |

**Trend Indicators:**
- `↑` — Edge растёт (slope > 0.01)
- `↓` — Edge падает (slope < -0.01)
- `≈` — Стабильный edge

### 2. **maker_taker_ratio** (Соотношение maker/taker)

| Threshold | Value | Status | Action |
|-----------|-------|--------|---------|
| CRIT | < 0.75 | ❌ CRIT | Очень низкая доля maker-ордеров |
| WARN | < 0.80 | ⚠️ WARN | Недостаточная доля maker |
| OK | ≥ 0.83 | ✅ OK | Хорошее соотношение |

**Recommendations (Russian):**
- **CRIT**: Уменьшить агрессивность spread, увеличить ширину maker-уровней
- **WARN**: Оптимизировать параметры spread и order placement

### 3. **p95_latency_ms** (P95 задержка в миллисекундах)

| Threshold | Value | Status | Action |
|-----------|-------|--------|---------|
| CRIT | > 400 | ❌ CRIT | Критическая задержка! |
| WARN | > 350 | ⚠️ WARN | Высокая задержка |
| OK | ≤ 330 | ✅ OK | Нормальная задержка |

**Recommendations (Russian):**
- **CRIT**: Проверить сетевое подключение, рассмотреть переход на более быстрый VPS
- **WARN**: Оптимизировать размер ордеров, уменьшить частоту обновлений

### 4. **risk_ratio** (Коэффициент риска)

| Threshold | Value | Status | Action |
|-----------|-------|--------|---------|
| CRIT | > 0.50 | ❌ CRIT | Критический риск! |
| WARN | > 0.45 | ⚠️ WARN | Повышенный риск |
| OK | ≤ 0.40 | ✅ OK | Риск в пределах нормы |

**Recommendations (Russian):**
- **CRIT**: Немедленно снизить позицию, ужесточить stop-loss
- **WARN**: Уменьшить максимальную позицию на 20-30%

---

## 📈 Output Files

### 1. `POST_SOAK_ANALYSIS.md`

**Пример:**

```markdown
# Post-Soak Analysis Report

Generated: 2025-01-15 12:00:00 UTC
Windows analyzed: 24
Min windows required: 24

## Summary Table

| Symbol   | edge_bps | Sparkline | Trend | Status | maker_taker | Sparkline | Trend | Status | p95_lat_ms | Sparkline | Trend | Status | risk_ratio | Sparkline | Trend | Status |
|----------|----------|-----------|-------|--------|-------------|-----------|-------|--------|------------|-----------|-------|--------|------------|-----------|-------|--------|
| BTCUSDT  | 2.85     | ▁▃▅▇█▇▅▃ | ≈     | ✅ OK  | 0.84        | ▃▅▆▇▇█▆▅ | ↑     | ✅ OK  | 320        | ▇▇▆▅▃▂▁▁ | ↓     | ✅ OK  | 0.38       | ▁▂▃▃▃▂▂▁ | ≈     | ✅ OK  |
| ETHUSDT  | 2.45     | ▇▇▆▅▃▂▁▁ | ↓     | ⚠️ WARN| 0.78        | ▇▆▅▄▃▃▂▁ | ↓     | ⚠️ WARN| 360        | ▁▂▃▅▆▇▇█ | ↑     | ⚠️ WARN| 0.42       | ▂▃▄▅▅▆▆▇ | ↑     | ⚠️ WARN|

## Violations Summary

- ❌ CRIT: 0
- ⚠️ WARN: 4
- ✅ OK: 12

## Final Verdict

⚠️ **WARN** — Some metrics below target, optimization recommended
```

### 2. `VIOLATIONS.json`

**Структура:**

```json
[
  {
    "symbol": "ETHUSDT",
    "metric": "edge_bps",
    "level": "WARN",
    "window_index": 22,
    "value": 2.45,
    "threshold": 2.5,
    "note": "Edge below target, optimization required"
  },
  {
    "symbol": "ETHUSDT",
    "metric": "maker_taker_ratio",
    "level": "WARN",
    "window_index": 23,
    "value": 0.78,
    "threshold": 0.80,
    "note": "Low maker ratio"
  }
]
```

**Использование в CI:**
```bash
# Parse violations for alerting
CRIT_COUNT=$(jq '[.[] | select(.level == "CRIT")] | length' artifacts/reports/analysis/VIOLATIONS.json)

if [ "$CRIT_COUNT" -gt 0 ]; then
  echo "::error::$CRIT_COUNT critical violations found!"
  exit 1
fi
```

### 3. `RECOMMENDATIONS.md`

**Пример (на русском):**

```markdown
# Рекомендации по оптимизации

## ETHUSDT

### ⚠️ Низкий edge (2.45 bps)
- Проверить spread относительно конкурентов
- Оптимизировать размер шага цены (tick_size)
- Рассмотреть увеличение ширины spread на 10-15%

### ⚠️ Низкая доля maker (0.78)
- Уменьшить агрессивность spread
- Увеличить ширину maker-уровней
- Рассмотреть более консервативную стратегию входа

### ⚠️ Высокая задержка (360ms)
- Проверить стабильность сети
- Оптимизировать размер ордеров
- Уменьшить частоту обновлений quotes

### ⚠️ Повышенный риск (0.42)
- Уменьшить максимальную позицию на 20-30%
- Ужесточить параметры stop-loss
- Снизить leverage при необходимости
```

---

## 🔧 CLI Options

### Basic Parameters

| Option | Default | Description |
|--------|---------|-------------|
| `--iter-glob` | Required | Glob pattern для ITER_SUMMARY files |
| `--out-dir` | `reports/analysis` | Output directory для отчётов |
| `--min-windows` | `24` | Минимальное кол-во окон для анализа |

### Filtering

| Option | Default | Description |
|--------|---------|-------------|
| `--symbols` | All | Comma-separated список символов (e.g., `BTCUSDT,ETHUSDT`) |
| `--time-buckets` | `1` | Bucket size для агрегации (1=per-window) |

### Edge Thresholds

| Option | Default | Description |
|--------|---------|-------------|
| `--warn-edge` | `2.5` | WARN порог для edge_bps |
| `--crit-edge` | `2.0` | CRIT порог для edge_bps |

### Maker/Taker Thresholds

| Option | Default | Description |
|--------|---------|-------------|
| `--warn-maker` | `0.80` | WARN порог для maker_taker_ratio |
| `--crit-maker` | `0.75` | CRIT порог для maker_taker_ratio |

### Latency Thresholds

| Option | Default | Description |
|--------|---------|-------------|
| `--warn-lat` | `350` | WARN порог для p95_latency_ms |
| `--crit-lat` | `400` | CRIT порог для p95_latency_ms |

### Risk Thresholds

| Option | Default | Description |
|--------|---------|-------------|
| `--warn-risk` | `0.45` | WARN порог для risk_ratio |
| `--crit-risk` | `0.50` | CRIT порог для risk_ratio |

### Exit Control

| Option | Default | Description |
|--------|---------|-------------|
| `--exit-on-crit` | `False` | Exit code 1 если найдены CRIT violations |

---

## 📖 Sparkline Interpretation

**ASCII sparklines** (8-12 chars) показывают динамику метрик с min/max нормализацией.

**Symbols:**
- `▁` — Минимальное значение в серии
- `▂▃▄▅▆▇` — Промежуточные значения
- `█` — Максимальное значение в серии

**Examples:**

| Sparkline | Interpretation |
|-----------|---------------|
| `▁▃▅▇█▇▅▃` | ⛰️ Рост, затем снижение (bell curve) |
| `▇▆▅▄▃▂▁▁` | 📉 Устойчивое снижение |
| `▁▁▂▃▅▇██` | 📈 Устойчивый рост |
| `▃▃▃▃▃▃▃▃` | 📊 Стабильное значение (low variance) |
| `▁█▁█▁█▁█` | ⚡ Высокая волатильность |

---

## 🎯 Trend Detection

**Linear Regression** (sklearn) используется для определения slope:

| Slope | Indicator | Interpretation |
|-------|-----------|----------------|
| > 0.01 | `↑` | **Growing** — метрика растёт |
| -0.01 to 0.01 | `≈` | **Stable** — метрика стабильна |
| < -0.01 | `↓` | **Declining** — метрика падает |

**Normalization:**
- Slope нормализуется на диапазон значений метрики
- Threshold 0.01 = 1% изменения за окно

---

## 🧪 Test Scenarios

### 1. **All OK**

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "tests/fixtures/soak_ok/ITER_*.json" \
  --min-windows 8

# Expected:
# - EXIT CODE: 0
# - Final Verdict: ✅ OK
# - VIOLATIONS.json: []
```

### 2. **CRIT with exit-on-crit**

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "tests/fixtures/soak_crit/ITER_*.json" \
  --exit-on-crit

# Expected:
# - EXIT CODE: 1
# - Final Verdict: ❌ CRIT
# - VIOLATIONS.json: [{"level": "CRIT", ...}]
```

### 3. **WARN (non-blocking)**

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "tests/fixtures/soak_warn/ITER_*.json"

# Expected:
# - EXIT CODE: 0 (even with WARN)
# - Final Verdict: ⚠️ WARN
# - RECOMMENDATIONS.md: Generated with specific actions
```

### 4. **Min-windows check**

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "tests/fixtures/soak_short/ITER_*.json" \
  --min-windows 24

# Expected:
# - EXIT CODE: 0
# - WARNING in report: "Only 8 windows found, 24 required"
# - Analysis continues with available data
```

### 5. **Symbol filtering**

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "artifacts/soak/latest/ITER_*.json" \
  --symbols "BTCUSDT,ETHUSDT"

# Expected:
# - Only BTCUSDT and ETHUSDT analyzed
# - Other symbols skipped
```

---

## ❓ FAQ

### Q: Почему Exit Code = 0 даже при WARN?

**A:** `--exit-on-crit` активирует строгий режим **только для CRIT violations**. WARN — информационный уровень, не блокирует CI pipeline.

Для строгого режима по WARN:
```bash
# Custom script after analyzer
WARN_COUNT=$(jq '[.[] | select(.level == "WARN")] | length' VIOLATIONS.json)
[ "$WARN_COUNT" -gt 0 ] && exit 1 || exit 0
```

### Q: Как интерпретировать "Not enough windows"?

**A:** Если окон меньше `--min-windows`, анализ продолжается с доступными данными, но добавляется **WARNING** в отчёт:

```
⚠️ WARNING: Only 8 windows analyzed (24 required for statistical significance)
```

**Recommendation:** Запустите soak на более длительный период (24+ iterations).

### Q: Где хранятся отчёты в CI?

**A:**
- **Linux**: `artifacts/reports/analysis/`
- **Windows**: `artifacts\reports\analysis\`

**Upload в GitHub Actions:**
```yaml
- uses: actions/upload-artifact@v4
  with:
    name: soak-analysis-${{ github.run_id }}
    path: artifacts/reports/analysis/
```

### Q: Можно ли изменить thresholds для конкретного символа?

**A:** Сейчас thresholds глобальные. Для per-symbol customization:

```bash
# Run twice with different configs
python -m tools.soak.analyze_post_soak \
  --symbols "BTCUSDT" \
  --warn-edge 3.0 --crit-edge 2.5

python -m tools.soak.analyze_post_soak \
  --symbols "ETHUSDT" \
  --warn-edge 2.5 --crit-edge 2.0
```

### Q: Как добавить custom метрику?

**A:** Редактируйте `tools/soak/analyze_post_soak.py`:

1. Добавьте метрику в `METRICS_CONFIG`:
```python
METRICS_CONFIG = {
    "custom_score": {
        "display_name": "Custom Score",
        "warn_high": 100,
        "crit_high": 150,
    }
}
```

2. Убедитесь, что метрика присутствует в `ITER_SUMMARY_*.json`:
```json
{
  "symbol": "BTCUSDT",
  "custom_score": 85.5,
  ...
}
```

---

## 🔗 Related Docs

- [KPI Gate Guide](./KPI_GATE_GUIDE.md) — Automatic pass/fail gates
- [Soak Test Guide](./SOAK_TEST_GUIDE.md) — Long-running stability tests
- [Delta Verification](./DELTA_VERIFY_GUIDE.md) — Auto-tune validation

---

## 📝 Changelog

### v2.0.0 (2025-01-15)

**New Features:**
- ✅ Sparklines (ASCII visualization)
- ✅ Trend detection (linear regression)
- ✅ Per-metric WARN/CRIT thresholds
- ✅ Russian recommendations (RECOMMENDATIONS.md)
- ✅ Violations log (VIOLATIONS.json)
- ✅ Symbol filtering (`--symbols`)
- ✅ Exit-on-crit mode

**Breaking Changes:**
- Removed old `build_reports.py` integration
- New CLI flags (backward-incompatible)

---

**Questions? Contact:** [dima@example.com](mailto:dima@example.com)

**CI Status:** ![CI](https://github.com/user/mm-bot/workflows/CI/badge.svg)

