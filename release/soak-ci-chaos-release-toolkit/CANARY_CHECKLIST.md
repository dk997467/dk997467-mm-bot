# Canary Deployment Checklist

**Version:** v1.0.0-soak-validated
**Status:** PASS
**Freeze Ready:** True

---

## Pre-Deployment

- [ ] Review POST_SOAK_AUDIT.md
- [ ] Review RECOMMENDATIONS.md
- [ ] Verify DELTA_VERIFY_REPORT.json (full_apply_ratio >= 0.95)
- [ ] Backup current runtime_overrides.json
- [ ] Notify #trading-ops channel
- [ ] Verify rollback plan ready (rollback_plan.md)

## Canary Deployment (5% Traffic)

### Step 1: Deploy Canary

```bash
# Update canary config
cp release/soak-ci-chaos-release-toolkit/soak_profile.runtime_overrides.json \
   config/runtime_overrides.canary.json

# Deploy canary pod
kubectl apply -f k8s/mm-bot-canary.yaml

# Update traffic split (5% canary)
kubectl patch virtualservice mm-bot --type merge -p '
  {"spec":{"http":[{
    "route":[
      {"destination":{"host":"mm-bot-stable"},"weight":95},
      {"destination":{"host":"mm-bot-canary"},"weight":5}
    ]
  }]}}"
```

### Step 2: Monitor Canary (24-48h)

**Watch Grafana Dashboard:** `mm-bot-canary-metrics`

#### Hour 1: Critical Stability

- [ ] No errors in logs
- [ ] Maker/taker ratio >= 0.75
- [ ] P95 latency <= 400ms
- [ ] Risk ratio <= 0.50

#### Hour 6: Performance Verification

- [ ] Maker/taker ratio >= 0.80
- [ ] P95 latency <= 350ms
- [ ] Risk ratio <= 0.45
- [ ] Net BPS positive

#### Hour 24: Target KPIs

- [ ] Maker/taker ratio >= 0.83
- [ ] P95 latency <= 340ms
- [ ] Risk ratio <= 0.40
- [ ] Net BPS >= 2.5

### Step 3: Auto-Rollback Triggers

**Immediately rollback if:**

| Metric | Trigger | Duration |
|--------|---------|----------|
| Maker/Taker | < 0.70 | 5 min |
| P95 Latency | > 500ms | 3 min |
| Risk Ratio | > 0.60 | 2 min |
| Error Rate | > 5% | 1 min |

**Rollback command:**
```bash
# Scale down canary
kubectl scale deployment mm-bot-canary --replicas=0

# Restore 100% stable traffic
kubectl patch virtualservice mm-bot --type merge -p '
  {"spec":{"http":[{
    "route":[{"destination":{"host":"mm-bot-stable"},"weight":100}]
  }]}}"
```

### Step 4: Full Rollout (after 24-48h)

If canary stable:

- [ ] Increase traffic to 25%
- [ ] Monitor for 12h
- [ ] Increase traffic to 50%
- [ ] Monitor for 6h
- [ ] Full rollout (100%)
- [ ] Decommission old stable pods

## Post-Deployment

- [ ] Update production tag
- [ ] Archive release bundle
- [ ] Update runbook with new KPI baselines
- [ ] Notify stakeholders
- [ ] Schedule post-mortem (if issues)

---

## Sign-Off

**Deployed by:** _________________

**Date:** _________________

**Rollback ready:** [ ] Yes [ ] No
