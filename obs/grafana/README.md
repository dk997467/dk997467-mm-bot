# MM-Bot Grafana Dashboard

## Overview

Production-grade Grafana dashboard for monitoring MM-Bot in testnet and live deployments.

**Dashboard ID**: `MMBot_Dashboard.json`

## Panels

1. **Reconciliation Divergences (by type)** — Critical operational metric
   - Tracks `mm_recon_divergence_total` by type
   - Alert threshold: any increase > 0 in 10m
   - Types: `orders_local_only`, `orders_remote_only`, `position_mismatch`

2. **Maker/Taker Ratio** — Fee efficiency
   - Target: ≥ 85% (paying mostly maker fees, not taker)
   - Alert threshold: < 0.85 for 30m

3. **Net PnL (BPS)** — Strategy profitability
   - Net basis points after fees/rebates
   - Alert threshold: < 0 for 30m (losing money)

4. **Orders Blocked (by reason)** — Execution quality
   - Reasons: `cross_price`, `min_qty`, `risk_limit`, `maker_only`
   - Stacked view to identify most common blockers

5. **Symbol Filters Source (stacked)** — API health
   - Sources: `cached`, `fetched`, `default_fallback`
   - High `default_fallback` rate indicates exchange API issues

6. **Freeze Events** — Safety mechanism activation
   - Counts by reason: `edge_too_low`, `max_inventory`, `max_notional`
   - Normal: occasional freezes due to market conditions
   - Abnormal: frequent freezes due to config or bugs

7. **Kill-Switch Status (Live Enable)** — Safety override
   - `0` = Shadow mode (safe)
   - `1` = Live mode (real trading)
   - CRITICAL: if `1` and bot down → orphan orders risk

8. **Exchange Latency (histogram)** — Performance monitoring
   - Heatmap of `mm_exchange_latency_ms_bucket`
   - Target: < 100ms p99

9. **Symbol Filters Fetch Errors** — API reliability
   - Alert threshold: any errors in 15m

10. **Cache Hit Rate** — Efficiency metric
    - Target: ≥ 80% (filters cached, not fetched every time)

## Import Steps

### Prerequisites
- Grafana instance (≥ v8.0)
- Prometheus data source configured
- MM-Bot exposing `/metrics` endpoint (requires `--obs` flag)

### Import Dashboard

1. **Open Grafana UI**
   ```
   http://your-grafana-instance:3000
   ```

2. **Navigate to Dashboards → Import**
   - Click `+` (top-left)
   - Select "Import"

3. **Upload JSON**
   - Click "Upload JSON file"
   - Select `obs/grafana/MMBot_Dashboard.json`
   - OR paste JSON content directly

4. **Configure Data Source**
   - Select Prometheus data source from dropdown
   - Click "Import"

5. **Verify Panels**
   - All panels should display (some may be empty if no data yet)
   - Check for "No data" vs "Error" (error = misconfigured metric names)

### Configure Alerts (Optional)

If using Grafana alerting (not Prometheus Alertmanager):

1. **Enable Alerting on Panels**
   - Click panel title → Edit
   - Navigate to "Alert" tab
   - Configure notification channels

2. **Recommended Alert Channels**
   - PagerDuty (for critical alerts)
   - Slack (for warnings)
   - Email (for info)

### Prometheus Data Source Setup

If Prometheus not yet configured:

1. **Add Prometheus Data Source**
   - Settings → Data Sources → Add data source
   - Select "Prometheus"
   - URL: `http://localhost:9090` (or your Prometheus instance)
   - Access: "Server" (if Grafana and Prometheus on same network)
   - Click "Save & Test"

2. **Verify Scrape Config**
   Ensure Prometheus is scraping MM-Bot metrics:

   ```yaml
   # prometheus.yml
   scrape_configs:
     - job_name: 'mm-bot'
       static_configs:
         - targets: ['localhost:8080']  # --obs-port 8080
       scrape_interval: 10s
   ```

3. **Reload Prometheus**
   ```bash
   curl -X POST http://localhost:9090/-/reload
   # OR restart Prometheus
   ```

## Dashboard Usage

### Testnet Soak Testing

Monitor these panels during 24–48h testnet soak:

- ✅ **Recon Divergences** — should be 0 (any divergence = investigation required)
- ✅ **Maker/Taker Ratio** — should be ≥ 0.85 (mostly maker fills)
- ✅ **Net PnL** — should be positive or near-zero (not losing money)
- ⚠️ **Orders Blocked** — moderate blocking OK (means safety checks working)
- ⚠️ **Freeze Events** — occasional freezes OK (edge-driven), frequent = problem
- ❌ **Kill-Switch** — MUST be 0 (shadow) during testnet

### Canary Live Launch

Before enabling live mode:

1. **Verify Clean State**
   - Recon divergences = 0
   - No freeze events in last 1h (except edge-driven)
   - Cache hit rate > 80%
   - Latency p99 < 100ms

2. **Enable Live Mode**
   ```bash
   export MM_LIVE_ENABLE=1
   python -m tools.live.exec_demo --shadow --live --symbols BTCUSDT --max-inv 500 --obs --obs-port 8080
   ```

3. **Monitor Closely (first 1h)**
   - Watch kill-switch panel: should show `1` (live)
   - Recon divergences: if any appear → STOP and investigate
   - Net PnL: should be positive or flat
   - Latency: should remain < 100ms

4. **Go/No-Go After 1h**
   - ✅ Go: no divergences, positive net_bps, stable latency
   - ❌ No-Go: any critical alert fires → rollback to shadow

### Troubleshooting

#### Panel shows "No data"
- Check Prometheus scrape config
- Verify MM-Bot is running with `--obs` flag
- Check `/metrics` endpoint: `curl http://localhost:8080/metrics`

#### Panel shows "Error: metric not found"
- Verify metric names match `tools/obs/metrics.py`
- Check Prometheus query syntax in panel edit mode
- Ensure MM-Bot version includes P0.10+ metrics

#### Alerts not firing
- Check Prometheus alert rules: `obs/prometheus/alerts_mm_bot.yml`
- Verify Alertmanager config (if using separate Alertmanager)
- Test alert: temporarily lower threshold to trigger

#### High "default_fallback" rate
- Exchange API down or rate-limited
- Network connectivity issues
- Check `mm_symbol_filters_fetch_errors_total` for error reasons

## References

- [RUNBOOK_SHADOW.md](../../RUNBOOK_SHADOW.md) — Operational runbook (P0.10 section)
- [RECON_OPERATIONS.md](../../RECON_OPERATIONS.md) — Reconciliation triage guide
- [obs/prometheus/alerts_mm_bot.yml](../prometheus/alerts_mm_bot.yml) — Alert rules
- [tools/obs/metrics.py](../../tools/obs/metrics.py) — Metric definitions

## Support

For dashboard issues or feature requests, see project README or contact quant-infra team.

