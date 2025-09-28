# Monitoring & Alerting

This directory contains monitoring configuration and alerting rules for the Market Maker Bot.

## Structure

```
monitoring/
├── README.md                 # This file
├── DEPLOYMENT.md            # Deployment guide
├── COMPONENTS.md            # Components overview
├── prometheus.yml            # Example Prometheus configuration (production)
├── prometheus.staging.yml    # Example Prometheus configuration (staging)
├── alertmanager.yml          # Example Alertmanager configuration
├── alerts/
│   └── mm_bot.rules.yml     # Alert rules for Prometheus
├── templates/                # Notification templates
│   ├── slack.tmpl           # Slack notification template
│   └── pagerduty.tmpl      # PagerDuty notification template
└── grafana/
    └── dashboards/
        └── mm-bot-alerts.json # Example Grafana dashboard
```

## Quick Start

### 1. Enable Alerting

Copy the alert rules to your Prometheus configuration:

```bash
# Copy rules to Prometheus rules directory
cp alerts/mm_bot.rules.yml /etc/prometheus/rules/

# Or add to your existing prometheus.yml
rule_files:
  - "rules/mm_bot.rules.yml"
```

### 2. Set Environment via Prometheus Configuration

**Important**: Do NOT use `${ENV:-prod}` in alert rules. Set environment via Prometheus `external_labels`:

```yaml
# In prometheus.yml
global:
  external_labels:
    service: "mm-bot"
    env: "prod"     # Set your environment here

# For staging, use prometheus.staging.yml
global:
  external_labels:
    service: "mm-bot"
    env: "staging"
```

**Environment Configuration Options**:

1. **Use different config files per environment**:
   ```bash
   # Production
   cp monitoring/prometheus.yml /etc/prometheus/
   
   # Staging
   cp monitoring/prometheus.staging.yml /etc/prometheus/
   ```

2. **Override at startup**:
   ```bash
   # Production
   prometheus --config.file=/etc/prometheus/prometheus.yml
   
   # Staging
   prometheus --config.file=/etc/prometheus/prometheus.staging.yml
   ```

3. **Docker/Container**:
   ```bash
   # Production
   docker run -v /etc/prometheus:/etc/prometheus prom/prometheus
   
   # Staging
   docker run -v /etc/prometheus:/etc/prometheus prom/prometheus \
     --config.file=/etc/prometheus/prometheus.staging.yml
   ```

### 3. Reload Prometheus

```bash
# Reload configuration
curl -X POST http://localhost:9090/-/reload

# Or restart Prometheus service
sudo systemctl reload prometheus
```

### 4. Verify Rules and Labels

Check that rules are loaded with correct labels:

```bash
# View loaded rules
curl http://localhost:9090/api/v1/rules

# Check specific rule group
curl http://localhost:9090/api/v1/rules?rule_group=mm_bot_alerts

# Verify external labels are applied
curl "http://localhost:9090/api/v1/rules" | grep -A 5 "env.*prod"
```

## Alert Rules

### Common Labels

All alerts include consistent labeling:
- `service: "mm-bot"` - Identifies the service (from rule labels)
- `env: "prod"` - Environment (from Prometheus external_labels)
- `severity: "critical|warning|info"` - Alert importance

**Note**: The `env` label comes from Prometheus `external_labels`, not from individual rule labels. This ensures consistency and allows environment switching without modifying rule files.

### Critical Alerts (Immediate Action Required)

- **RiskPaused**: Bot paused by risk management
- **CircuitBreakerOpen**: Circuit breaker is open
- **HighLatencyREST**: REST p95 latency >300ms
- **DrawdownDay**: Daily drawdown beyond limits
- **OrderManagerUnhealthy**: Bot is down

### Warning Alerts (Monitor Closely)

- **RejectRateHigh**: REST error rate >2%
- **CancelRateNearLimit**: Cancel rate approaching limits (5m threshold)
- **AmendFailureRateHigh**: Amend failure rate >10%
- **QueuePositionDegraded**: Queue position degraded
- **HighBackoffTime**: High backoff time accumulation

### Info Alerts

- **LowMakerShare**: Placeholder for future maker share metrics

## Alert Inhibition

The system uses intelligent inhibition rules to reduce alert noise:

### Inhibition Rules

1. **Risk Paused Inhibits Warnings**: When `RiskPaused` is firing, it inhibits:
   - `CancelRateNearLimit`
   - `RejectRateHigh`
   - `QueuePositionDegraded`

2. **High Latency Inhibits Errors**: When `HighLatencyREST` is firing, it inhibits:
   - `RejectRateHigh` (likely related to latency issues)

3. **Circuit Breaker Inhibits Related**: When `CircuitBreakerOpen` is firing, it inhibits:
   - `AmendFailureRateHigh`
   - `HighBackoffTime`

### Benefits

- **Reduces Alert Fatigue**: Prevents multiple related alerts from firing simultaneously
- **Focuses Attention**: Teams focus on root cause rather than symptoms
- **Logical Grouping**: Related issues are grouped under primary alerts
- **Environment Isolation**: Alerts are inhibited only within the same service/env

## Configuration

### Prometheus Configuration

Use the provided configuration files as starting points:

**Production** (`prometheus.yml`):
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    service: "mm-bot"
    env: "prod"

rule_files:
  - "alerts/mm_bot.rules.yml"
```

**Staging** (`prometheus.staging.yml`):
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    service: "mm-bot"
    env: "staging"

rule_files:
  - "alerts/mm_bot.rules.yml"
```

### Environment Variables

**Do not set ENV variable for alert rules**. Instead, use different Prometheus configuration files:

```bash
# Production deployment
cp monitoring/prometheus.yml /etc/prometheus/

# Staging deployment  
cp monitoring/prometheus.staging.yml /etc/prometheus/

# Or use command line override
prometheus --config.file=/path/to/prometheus.staging.yml
```

### Alertmanager Integration

For notification delivery, configure Alertmanager:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093
```

Use the provided `alertmanager.yml` and templates for:
- Slack notifications
- PagerDuty integration
- Alert grouping and inhibition
- Environment-aware routing

## Testing Alerts

### Manual Testing

Test alerts by temporarily modifying metrics:

```bash
# Test risk pause alert
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"

# Test circuit breaker alert
curl -X POST http://localhost:8080/metrics/circuit_breaker_state -d "1"

# Test high error rate
curl -X POST http://localhost:8080/metrics/rest_error_rate -d "0.05"
```

### Testing Inhibition

To test inhibition rules:

```bash
# 1. Trigger a source alert (e.g., RiskPaused)
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"

# 2. Wait for alert to fire (check Prometheus UI)

# 3. Trigger a target alert (e.g., CancelRateNearLimit)
# This should be inhibited if RiskPaused is firing

# 4. Check Alertmanager UI for inhibition status

# 5. Resolve the source alert
curl -X POST http://localhost:8080/metrics/risk_paused -d "0"

# 6. The target alert should now fire if conditions are met
```

### Automated Testing

Run the test suite to verify alert conditions:

```bash
# Test YAML syntax and structure
python -m pytest tests/test_alerts_yaml.py -v

# Test alert firing conditions
python -m pytest tests/test_alerts_firing.py -v

# Test alert integration
python -m pytest tests/test_alerts_integration.py -v
```

## Customization

### Modifying Thresholds

Edit `alerts/mm_bot.rules.yml` to adjust thresholds:

```yaml
- alert: CustomThreshold
  expr: your_metric > 0.5  # Adjust threshold here
  for: 5m
  labels:
    severity: "warning"
    service: "mm-bot"  # Keep this consistent
  annotations:
    summary: "Custom alert description"
    description: "Detailed description of the alert"
    runbook_url: "https://runbook.example.com/mm-bot/custom-alert"
    grafana_panel: "https://grafana.example.com/d/mm-bot/panel"
```

### Adding New Alerts

Add new alert rules to the `mm_bot_alerts` group:

```yaml
- alert: NewAlert
  expr: new_metric > threshold
  for: 10m
  labels:
    severity: "warning"
    service: "mm-bot"  # Keep this consistent
  annotations:
    summary: "New alert description"
    description: "Detailed description of the alert"
    runbook_url: "https://runbook.example.com/mm-bot/new-alert"
    grafana_panel: "https://grafana.example.com/d/mm-bot/panel"
```

**Important**: Do not add `env` labels to rules. The environment label comes from Prometheus `external_labels`.

### Custom Inhibition Rules

Add custom inhibition rules in `alertmanager.yml`:

```yaml
inhibit_rules:
  - source_matchers:
      - alertname: "YourSourceAlert"
    target_matchers:
      - alertname: "YourTargetAlert"
    equal: ["service", "env"]  # env comes from external_labels
```

## Integration

### Grafana Dashboards

Import the provided `grafana/dashboards/mm-bot-alerts.json` or create custom dashboards using the same PromQL expressions.

### External Monitoring

Integrate with external monitoring systems:

- **PagerDuty**: For incident management
- **Slack/Discord**: For team notifications
- **Email**: For critical alerts
- **SMS**: For urgent issues

## Best Practices

1. **Start with conservative thresholds** and adjust based on production data
2. **Use appropriate severity levels** to avoid alert fatigue
3. **Document runbooks** for each alert type
4. **Regular review** of alert effectiveness and false positives
5. **Test alerts** in development before deploying to production
6. **Use alert inhibition** to prevent alert spam
7. **Group related alerts** for better organization
8. **Set environment via Prometheus external_labels** (not ENV variables)
9. **Use different config files** for different environments
10. **Monitor inhibition effectiveness** to ensure it's working as expected

## Troubleshooting

### Common Issues

1. **Rules not loading**: Check file path and permissions
2. **Alerts not firing**: Verify metric names and expressions
3. **YAML syntax errors**: Use `python -c "import yaml; yaml.safe_load(open('file.yml'))"`
4. **Inhibition not working**: Check matcher syntax and equal fields
5. **Environment labels missing**: Verify external_labels in Prometheus config
6. **${ENV} in rules**: Remove shell substitution, use external_labels instead

### Debugging

1. **Check Prometheus logs** for rule loading errors
2. **Verify metrics exist** at `/metrics` endpoint
3. **Test expressions** in Prometheus query interface
4. **Use Alertmanager UI** to debug notification delivery
5. **Check inhibition status** in Alertmanager UI

### Environment Label Issues

```bash
# Check if external_labels are set
curl "http://localhost:9090/api/v1/status/config" | grep -A 10 "external_labels"

# Verify env labels in rules
curl "http://localhost:9090/api/v1/rules" | grep -o 'env.*prod'

# Check Prometheus configuration
curl "http://localhost:9090/api/v1/status/config"
```

### Inhibition Debugging

To debug inhibition rules:

```bash
# Check Alertmanager status
curl http://localhost:9093/api/v1/status

# View active alerts
curl http://localhost:9093/api/v1/alerts

# Check inhibition status
curl http://localhost:9093/api/v1/inhibits
```

## Production Deployment

See `DEPLOYMENT.md` for detailed production deployment instructions including:
- Environment-specific configuration
- Notification channel setup
- Runbook creation
- Team training procedures
- Inhibition rule validation
- External labels configuration
