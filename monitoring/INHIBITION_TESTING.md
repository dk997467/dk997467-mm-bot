# Inhibition Testing Guide

This guide explains how to test the alert inhibition rules to ensure they work correctly in your environment.

## Overview

The MM Bot alerting system uses intelligent inhibition rules to prevent alert spam and focus attention on root causes. This guide provides step-by-step instructions for testing each inhibition rule.

## Prerequisites

- Prometheus running and accessible
- Alertmanager running and accessible
- MM Bot metrics endpoint accessible
- Basic understanding of curl commands

## Testing Environment Setup

### 1. Set Environment Variable
```bash
# Set environment for testing
export ENV=test

# Verify it's set
echo $ENV
```

### 2. Verify Services
```bash
# Check Prometheus
curl http://localhost:9090/-/healthy

# Check Alertmanager
curl http://localhost:9093/-/healthy

# Check MM Bot metrics
curl http://localhost:8080/metrics | head -5
```

## Inhibition Rules to Test

### Rule 1: RiskPaused Inhibits Warning Alerts

**What it does**: When `RiskPaused` is firing, it inhibits:
- `CancelRateNearLimit`
- `RejectRateHigh`
- `QueuePositionDegraded`

**Test Steps**:
```bash
# 1. Trigger RiskPaused alert
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"

# 2. Wait for alert to fire (check Prometheus UI)
# Navigate to http://localhost:9090/alerts
# Look for RiskPaused in FIRING state

# 3. Try to trigger CancelRateNearLimit
curl -X POST http://localhost:8080/metrics/cancel_rate -d "0.95"

# 4. Check if CancelRateNearLimit is inhibited
curl "http://localhost:9093/api/v1/alerts" | grep -A 10 "CancelRateNearLimit"

# 5. Check inhibition status
curl "http://localhost:9093/api/v1/inhibits"

# 6. Resolve RiskPaused
curl -X POST http://localhost:8080/metrics/risk_paused -d "0"

# 7. Verify CancelRateNearLimit can now fire
# Wait for RiskPaused to resolve, then check if CancelRateNearLimit fires
```

**Expected Results**:
- RiskPaused should fire normally
- CancelRateNearLimit should be inhibited while RiskPaused is firing
- After RiskPaused resolves, CancelRateNearLimit should fire if conditions are met

### Rule 2: HighLatencyREST Inhibits RejectRateHigh

**What it does**: When `HighLatencyREST` is firing, it inhibits `RejectRateHigh` (likely related to latency issues).

**Test Steps**:
```bash
# 1. Trigger HighLatencyREST alert
# This requires setting up a metric that triggers the latency alert
# For testing, you might need to modify the metric directly

# 2. Wait for HighLatencyREST to fire

# 3. Try to trigger RejectRateHigh
curl -X POST http://localhost:8080/metrics/rest_error_rate -d "0.05"

# 4. Check if RejectRateHigh is inhibited
curl "http://localhost:9093/api/v1/alerts" | grep -A 10 "RejectRateHigh"

# 5. Check inhibition status
curl "http://localhost:9093/api/v1/inhibits"
```

**Expected Results**:
- HighLatencyREST should fire normally
- RejectRateHigh should be inhibited while HighLatencyREST is firing

### Rule 3: CircuitBreakerOpen Inhibits Related Alerts

**What it does**: When `CircuitBreakerOpen` is firing, it inhibits:
- `AmendFailureRateHigh`
- `HighBackoffTime`

**Test Steps**:
```bash
# 1. Trigger CircuitBreakerOpen alert
curl -X POST http://localhost:8080/metrics/circuit_breaker_state -d "1"

# 2. Wait for alert to fire

# 3. Try to trigger AmendFailureRateHigh
# This requires setting up amend metrics

# 4. Try to trigger HighBackoffTime
# This requires setting up backoff metrics

# 5. Check inhibition status
curl "http://localhost:9093/api/v1/inhibits"

# 6. Resolve CircuitBreakerOpen
curl -X POST http://localhost:8080/metrics/circuit_breaker_state -d "0"
```

**Expected Results**:
- CircuitBreakerOpen should fire normally
- AmendFailureRateHigh and HighBackoffTime should be inhibited
- After CircuitBreakerOpen resolves, other alerts should fire if conditions are met

## Verification Commands

### Check Alert Status
```bash
# View all active alerts
curl "http://localhost:9093/api/v1/alerts"

# View specific alert
curl "http://localhost:9093/api/v1/alerts" | grep -A 15 "AlertName"

# Check Prometheus rules
curl "http://localhost:9090/api/v1/rules"
```

### Check Inhibition Status
```bash
# View all inhibitions
curl "http://localhost:9093/api/v1/inhibits"

# Check specific inhibition
curl "http://localhost:9093/api/v1/inhibits" | grep -A 10 "source"

# View Alertmanager status
curl "http://localhost:9093/api/v1/status"
```

### Check Environment Labels
```bash
# Verify env labels in Prometheus
curl "http://localhost:9090/api/v1/rules" | grep -o 'env.*test'

# Verify env labels in Alertmanager
curl "http://localhost:9093/api/v1/alerts" | grep -A 5 "env.*test"
```

## Troubleshooting

### Common Issues

1. **Inhibition not working**:
   - Check if source alert is actually firing
   - Verify `equal` fields match exactly
   - Check Alertmanager logs for errors

2. **Alerts not firing**:
   - Verify metric names and expressions
   - Check if metrics have values
   - Ensure `for:` duration has passed

3. **Environment labels missing**:
   - Verify ENV variable is set
   - Check Prometheus configuration
   - Restart Prometheus after ENV changes

### Debug Commands
```bash
# Check Alertmanager logs
sudo journalctl -u alertmanager -f

# Check Prometheus logs
sudo journalctl -u prometheus -f

# Test metric endpoint
curl http://localhost:8080/metrics | grep -E "(risk_paused|circuit_breaker)"

# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('monitoring/alertmanager.yml', 'r'))"
```

## Testing Checklist

- [ ] Environment variable set correctly
- [ ] All services running and healthy
- [ ] RiskPaused inhibition tested
- [ ] HighLatencyREST inhibition tested
- [ ] CircuitBreakerOpen inhibition tested
- [ ] Environment labels verified
- [ ] Inhibition status checked
- [ ] Alerts resolve properly after source alert resolves

## Next Steps

After testing inhibition rules:

1. **Production Deployment**: Deploy to production environment
2. **Monitor Effectiveness**: Watch for false positives/negatives
3. **Adjust Rules**: Modify inhibition rules based on production experience
4. **Team Training**: Train team on how inhibition affects alerting
5. **Documentation**: Update runbooks with inhibition information

## Support

For issues with inhibition testing:
1. Check Alertmanager logs for errors
2. Verify metric values and expressions
3. Test inhibition rules one at a time
4. Use Alertmanager UI for visual debugging
5. Consult the main README.md for general troubleshooting
