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

## 🔄 Continuous Mode (Step 6)

### Overview

Continuous Mode автоматизирует полный цикл:
1. **Анализ** → запуск `analyze_post_soak`
2. **Export Summary** → выгрузка `SOAK_SUMMARY.json` в Redis
3. **Export Violations** → выгрузка нарушений (hash + stream) в Redis
4. **Alerts** → уведомления при CRIT/WARN

### Диаграмма потока

```
┌──────────────────┐
│ ITER_SUMMARY_*.  │
│     json         │
└────────┬─────────┘
         │
         ▼
┌────────────────────────┐
│ analyze_post_soak      │
│ (trends, violations)   │
└────────┬───────────────┘
         │
         ├──► POST_SOAK_ANALYSIS.md
         ├──► RECOMMENDATIONS.md
         ├──► VIOLATIONS.json
         └──► SOAK_SUMMARY.json
              │
              ├──► Redis: summary hash
              │    (env:exchange:soak:summary)
              │
              ├──► Redis: violations hash
              │    (env:exchange:soak:violations:{symbol})
              │
              ├──► Redis: violations stream
              │    (env:exchange:soak:violations:stream:{symbol})
              │
              └──► Alerts (Telegram/Slack)
                   if verdict == CRIT
```

### Quick Start

**Одиночный цикл (для отладки):**

```bash
make soak-once
```

**Непрерывный режим (production):**

```bash
make soak-continuous
```

**Кастомные параметры:**

```bash
python -m tools.soak.continuous_runner \
  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
  --min-windows 24 \
  --interval-min 60 \
  --max-iterations 0 \
  --env prod --exchange bybit \
  --redis-url rediss://prod-redis:6379/0 \
  --ttl 3600 \
  --stream --stream-maxlen 10000 \
  --alert telegram --alert slack \
  --verbose
```

### Параметры CLI

| Параметр | Описание | Default |
|----------|----------|---------|
| `--iter-glob` | Glob pattern для ITER_SUMMARY файлов | (required) |
| `--min-windows` | Минимальное кол-во окон для анализа | 24 |
| `--interval-min` | Пауза между циклами (минуты) | 60 |
| `--max-iterations` | Макс. итераций (0=бесконечно) | 0 |
| `--exit-on-crit` | Выход при CRIT нарушениях | False |
| `--env` | Окружение (dev/staging/prod) | dev |
| `--exchange` | Биржа | bybit |
| `--redis-url` | Redis connection URL | redis://localhost:6379/0 |
| `--ttl` | TTL для Redis ключей (сек) | 3600 |
| `--stream` | Экспорт stream нарушений | False |
| `--stream-maxlen` | Лимит stream (retention) | 5000 |
| `--lock-file` | Путь к lock файлу | /tmp/soak_continuous.lock |
| `--alert` | Alert каналы (telegram, slack) | [] |
| `--dry-run` | Dry-run (без Redis/alerts) | False |
| `--verbose` | Verbose logging | False |

### Секреты и ENV

Создайте `.env` файл (или экспортируйте переменные):

```bash
# Redis
REDIS_URL=rediss://prod-redis.example.com:6379/0

# Environment
ENV=prod
EXCHANGE=bybit

# Telegram (optional)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890

# Slack (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
```

**Приоритет:** CLI > ENV > defaults

### Файловый Lock

- Lock файл создается с PID процесса
- Защищает от параллельных запусков
- Auto-cleanup для stale locks (>6h)
- При падении: можно вручную удалить lock файл

```bash
# Проверка lock
ls -la /tmp/soak_continuous.lock

# Удаление вручную (если зависла)
rm /tmp/soak_continuous.lock
```

### Идемпотентность

Если `SOAK_SUMMARY.json` не изменился (одинаковый SHA256 hash), экспорт и алерты пропускаются:

```
[INFO] Summary unchanged, skip export
```

Это экономит ресурсы Redis и предотвращает дублирование алертов.

### Алерты

**Формат сообщения:**

```
[🔴 CRIT] Soak summary (env=prod, exch=bybit)
windows=48 symbols=3 crit=2 warn=1

Top violations:
- BTCUSDT: edge_bps < 2.5 at window #47 (2.1)
- ETHUSDT: risk_ratio >= 0.40 at window #45 (0.41)

Артефакты: POST_SOAK_ANALYSIS.md, RECOMMENDATIONS.md
```

**Условия отправки:**

- `verdict == "CRIT"` → отправка
- `verdict == "WARN"` или `"OK"` → без алертов
- `--dry-run` → печать текста, без отправки

**Каналы:**

- `--alert telegram`: Требует `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `--alert slack`: Требует `SLACK_WEBHOOK_URL`

### CI Integration

Workflow `.github/workflows/continuous-soak.yml` запускается:
- **По расписанию**: каждый час (`0 * * * *`)
- **Вручную**: `workflow_dispatch` с параметрами

**Пример:**

```yaml
- name: Run Continuous Soak (single cycle for CI)
  env:
    REDIS_URL: ${{ secrets.REDIS_URL_DEV }}
    TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  run: |
    python -m tools.soak.continuous_runner \
      --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
      --min-windows 24 \
      --max-iterations 1 \
      --env dev \
      --redis-url "${{ secrets.REDIS_URL_DEV }}" \
      --dry-run \
      --verbose
```

### Troubleshooting Playbook

#### 1. Lock файл застрял (stale)

**Симптом:**
```
[ERROR] Failed to acquire lock, exiting
```

**Решение:**
```bash
# Проверить возраст lock
ls -la /tmp/soak_continuous.lock

# Если >6h и процесс не работает - удалить
rm /tmp/soak_continuous.lock
```

#### 2. Redis недоступен

**Симптом:**
```
[WARN] Could not connect to Redis at redis://...
```

**Решение:**
- Проверить `REDIS_URL` в `.env`
- Проверить firewall/сеть
- Использовать `--dry-run` для локальной отладки

#### 3. CRIT алёрты каждый час (alert fatigue)

**Симптом:**
Telegram/Slack спам при стабильном CRIT.

**Решение:**
- Идемпотентность должна предотвращать (проверить hash summary)
- Добавить rate-limiting в alerting logic (TODO)
- Временно: увеличить `--interval-min` до 120-180

#### 4. Анализатор падает с exit 1

**Симптом:**
```
[WARN] Analyzer returned 1
```

**Решение:**
- Проверить `reports/analysis/` на наличие артефактов
- Запустить `analyze_post_soak` вручную с `--verbose`
- Проверить `--min-windows` (может быть недостаточно данных)

#### 5. Нет алертов при CRIT

**Симптом:**
Verdict=CRIT, но алёрты не приходят.

**Решение:**
- Проверить ENV: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SLACK_WEBHOOK_URL`
- Убедиться что `--alert telegram` или `--alert slack` указан
- Проверить `--dry-run` (если включен - алёрты только печатаются)

### Metrics Output

Каждый цикл логирует метрики:

```
[INFO] CONTINUOUS_METRICS verdict=CRIT windows=48 symbols=3 crit=2 warn=1 ok=0 duration_ms=1234
[INFO] EXPORT_STATUS summary=OK violations=OK reason=
```

**Формат:**
- `verdict`: OK, WARN, CRIT, UNCHANGED, FAIL
- `windows`: Количество окон
- `symbols`: Количество символов
- `crit/warn/ok`: Counts по уровням
- `duration_ms`: Время цикла (мс)
- `EXPORT_STATUS`: summary/violations status (OK/SKIP), reason

Эти метрики можно парсить (e.g., для Prometheus/Grafana).

### Alert Policy (Fine-Tuned)

#### Минимальная серьёзность (`--alert-min-severity`)

Фильтр по уровню:
- `--alert-min-severity OK`: алёрты для всех уровней (OK, WARN, CRIT)
- `--alert-min-severity WARN`: только WARN и CRIT
- `--alert-min-severity CRIT`: только CRIT (default)

**Пример:**
```bash
--alert-min-severity WARN  # Алёрты при WARN или CRIT
```

#### Debounce Window (`--alert-debounce-min`)

Предотвращает спам при повторяющихся уровнях:
- **Default**: 180 минут (3 часа)
- **Логика**: 
  - Одинаковый уровень (CRIT→CRIT) → дебаунс применяется
  - Усиление уровня (WARN→CRIT) → дебаунс игнорируется (отправка сразу)
  - Ослабление (CRIT→WARN) → дебаунс применяется

**Состояние хранится в Redis:**
```json
{
  "last_level": "CRIT",
  "last_sent_utc": "2025-10-26T12:00:00Z"
}
```

**Отключение debounce:**
```bash
--alert-debounce-min 0
```

**Пример сценария:**
1. 12:00 - CRIT → алёрт отправлен
2. 12:30 - CRIT → алёрт пропущен (debounce < 180 min)
3. 15:30 - CRIT → алёрт отправлен (debounce > 180 min)
4. 16:00 - WARN→CRIT → алёрт отправлен сразу (усиление)

#### Redis Key для Debounce

**Default:** `soak:alerts:debounce`

**С префиксом env/exchange:**
```
{env}:{exchange}:soak:alerts:debounce
```

**Пример:** `prod:bybit:soak:alerts:debounce`

### Graceful Redis Degrade

При недоступности Redis:
- **НЕ падает цикл** - продолжает работу
- **Логирование WARN**: `redis unavailable, skip export`
- **Локальный маркер**: `artifacts/state/last_export_status.json`

**Формат маркера:**
```json
{
  "ts": "2025-10-26T12:34:56Z",
  "summary": "SKIP",
  "violations": "OK",
  "reason": "redis_unavailable"
}
```

**Интерпретация:**
- `summary: OK` - экспорт summary выполнен
- `violations: SKIP` - экспорт violations пропущен
- `reason: redis_unavailable` - причина

**Проверка статуса:**
```bash
cat artifacts/state/last_export_status.json
```

**Мониторинг:**
```bash
# Проверка последнего успешного экспорта
jq '.ts,.reason' artifacts/state/last_export_status.json
```

### Runner Heartbeat

Runner пишет heartbeat в Redis после каждого успешного цикла.

**Параметры:**
```bash
--heartbeat-key "soak:runner:heartbeat"  # Base key (будет добавлен префикс env:exchange:)
```

**Полный ключ в Redis:**
```
{env}:{exchange}:soak:runner:heartbeat
```

**Пример:** `prod:bybit:soak:runner:heartbeat`

**TTL:** `2 * interval_min * 60` (минимум 1 час)

**Проверка heartbeat:**
```bash
# Redis CLI
redis-cli GET prod:bybit:soak:runner:heartbeat

# Output: "2025-10-26T12:34:56Z"
```

**Dashboard пример (PromQL):**
```promql
# Время с последнего heartbeat (секунды)
time() - redis_heartbeat_timestamp{env="prod", exchange="bybit"}

# Алерт: heartbeat отсутствует >10 минут
(time() - redis_heartbeat_timestamp) > 600
```

**Grafana panel:**
- **Query**: `redis_heartbeat_timestamp{env="$env", exchange="$exchange"}`
- **Transform**: Time since (now - value)
- **Threshold**: WARN > 5m, CRIT > 10m

### Updated CLI Examples

**Full production run with all features:**
```bash
python -m tools.soak.continuous_runner \
  --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
  --min-windows 24 \
  --interval-min 60 \
  --max-iterations 0 \
  --env prod --exchange bybit \
  --redis-url rediss://user:pass@prod-redis:6379/0 \
  --ttl 3600 \
  --stream --stream-maxlen 10000 \
  --alert telegram --alert slack \
  --alert-min-severity CRIT \
  --alert-debounce-min 180 \
  --heartbeat-key "soak:runner:heartbeat" \
  --verbose
```

**Quick dry-run test (with debounce simulation):**
```bash
make soak-alert-dry
```

**Alert self-test (fake CRIT):**
```bash
make soak-alert-selftest
```

---

## 🔔 Alert Routing (ENV-Specific Policies)

### Параметр `--alert-policy`

Позволяет задавать разные пороги для разных окружений:

```bash
--alert-policy "dev=WARN,staging=WARN,prod=CRIT"
```

**Приоритет:**
- `--alert-policy` **переопределяет** `--alert-min-severity` для конкретного env
- Если env не указан в policy → используется fallback из `--alert-min-severity`

**Примеры:**

**Dev/Staging: более чувствительные (WARN):**
```bash
python -m tools.soak.continuous_runner \
  --env dev \
  --alert-policy "dev=WARN,staging=WARN,prod=CRIT" \
  --alert telegram
```
→ Логирование: `ALERT_POLICY env=dev min_severity=WARN source=alert-policy`

**Prod: только критические (CRIT):**
```bash
python -m tools.soak.continuous_runner \
  --env prod \
  --alert-policy "dev=WARN,staging=WARN,prod=CRIT" \
  --alert telegram
```
→ Логирование: `ALERT_POLICY env=prod min_severity=CRIT source=alert-policy`

**Fallback на глобальный:**
```bash
python -m tools.soak.continuous_runner \
  --env test \
  --alert-min-severity OK \
  --alert telegram
```
→ Логирование: `ALERT_POLICY env=test min_severity=OK source=alert-min-severity`

### Формат лога

```
ALERT_POLICY env=prod min_severity=CRIT source=alert-policy
```

**Поля:**
- `env`: текущее окружение
- `min_severity`: эффективная минимальная серьёзность
- `source`: `alert-policy` (из --alert-policy) или `alert-min-severity` (fallback)

---

## ⏱️ Debounce ETA (Remaining Time)

### Формат логов

**При дебаунсе (алёрт пропущен):**
```
ALERT_DEBOUNCED level=CRIT last_sent="2025-10-26T10:20:00Z" debounce_min=180 remaining_min=73 verdict=CRIT
```

**Интерпретация:**
- `remaining_min=73` → следующий алёрт возможен через 73 минуты
- `debounce_min=180` → полное окно дебаунса (3 часа)
- `last_sent` → timestamp последнего отправленного алёрта

**При эскалации (bypass debounce):**
```
ALERT_BYPASS_DEBOUNCE prev=WARN new=CRIT reason=severity_increase
```

**Интерпретация:**
- Severity усилился (WARN → CRIT)
- Debounce игнорируется
- Алёрт отправлен немедленно

### Расчёт remaining_min

```python
remaining_min = max(0, debounce_min - floor((now - last_sent) / 60))
```

**Пример сценария:**
1. **12:00** - CRIT алёрт отправлен
2. **12:45** - CRIT снова → `remaining_min=135` (ещё 2h 15m)
3. **15:00** - CRIT → `remaining_min=0`, алёрт отправлен
4. **15:15** - WARN→CRIT → `ALERT_BYPASS_DEBOUNCE`, отправлен сразу

### Где смотреть

**Logs (stdout):**
```bash
grep "ALERT_DEBOUNCED\|ALERT_BYPASS" soak_runner.log
```

**Grafana (Loki):**
```logql
{job="soak-runner"} |= "ALERT_DEBOUNCED" or "ALERT_BYPASS_DEBOUNCE"
```

**Интерпретация в Grafana panel:**
- Видите много `ALERT_DEBOUNCED` с высоким `remaining_min` → система застряла в CRIT
- Видите частые `ALERT_BYPASS_DEBOUNCE` → много эскалаций

---

## 📊 Heartbeat Dashboard (Grafana)

### Доступные панели

Dashboard: `ops/grafana/soak_runner_dashboard.json`

**Панели:**
1. **Runner Heartbeat Age**: Время с последнего heartbeat (минуты)
2. **Alert Debounce Status**: Логи debounce событий
3. **Export Status**: Redis export статусы
4. **Continuous Metrics**: Cycle metrics
5. **Alert Policy**: Активная политика алёртов

### Как подключить

**Вариант A: Redis Exporter (Production)**

1. Deploy [redis_exporter](https://github.com/oliver006/redis_exporter):
```yaml
# docker-compose.yml
redis-exporter:
  image: oliver006/redis_exporter
  environment:
    REDIS_ADDR: redis:6379
  ports:
    - 9121:9121
```

2. Configure Prometheus:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
```

3. Import dashboard в Grafana

**Heartbeat metric:**
```promql
(time() - redis_key_timestamp{key=~".*:soak:runner:heartbeat"}) / 60
```

**Вариант B: Log-Based (Minimal)**

Если Redis exporter недоступен:

1. Ensure runner logs → Loki (via Promtail)
2. Import dashboard (heartbeat panel будет log-based)
3. Use Loki queries для мониторинга:

```logql
# Heartbeat log entries
{job="soak-runner"} |= "Heartbeat written"

# Absence alert
absent_over_time({job="soak-runner"} |= "Heartbeat written"[15m])
```

### Интерпретация панелей

**Heartbeat Age:**
- 🟢 0-5 min: Healthy
- 🟡 5-10 min: Degraded
- 🔴 >10 min: Critical

**Alert Debounce Status:**
- `ALERT_DEBOUNCED ... remaining_min=X` → следующий alert через X минут
- `ALERT_BYPASS_DEBOUNCE` → эскалация, debounce игнорирован

**Export Status:**
- `summary=OK violations=OK` → нормально
- `summary=SKIP reason=redis_unavailable` → Redis недоступен

### Quick Start

```bash
# Local: Import dashboard JSON
grafana-cli dashboard import ops/grafana/soak_runner_dashboard.json

# API
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Authorization: Bearer $API_KEY" \
  -d @ops/grafana/soak_runner_dashboard.json
```

**Подробности:** См. `ops/grafana/README.md`

---

## 🧪 Alert Self-Test CI (Daily)

### Назначение

Ежедневная автоматическая проверка цепочки алёртов:
1. Generate fake CRIT summary
2. Run continuous_runner
3. Verify alerts sent to Telegram/Slack
4. Upload artifacts

**Workflow:** `.github/workflows/alert-selftest.yml`

**Расписание:** Ежедневно в 07:07 UTC

### Что проверяется

✅ `generate_fake_summary.py` работает  
✅ Runner обрабатывает fake data  
✅ Alert routing по env работает  
✅ Redis export (опционально)  
✅ Telegram/Slack alerts delivery  

### Особенности self-test

**Безопасность:**
- Использует отдельный heartbeat key: `dev:bybit:soak:runner:selftest_heartbeat`
- Debounce отключён (`--alert-debounce-min 0`)
- TTL короткий (600s)
- **НЕ влияет на prod alert state**

**Артефакты:**
```
reports/analysis/SOAK_SUMMARY.json   # Fake CRIT
reports/analysis/VIOLATIONS.json     # Fake violations
artifacts/state/last_export_status.json
```

### Запуск вручную

**Локально:**
```bash
make soak-alert-selftest
```

**GitHub UI:**
1. Actions → Alert Self-Test (Daily)
2. Run workflow
3. Выбрать `verdict`: crit/warn/ok

**CLI:**
```bash
gh workflow run alert-selftest.yml -f verdict=crit
```

### Интерпретация результатов

**Success:**
- Workflow completes (green)
- Telegram/Slack получили alert
- Artifacts uploaded

**Failure scenarios:**
1. **Workflow fails** → проверить `generate_fake_summary.py` или runner
2. **No alert received** → проверить ENV vars (TELEGRAM_BOT_TOKEN, etc)
3. **Export status SKIP** → Redis недоступен (не критично для self-test)

### Мониторинг

**Check recent runs:**
```bash
gh run list --workflow=alert-selftest.yml --limit 5
```

**Download artifacts:**
```bash
gh run download <run-id> --name alert-selftest-<run-id>
```

**Verify в Grafana:**
- Dashboard → Alert Debounce Status
- Фильтр: `{job="soak-runner"} |= "selftest"`

---

## 🛠️ Makefile Quick Reference (Updated)

```bash
# Production
make soak-continuous          # Infinite loop (60 min intervals)
make soak-once                # Single cycle

# Dry-run testing
make soak-alert-dry           # Dry-run с debounce

# Self-test
make soak-alert-selftest      # Generate fake CRIT + run
make soak-qol-smoke           # QoL smoke test (debounce check)
make soak-qol-smoke-new-viol  # Signature bypass test

# Analysis
make soak-analyze             # Post-soak analyzer

# Redis
make soak-violations-redis    # Export violations
```

**ENV overrides:**
```bash
ENV=prod EXCHANGE=kucoin make soak-once
ALERT_POLICY="dev=WARN,prod=CRIT" make soak-alert-selftest
REDIS_URL=redis://localhost:6380/1 make soak-qol-smoke
```

---

## 🎯 Safety & Observability Pack

### Debounce Gauge (Prometheus Метрика)

**Назначение:** Real-time мониторинг оставшегося времени до следующего разрешённого алерта.

**Метрика:**
```promql
soak_alert_debounce_remaining_minutes{env="prod", exchange="bybit"}
```

**Значения:**
- `> 0` → debounce активен, алерты подавляются
- `== 0` → debounce неактивен или bypass
- Отсутствует → metrics не экспортируются

**Обновление:**
- При debounce: `remaining_min = debounce_min - elapsed_min`
- При bypass (severity increase): `0`
- При bypass (new violations signature): `0`
- При Redis недоступен: `0`

**Grafana Panel:**
```json
{
  "title": "Debounce Remaining (min)",
  "type": "stat",
  "targets": [{
    "expr": "soak_alert_debounce_remaining_minutes{env=\"$env\", exchange=\"$exchange\"}"
  }],
  "fieldConfig": {
    "thresholds": {
      "steps": [
        {"value": 0, "color": "green"},
        {"value": 60, "color": "yellow"},
        {"value": 120, "color": "red"}
      ]
    }
  }
}
```

**Alert Rules:**
```yaml
- alert: SoakRunnerDebounceStuck
  expr: changes(soak_alert_debounce_remaining_minutes[6h]) == 0 AND soak_alert_debounce_remaining_minutes > 0
  for: 5m
  annotations:
    summary: "Debounce gauge stuck (no change for 6h)"
```

**Интерпретация:**
- **0 min** → можно отправлять алерт
- **60 min** → ещё час до следующего алерта
- **180 min** → максимальное debounce время (3h)
- **Stuck (не меняется 6h)** → вероятно, bug или Redis state проблема

**Prometheus Exporter:**
- Runner должен экспортировать metrics в Redis
- Redis Exporter (опционально) → Prometheus → Grafana
- Альтернатива: Loki logs + LogQL (без Prometheus)

---

### Violation Signature Bypass (Smart Debounce)

**Назначение:** Bypass debounce если *состав* нарушений изменился, даже если severity остался тем же (CRIT→CRIT).

**Как работает:**

1. **Signature Computation:**
   ```python
   def compute_violations_signature(violations, top_k=5):
       # Берём top-K самых серьёзных
       top = sorted(violations, key=lambda v: (v['level'], v['symbol']))[:top_k]
       canonical = [f"{v['symbol']}:{v['metric']}:{v['window_index']}" for v in top]
       return hashlib.sha1("|".join(canonical).encode()).hexdigest()
   ```

2. **Comparison:**
   ```python
   current_signature = compute_violations_signature(violations)
   last_signature = redis.get("alert_key").get("last_signature", "")
   
   if current_signature != last_signature:
       logger.info("ALERT_BYPASS_DEBOUNCE reason=new_violations signature_changed=true")
       return True  # Send alert despite debounce
   ```

3. **Storage in Redis:**
   ```json
   {
     "last_sent_at": "2025-10-26T12:00:00Z",
     "last_level": "CRIT",
     "last_signature": "a1b2c3d4e5f6..."
   }
   ```

**Примеры:**

**Scenario 1: Same violations → DEBOUNCE**
```
12:00 - CRIT: [BTCUSDT edge_bps, BTCUSDT p95_latency]
12:30 - CRIT: [BTCUSDT edge_bps, BTCUSDT p95_latency] (same signature)
→ ALERT_DEBOUNCED remaining_min=150
```

**Scenario 2: New violations → BYPASS**
```
12:00 - CRIT: [BTCUSDT edge_bps, BTCUSDT p95_latency]
12:30 - CRIT: [ETHUSDT edge_bps, SOLUSDT maker_taker] (different signature)
→ ALERT_BYPASS_DEBOUNCE reason=new_violations signature_changed=true
```

**Конфигурация:**
- `top_k=5` (по умолчанию) в `compute_violations_signature()`
- Signature хранится в Redis (key: `{env}:{exchange}:soak:alert_state`)

**Тестирование:**
```bash
# Вариант 1: Same violations (debounce)
make soak-qol-smoke

# Вариант 2: Different violations (bypass)
make soak-qol-smoke-new-viol
```

---

### Redis Unavailable WARN Alert

**Назначение:** Автоматическое оповещение если Redis export стабильно не работает N циклов подряд.

**Условия отправки:**
- Redis export failed >= `--redis-down-max` consecutive cycles (default: 3)
- Отправка WARN alert (независимо от soak verdict)
- После успешного export — счётчик сбрасывается

**Формат сообщения:**
```
[🟡 WARN] Redis export skipped 3 cycles in a row

Env: dev
Exchange: bybit
Consecutive failures: 3
Last check: 2025-10-26T12:45:00Z

Redis may be unavailable. Check REDIS_URL and connectivity.
```

**Tracking:**
```json
// artifacts/state/last_export_status.json
{
  "timestamp": "2025-10-26T12:45:00Z",
  "status": "SKIP",
  "reason": "redis_unavailable",
  "consecutive_failures": 3
}
```

**Логика:**
```python
def check_redis_down_streak(export_status, state_dir):
    state_file = state_dir / "last_export_status.json"
    
    if export_status.get("status") == "SKIP" and "redis" in export_status.get("reason", ""):
        # Increment consecutive failures
        old_count = old_state.get("consecutive_failures", 0)
        new_count = old_count + 1
    else:
        # Reset on success
        new_count = 0
    
    return new_count
```

**Конфигурация:**
```bash
python -m tools.soak.continuous_runner \
  --redis-down-max 5 \     # Send WARN after 5 consecutive failures
  --alert telegram \        # Send to Telegram
  --verbose
```

**Troubleshooting:**
1. **Check Redis connectivity:**
   ```bash
   redis-cli -u "$REDIS_URL" PING
   ```

2. **Check state file:**
   ```bash
   cat artifacts/state/last_export_status.json
   ```

3. **Reset counter (если false positive):**
   ```bash
   echo '{"status":"OK","consecutive_failures":0}' > artifacts/state/last_export_status.json
   ```

**Prometheus Alert (optional):**
```yaml
- alert: SoakRedisExportDown
  expr: redis_export_fail_total{env="prod"} > 3
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Soak Redis export failing ({{ $labels.env }})"
```

---

### One-Shot Smoke Tests (QoL Pack)

**Назначение:** Быстрая проверка debounce логики и violation signature bypass в isolated режиме.

**Makefile Targets:**

#### `make soak-qol-smoke`
**Что делает:**
1. Generate fake CRIT (variant 1)
2. Run continuous_runner (должен отправить alert)
3. Run снова (должен DEBOUNCE — same violations)

**Ожидаемый вывод:**
```
Step 2: First run (should alert)
[INFO] ALERT_SENT verdict=CRIT severity_increased=False

Step 3: Second run (should DEBOUNCE - same violations)
[INFO] ALERT_DEBOUNCED level=CRIT remaining_min=180
```

**Использование:**
```bash
# Default: dev env, bybit exchange
make soak-qol-smoke

# Custom env
ENV=staging EXCHANGE=kucoin make soak-qol-smoke

# Custom Redis
REDIS_URL=redis://localhost:6380/1 make soak-qol-smoke
```

#### `make soak-qol-smoke-new-viol`
**Что делает:**
1. Generate fake CRIT (variant 2 — **different violations**)
2. Run continuous_runner (должен BYPASS debounce → `signature_changed=true`)

**Ожидаемый вывод:**
```
[INFO] ALERT_BYPASS_DEBOUNCE prev=CRIT new=CRIT reason=new_violations signature_changed=true
```

**Сравнение violations:**
```
# Variant 1:
BTCUSDT edge_bps (window 23)
BTCUSDT p95_latency_ms (window 24)
ETHUSDT maker_taker_ratio (window 24)

# Variant 2 (different signature):
BTCUSDT edge_bps (window 24)  ← другой window
BTCUSDT maker_taker_ratio (window 24)  ← другая метрика
SOLUSDT edge_bps (window 23)  ← другой symbol
```

**Вариант генератора:**
```bash
# Variant 1 (default)
python -m tools.soak.generate_fake_summary --crit --out reports/analysis --variant 1

# Variant 2 (new signature)
python -m tools.soak.generate_fake_summary --crit --out reports/analysis --variant 2
```

**Тестовый сценарий:**
```bash
# 1. Clean state
redis-cli DEL "dev:bybit:soak:alert_state"

# 2. First alert (variant 1)
make soak-qol-smoke
# → ALERT_SENT

# 3. Same violations (should debounce)
make soak-qol-smoke
# → ALERT_DEBOUNCED remaining_min=180

# 4. New violations (should bypass)
make soak-qol-smoke-new-viol
# → ALERT_BYPASS_DEBOUNCE signature_changed=true
```

**Isolation от Production:**
- Uses `reports/analysis/FAKE_*.json` (fake glob pattern)
- Separate Redis heartbeat key: `dev:bybit:soak:runner:heartbeat`
- Short TTL (600s)
- Can use `--dry-run` for no-op alerts

**Debugging:**
```bash
# Check Redis state
redis-cli GET "dev:bybit:soak:alert_state"

# Check last signature
redis-cli GET "dev:bybit:soak:alert_state" | jq .last_signature

# Clear state (для повторного теста)
redis-cli DEL "dev:bybit:soak:alert_state"
```

**Acceptance Criteria:**
✅ `soak-qol-smoke` → ALERT_SENT (1st), ALERT_DEBOUNCED (2nd)  
✅ `soak-qol-smoke-new-viol` → ALERT_BYPASS_DEBOUNCE signature_changed=true  
✅ Prometheus gauge `soak_alert_debounce_remaining_minutes` updates  
✅ Redis state includes `last_signature`  

---

**Questions? Contact:** [dima@example.com](mailto:dima@example.com)

**CI Status:** ![CI](https://github.com/user/mm-bot/workflows/CI/badge.svg)

