# Prometheus Alert Rules

This directory contains Prometheus alert rule definitions for monitoring the MM-Rebate Bot.

## Files

- **`shadow_rules.yml`**: Alert rules for Shadow Mode KPIs

## Usage

### 1. Install Rules

Copy rules to Prometheus configuration directory:

```bash
# Example: copy to Prometheus rules directory
cp ops/alerts/shadow_rules.yml /etc/prometheus/rules/

# Update prometheus.yml to include rules
cat >> /etc/prometheus/prometheus.yml <<EOF
rule_files:
  - "rules/shadow_rules.yml"
EOF
```

### 2. Reload Prometheus

```bash
# Method 1: Send HUP signal
kill -HUP $(pgrep prometheus)

# Method 2: Use reload endpoint (if --web.enable-lifecycle enabled)
curl -X POST http://localhost:9090/-/reload
```

### 3. Verify Rules

```bash
# Check rules are loaded
curl http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name=="shadow.mode.rules")'

# View active alerts
curl http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.component=="shadow")'
```

## Shadow Mode Alerts

| Alert | Threshold | Duration | Severity | Description |
|-------|-----------|----------|----------|-------------|
| **ShadowEdgeLow** | avg(edge_bps) < 2.5 | 10m | warning | Edge below target |
| **ShadowMakerLow** | avg(maker_taker) < 0.83 | 10m | warning | Maker ratio too low |
| **ShadowLatencyHigh** | avg(latency_ms) > 350 | 10m | warning | Latency too high |
| **ShadowRiskHigh** | avg(risk_ratio) > 0.40 | 10m | warning | Risk above limit |
| **ShadowClockDriftHigh** | avg(clock_drift) > 500ms | 5m | warning | Clock sync issues |
| **ShadowMetricsMissing** | absent(shadow_*) | 5m | critical | Feed down |

## Alert Routing

### Example Alertmanager Config

```yaml
route:
  group_by: ['alertname', 'component']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
  receiver: 'default'
  
  routes:
  - match:
      component: shadow
      severity: critical
    receiver: 'pagerduty'
  
  - match:
      component: shadow
      severity: warning
    receiver: 'slack'

receivers:
- name: 'slack'
  slack_configs:
  - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
    channel: '#mm-bot-alerts'
    title: 'Shadow Mode Alert'
    text: '{{ .CommonAnnotations.description }}'

- name: 'pagerduty'
  pagerduty_configs:
  - service_key: 'YOUR_PAGERDUTY_KEY'
```

## Metric Exporter

Shadow mode metrics are exported via Prometheus client in `tools/shadow/run_shadow.py`.

**Exported Metrics:**
- `shadow_edge_bps{symbol="BTCUSDT"}`: Net edge
- `shadow_maker_taker_ratio{symbol="BTCUSDT"}`: Maker/taker ratio
- `shadow_latency_ms{symbol="BTCUSDT"}`: P95 latency
- `shadow_risk_ratio{symbol="BTCUSDT"}`: Risk ratio
- `shadow_clock_drift_ms{symbol="BTCUSDT"}`: Clock drift EWMA

## Troubleshooting

### Alert Firing but Shadow Running Fine

Check evaluation window:
```promql
# Query last 15m average
avg_over_time(shadow_edge_bps[15m])
```

If recent values are OK but alert still firing, it's averaging in older bad values.

### Alert Not Firing when Expected

1. Check metric is being scraped:
   ```promql
   shadow_edge_bps
   ```

2. Check alert is active:
   ```promql
   ALERTS{alertname="ShadowEdgeLow"}
   ```

3. Check evaluation interval matches rule group interval (30s)

### Silence Alerts

```bash
# Silence ShadowEdgeLow for 1 hour
amtool silence add alertname=ShadowEdgeLow --duration=1h --comment="Maintenance window"
```

## Testing Alerts

### Simulate Low Edge

```bash
# Run shadow with aggressive profile (tighter spreads = lower edge)
python -m tools.shadow.run_shadow --profile aggressive --iterations 100
```

### Simulate High Latency

```bash
# Simulate network delay (requires tc/netem)
sudo tc qdisc add dev eth0 root netem delay 400ms
python -m tools.shadow.run_shadow --iterations 20
sudo tc qdisc del dev eth0 root
```

## References

- [Prometheus Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Shadow Mode Guide](../../SHADOW_MODE_GUIDE.md)

