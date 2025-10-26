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

## 📊 SOAK_SUMMARY.json (Machine-Readable Snapshot)

Post-Soak Analyzer V2 автоматически генерирует **SOAK_SUMMARY.json** — компактный JSON-снапшот для интеграции с пайплайнами, дашбордами и алертами.

### Структура

```json
{
  "generated_at_utc": "2025-10-21T12:34:56Z",
  "windows": 24,
  "min_windows_required": 24,
  "symbols": {
    "BTCUSDT": {
      "edge_bps": {"median": 3.2, "last": 3.1, "trend": "↑", "status": "OK"},
      "maker_taker_ratio": {"median": 0.84, "last": 0.86, "trend": "≈", "status": "OK"},
      "p95_latency_ms": {"median": 245, "last": 232, "trend": "↓", "status": "OK"},
      "risk_ratio": {"median": 0.33, "last": 0.34, "trend": "≈", "status": "OK"}
    }
  },
  "overall": {
    "crit_count": 0,
    "warn_count": 2,
    "ok_count": 2,
    "verdict": "OK|WARN|CRIT"
  },
  "meta": {
    "commit_range": "abc123..def456",
    "profile": "moderate",
    "source": "soak"
  }
}
```

### Использование

```bash
# Check overall verdict
jq '.overall.verdict' reports/analysis/SOAK_SUMMARY.json

# Extract edge for specific symbol
jq '.symbols.BTCUSDT.edge_bps.last' reports/analysis/SOAK_SUMMARY.json

# Count critical violations
jq '.overall.crit_count' reports/analysis/SOAK_SUMMARY.json
```

### CLI Flags

- `--emit-summary` (default: True) — генерировать SOAK_SUMMARY.json
- `--no-emit-summary` — отключить генерацию

---

## 📈 CLI Mini-Plots (--verbose)

При указании флага `--verbose` анализатор печатает компактную ASCII-таблицу со спарклайнами прямо в stdout:

```bash
python -m tools.soak.analyze_post_soak \
  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
  --verbose
```

### Пример вывода

```
============================================================================================================
MINI-PLOTS SUMMARY
============================================================================================================
Symbol       Edge(bps)            Maker/Taker          p95(ms)              Risk                
------------------------------------------------------------------------------------------------------------
BTCUSDT      ▁▂▄▅▆█▇▅ 3.1 ↑      ▃▄▅▆▆▇██ 0.86 ≈     ▇▆▅▄▃▂▁▁ 232 ↓       ▂▃▃▃▃▃▃▃ 0.34 ≈     
ETHUSDT      ▇▆▅▄▃▂▁▁ 2.9 ↓      ▅▄▄▃▃▃▂▁ 0.82 ↓     ▁▂▃▅▆▇▇█ 360 ↑       ▃▃▄▄▄▅▅▅ 0.42 ↑     
============================================================================================================
```

**Формат:**
- **Sparkline** (8 символов): визуализация динамики за все windows
- **Last value**: последнее значение метрики
- **Trend**: тренд (↑ рост / ↓ падение / ≈ стабильно)

---

## 🔴 Export Violations to Redis

Модуль **`export_violations_to_redis.py`** экспортирует нарушения и summary в Redis для интеграции с алертингом, дашбордами и другими системами.

### Ключи Redis

**Hash per symbol:**
```
{env}:{exchange}:soak:violations:{symbol}
```

**Поля hash:**
- `crit_count` — количество CRIT violations
- `warn_count` — количество WARN violations
- `last_edge` — последнее значение edge_bps
- `last_maker_taker` — последнее значение maker_taker_ratio
- `last_latency_p95` — последнее значение p95_latency_ms
- `last_risk` — последнее значение risk_ratio
- `verdict` — OK / WARN / CRIT
- `updated_at` — ISO timestamp

**Stream (optional):**
```
{env}:{exchange}:soak:violations:stream:{symbol}
```

### Usage

```bash
# Basic export
python -m tools.soak.export_violations_to_redis \
  --summary reports/analysis/SOAK_SUMMARY.json \
  --violations reports/analysis/VIOLATIONS.json \
  --env prod --exchange bybit \
  --redis-url rediss://user:pass@host:6379/0 \
  --ttl 3600

# With stream
python -m tools.soak.export_violations_to_redis \
  --summary reports/analysis/SOAK_SUMMARY.json \
  --violations reports/analysis/VIOLATIONS.json \
  --env prod --exchange bybit \
  --redis-url rediss://localhost:6379/0 \
  --stream
```

### Makefile Target

```bash
make soak-violations-redis
```

### Redis CLI Examples

```bash
# Get hash for symbol
redis-cli HGETALL prod:bybit:soak:violations:BTCUSDT

# Check verdict
redis-cli HGET prod:bybit:soak:violations:BTCUSDT verdict

# Read stream
redis-cli XREAD STREAMS prod:bybit:soak:violations:stream:BTCUSDT 0
```

### Stream Retention (MAXLEN + XTRIM)

Для контроля размера Redis streams используйте флаг `--stream-maxlen`:

```bash
python -m tools.soak.export_violations_to_redis \
  --summary reports/analysis/SOAK_SUMMARY.json \
  --violations reports/analysis/VIOLATIONS.json \
  --env prod --exchange bybit \
  --redis-url rediss://localhost:6379/0 \
  --stream \
  --stream-maxlen 10000
```

**Механизм:**
- При каждом `XADD` используется `MAXLEN ~ <maxlen>` (approximate) для производительности
- После экспорта всех событий выполняется явный `XTRIM MAXLEN ~ <maxlen>` на каждый stream
- Approximate trim (~) позволяет Redis оптимизировать удаление (быстрее, чем exact)

**Рекомендации по выбору лимита:**

| Scenario | Recommended MAXLEN | Rationale |
|----------|-------------------|-----------|
| Dev/Staging | 1000-5000 | Экономия памяти, быстрая итерация |
| Production (low-traffic) | 5000-10000 | Баланс между историей и памятью |
| Production (high-traffic) | 10000-20000 | Больше истории для анализа трендов |
| Archive/Debug | 50000+ | Долгосрочное хранение (но рассмотрите перенос в TSDB) |

**Пример с Redis CLI:**

```bash
# Check stream length
redis-cli XLEN prod:bybit:soak:violations:stream:BTCUSDT

# Manual trim (if needed)
redis-cli XTRIM prod:bybit:soak:violations:stream:BTCUSDT MAXLEN ~ 5000

# Read last 10 events
redis-cli XREVRANGE prod:bybit:soak:violations:stream:BTCUSDT + - COUNT 10
```

### Graceful Fallback

Если Redis недоступен, модуль выводит warning и завершается с `exit 0` (мягкий fallback). Это позволяет продолжить CI-пайплайн даже при недоступности Redis.

---

## 💬 PR Comment Integration

В CI workflows (`.github/workflows/soak.yml` и `soak-windows.yml`) автоматически публикуется комментарий в PR с итогами анализа:

### Пример комментария

```markdown
### 🧪 Soak Analysis Summary

**Windows:** 24 (min=24) | **Verdict:** 🟡 **WARN**

**Commit:** `abc123..def456` | **Profile:** `moderate`

| Symbol | Edge(bps) | Trend | Maker/Taker | Trend | p95(ms) | Trend | Risk | Trend | Status |
|--------|-----------|-------|-------------|-------|---------|-------|------|-------|--------|
| BTCUSDT | 3.1 | ↑ | 0.86 | ≈ | 232 | ↓ | 0.34 | ≈ | ✅ OK |
| ETHUSDT | 2.9 | ↓ | 0.82 | ↓ | 360 | ↑ | 0.42 | ↑ | 🟡 WARN |

**Violations:** 🔴 CRIT: 0 | 🟡 WARN: 4 | ✅ OK: 1

**Artifacts:** POST_SOAK_ANALYSIS.md, RECOMMENDATIONS.md, VIOLATIONS.json, SOAK_SUMMARY.json
(see workflow artifacts above)
```

### Как включить/отключить

**Включено по умолчанию** для PR workflows (`github.event_name == 'pull_request'`).

**Отключить:**
Закомментируйте шаг `Post Soak Summary to PR` в workflow file.

**Требования:**
- `GITHUB_TOKEN` (автоматически доступен в GitHub Actions)
- `SOAK_SUMMARY.json` должен быть создан анализатором

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

