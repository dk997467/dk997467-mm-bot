# Alerting System Components

## Overview

This document describes all components of the MM Bot alerting system that have been created, tested, and enhanced with advanced features.

## Core Components

### 1. Alert Rules (`alerts/mm_bot.rules.yml`)

**Purpose**: Define when and how alerts should fire based on metric conditions.

**Features**:
- 10 production-ready alert rules
- Proper severity classification (critical, warning, info)
- Consistent labeling and annotations
- **Enhanced**: Common labels `{service="mm-bot", env="${ENV:-prod}"}`
- **Enhanced**: Rich annotations with `runbook_url` and `grafana_panel`
- **Enhanced**: Anti-flap protection with increased `for:` durations
- **Enhanced**: MakerShareLow kept commented until `fills_*` metrics exist

**Alert Types**:
- **Critical**: RiskPaused, CircuitBreakerOpen, HighLatencyREST, DrawdownDay, OrderManagerUnhealthy
- **Warning**: RejectRateHigh, CancelRateNearLimit (5m threshold), AmendFailureRateHigh, QueuePositionDegraded, HighBackoffTime
- **Info**: LowMakerShare (placeholder for future metrics)

**Enhanced Features**:
- Environment-aware labeling with `${ENV:-prod}` fallback
- Consistent service identification as "mm-bot"
- Rich descriptions with metric values and thresholds
- Direct links to runbooks and Grafana panels
- Improved threshold expressions for better accuracy

### 2. Prometheus Configuration (`prometheus.yml`)

**Purpose**: Example configuration for Prometheus to scrape MM Bot metrics and load alert rules.

**Features**:
- Proper scrape intervals and timeouts
- Label relabeling for better organization
- Rule file inclusion
- Optional Alertmanager integration
- **Enhanced**: Environment variable support
- **Enhanced**: Better label management

### 3. Alertmanager Configuration (`alertmanager.yml`)

**Purpose**: Configure notification delivery and alert routing with intelligent inhibition.

**Features**:
- Slack integration for team notifications
- PagerDuty integration for critical alerts
- **Enhanced**: Advanced alert grouping by `['alertname', 'service', 'env']`
- **Enhanced**: Comprehensive inhibition rules to prevent alert spam
- **Enhanced**: Environment-aware routing and grouping

**Inhibition Rules**:
1. **RiskPaused inhibits**: CancelRateNearLimit, RejectRateHigh, QueuePositionDegraded
2. **HighLatencyREST inhibits**: RejectRateHigh (likely related)
3. **CircuitBreakerOpen inhibits**: AmendFailureRateHigh, HighBackoffTime

**Benefits**:
- Reduces alert fatigue by preventing related alerts from firing simultaneously
- Focuses team attention on root causes rather than symptoms
- Provides logical grouping of related issues
- Maintains environment isolation for proper alert management

### 4. Notification Templates

#### Slack Template (`templates/slack.tmpl`)
- Rich formatting with alert details
- Action buttons for quick access
- Contextual information (symbol, side, exchange)
- Runbook links
- **Enhanced**: Environment-aware notifications

#### PagerDuty Template (`templates/pagerduty.tmpl`)
- Incident creation with proper severity
- Detailed alert information
- Service and group classification
- **Enhanced**: Environment context in incident details

### 5. Grafana Dashboard (`grafana/dashboards/mm-bot-alerts.json`)

**Purpose**: Visual representation of alert status and history.

**Panels**:
- Alert status overview
- Critical alerts table
- Warning alerts table
- Alert history timeline
- **Enhanced**: Environment-aware filtering

## Testing Components

### 1. YAML Validation Tests (`tests/test_alerts_yaml.py`)

**Purpose**: Ensure alert rules have valid syntax and structure.

**Tests**:
- YAML syntax validation
- Structure validation
- Alert name uniqueness
- Required fields presence
- Expression validation
- Duration format validation
- Label consistency
- Annotation completeness
- **Enhanced**: Environment label validation
- **Enhanced**: Service label consistency

### 2. Alert Firing Tests (`tests/test_alerts_firing.py`)

**Purpose**: Verify that alerts fire when conditions are met.

**Tests**:
- Risk pause alert firing
- Circuit breaker alert firing
- High error rate alert firing
- High latency alert firing
- Amend failure rate alert firing
- Queue position degraded alert firing
- High backoff time alert firing
- Drawdown alert firing
- Cancel rate near limit alert firing
- Alert labels consistency
- **Enhanced**: Environment label verification
- **Enhanced**: Service label verification

### 3. Integration Tests (`tests/test_alerts_integration.py`)

**Purpose**: Verify complete alert system integration.

**Tests**:
- Prometheus compatibility
- Metric reference validation
- Label structure consistency
- Annotation completeness
- Duration format validation
- Threshold reasonableness
- Logical grouping
- Runbook URL presence
- **Enhanced**: Inhibition rule validation
- **Enhanced**: Environment label integration

## Documentation Components

### 1. Main README (`README.md`)

**Purpose**: Comprehensive guide to the alerting system.

**Content**:
- Quick start guide
- Alert rule descriptions
- Configuration examples
- Testing instructions
- Customization guide
- Best practices
- Troubleshooting
- **Enhanced**: Alert inhibition documentation
- **Enhanced**: Environment variable configuration
- **Enhanced**: Inhibition testing procedures

### 2. Deployment Guide (`DEPLOYMENT.md`)

**Purpose**: Step-by-step production deployment instructions.

**Content**:
- Quick deployment steps
- Verification procedures
- Production checklist
- Common issues and solutions
- **Enhanced**: Inhibition rule testing
- **Enhanced**: Environment variable setup
- **Enhanced**: Alertmanager configuration
- **Enhanced**: Inhibition debugging

### 3. Components Overview (`COMPONENTS.md`)

**Purpose**: This document - overview of all system components.

## File Structure

```
monitoring/
├── README.md                 # Main documentation
├── DEPLOYMENT.md            # Deployment guide
├── COMPONENTS.md            # This file
├── prometheus.yml            # Prometheus configuration
├── alertmanager.yml          # Alertmanager configuration with inhibition
├── alerts/
│   └── mm_bot.rules.yml     # Enhanced alert rules with env labels
├── templates/                # Notification templates
│   ├── slack.tmpl           # Slack notifications
│   └── pagerduty.tmpl      # PagerDuty notifications
└── grafana/
    └── dashboards/
        └── mm-bot-alerts.json # Grafana dashboard
```

## Testing Coverage

### Total Tests: 26+
- **YAML Tests**: 8+ tests (enhanced with env validation)
- **Firing Tests**: 10+ tests (enhanced with label verification)
- **Integration Tests**: 8+ tests (enhanced with inhibition validation)

### Test Results: ✅ All Passing
- YAML syntax validation: ✅
- Alert rule structure: ✅
- Metric references: ✅
- Label consistency: ✅
- Threshold validation: ✅
- Integration compatibility: ✅
- **Enhanced**: Environment label validation: ✅
- **Enhanced**: Inhibition rule validation: ✅

## Production Readiness

### ✅ Completed
- [x] Alert rules defined and tested
- [x] Prometheus configuration provided
- [x] Alertmanager configuration provided
- [x] Notification templates created
- [x] Grafana dashboard example
- [x] Comprehensive testing suite
- [x] Documentation and deployment guides
- [x] YAML syntax validation
- [x] Alert firing verification
- **Enhanced**: [x] Environment-aware labeling
- **Enhanced**: [x] Intelligent inhibition rules
- **Enhanced**: [x] Anti-flap protection
- **Enhanced**: [x] Rich annotations with runbooks

### 🔄 Next Steps (Production)
- [ ] Adjust thresholds based on production data
- [ ] Configure notification channels (Slack, PagerDuty)
- [ ] Create runbooks for each alert type
- [ ] Train team on alert response procedures
- [ ] Set up alert fatigue prevention
- [ ] Monitor false positive rates
- [ ] Establish alert review process
- **Enhanced**: [ ] Test inhibition rules in production
- **Enhanced**: [ ] Validate environment labels
- **Enhanced**: [ ] Monitor inhibition effectiveness

## Enhanced Features

### 1. Environment-Aware Labeling
- All alerts include `env: "${ENV:-prod}"` label
- Supports multiple environments (prod, staging, dev)
- Environment isolation for proper alert management
- Fallback to 'prod' if ENV variable not set

### 2. Intelligent Inhibition
- Prevents alert spam by inhibiting related alerts
- Logical grouping of issues under root causes
- Environment-aware inhibition (same service/env only)
- Reduces alert fatigue and focuses team attention

### 3. Anti-Flap Protection
- Increased `for:` durations for stability
- CancelRateNearLimit: 5m (was 3m)
- CircuitBreakerOpen: 3m (was 1m)
- Better protection against transient issues

### 4. Rich Annotations
- `runbook_url`: Direct links to troubleshooting guides
- `grafana_panel`: Quick access to relevant dashboards
- Enhanced descriptions with metric values
- Better context for incident response

## Usage Examples

### Enable Alerts with Environment
```bash
# Set environment
export ENV=production

# Copy rules to Prometheus
cp monitoring/alerts/mm_bot.rules.yml /etc/prometheus/rules/

# Reload configuration
curl -X POST http://localhost:9090/-/reload
```

### Test Inhibition Rules
```bash
# Test RiskPaused inhibition
curl -X POST http://localhost:8080/metrics/risk_paused -d "1"
# Wait for alert to fire
# Try to trigger CancelRateNearLimit - should be inhibited

# Check inhibition status
curl http://localhost:9093/api/v1/inhibits
```

### Validate Environment Labels
```bash
# Check if env labels are set
curl "http://localhost:9090/api/v1/rules" | grep -o 'env.*prod'

# Verify in Alertmanager
curl "http://localhost:9093/api/v1/alerts" | grep -A 5 "env.*prod"
```

## Support

For questions or issues with the alerting system:
1. Check the troubleshooting section in README.md
2. Review the test suite for examples
3. Validate YAML syntax using provided commands
4. Test alert firing conditions manually
5. **Enhanced**: Test inhibition rules manually
6. **Enhanced**: Verify environment variable configuration
7. **Enhanced**: Check Alertmanager inhibition status
