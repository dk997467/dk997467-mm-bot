# Alerting Deployment Guide

## Quick Deployment

### 1. Copy Alert Rules
```bash
# Copy to Prometheus rules directory
cp monitoring/alerts/mm_bot.rules.yml /etc/prometheus/rules/

# Or use relative path in your prometheus.yml
rule_files:
  - "rules/mm_bot.rules.yml"
```

### 2. Set Environment Variable
```bash
# Set environment (defaults to 'prod' if not set)
export ENV=production

# Or in your systemd service file
Environment=ENV=production

# Or in your docker-compose.yml
environment:
  - ENV=production
```

### 3. Update Prometheus Config
```bash
# Use provided example or merge with existing config
cp monitoring/prometheus.yml /etc/prometheus/
```

### 4. Configure Alertmanager
```bash
# Copy Alertmanager configuration
cp alertmanager.yml /etc/alertmanager/

# Copy notification templates
cp -r templates/ /etc/alertmanager/
```

### 5. Reload Services
```bash
# Reload Prometheus configuration
curl -X POST http://localhost:9090/-/reload

# Restart Alertmanager
sudo systemctl restart alertmanager

# Or restart services
sudo systemctl reload prometheus
sudo systemctl reload alertmanager
```

## Verification

### Check Rules Loaded
```bash
# View loaded rules
curl http://localhost:9090/api/v1/rules

# Check specific group
curl "http://localhost:9090/api/v1/rules?rule_group=mm_bot_alerts"

# Verify environment labels
curl "http://localhost:9090/api/v1/rules" | grep -A 5 "env.*prod"
```

### Check Alertmanager Status
```bash
# View Alertmanager status
curl http://localhost:9093/api/v1/status

# Check inhibition rules
curl http://localhost:9093/api/v1/inhibits

# View active alerts
curl http://localhost:9093/api/v1/alerts
```

### Test Alert Firing
```bash
# Test risk pause alert
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"

# Test circuit breaker alert
curl -X POST http://localhost:8080/metrics/circuit_breaker_state -d "1"

# Test high error rate
curl -X POST http://localhost:8080/metrics/rest_error_rate -d "0.05"
```

### Test Inhibition Rules
```bash
# 1. Trigger source alert (RiskPaused)
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"

# 2. Wait for alert to fire (check Prometheus UI)

# 3. Trigger target alert (CancelRateNearLimit)
# This should be inhibited if RiskPaused is firing

# 4. Check Alertmanager UI for inhibition status

# 5. Resolve source alert
curl -X POST http://localhost:8080/metrics/risk_paused -d "0"

# 6. Target alert should now fire if conditions are met
```

## Production Checklist

- [ ] Alert thresholds adjusted for production environment
- [ ] Environment variable set (ENV=production)
- [ ] Notification channels configured (Slack, PagerDuty, etc.)
- [ ] Runbooks created for each alert type
- [ ] Team trained on alert response procedures
- [ ] False positive analysis completed
- [ ] Alert fatigue prevention measures in place
- [ ] Inhibition rules tested and validated
- [ ] Environment labels verified in Prometheus
- [ ] Alertmanager templates deployed
- [ ] Notification delivery tested

## Inhibition Rules

### What Gets Inhibited

1. **RiskPaused inhibits**:
   - CancelRateNearLimit
   - RejectRateHigh
   - QueuePositionDegraded

2. **HighLatencyREST inhibits**:
   - RejectRateHigh

3. **CircuitBreakerOpen inhibits**:
   - AmendFailureRateHigh
   - HighBackoffTime

### Testing Inhibition

```bash
# Test RiskPaused inhibition
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"
# Wait for alert to fire
# Try to trigger CancelRateNearLimit - should be inhibited

# Test CircuitBreaker inhibition
curl -X POST http://localhost:8080/metrics/circuit_breaker_state -d "1"
# Wait for alert to fire
# Try to trigger AmendFailureRateHigh - should be inhibited
```

## Troubleshooting

### Common Issues

1. **Rules not loading**: Check file permissions and paths
2. **Alerts not firing**: Verify metric names and expressions
3. **High false positive rate**: Adjust thresholds based on production data
4. **Inhibition not working**: Check matcher syntax and equal fields
5. **Environment labels missing**: Verify ENV variable is set
6. **Notifications not sending**: Check Alertmanager configuration and templates

### Debug Commands

```bash
# Check Prometheus logs
sudo journalctl -u prometheus -f

# Check Alertmanager logs
sudo journalctl -u alertmanager -f

# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('rules.yml', 'r'))"

# Test PromQL expressions in Prometheus UI
# Navigate to http://localhost:9090/graph

# Check inhibition status
curl http://localhost:9093/api/v1/inhibits

# View Alertmanager UI
# Navigate to http://localhost:9093
```

### Environment Variable Issues

```bash
# Check if ENV is set
echo $ENV

# Set if missing
export ENV=production

# Verify in Prometheus
curl "http://localhost:9090/api/v1/rules" | grep -o 'env.*prod'

# Check systemd service file
sudo systemctl cat prometheus | grep Environment
```

### Inhibition Debugging

```bash
# Check source alerts
curl "http://localhost:9093/api/v1/alerts" | grep -A 5 "RiskPaused"

# Check target alerts
curl "http://localhost:9093/api/v1/alerts" | grep -A 5 "CancelRateNearLimit"

# Check inhibition status
curl "http://localhost:9093/api/v1/inhibits"

# View Alertmanager UI for visual confirmation
# Navigate to http://localhost:9093
```
