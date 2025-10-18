# Production Rollback Plan

**Version:** v1.0.0-soak-validated
**Generated:** 2025-10-18T10:14:25.398997Z

---

## Quick Rollback (<10 minutes)

If KPIs degrade after deployment, follow this procedure:

### 1. Disable Auto-Tuning (Immediate)

```bash
# Option A: Environment variable
export MM_DISABLE_AUTO_TUNE=1

# Option B: Runtime override
curl -X POST http://localhost:8080/admin/config \
  -H "Content-Type: application/json" \
  -d '{"auto_tune_enabled": false}'
```

### 2. Revert Runtime Overrides (5 minutes)

```bash
# Backup current config
cp config/runtime_overrides.json config/runtime_overrides.json.backup

# Restore previous stable config
cp release/previous_release/soak_profile.runtime_overrides.json \
   config/runtime_overrides.json

# Restart bot (graceful)
systemctl reload mm-bot  # or: kill -HUP $(pidof mm-bot)
```

### 3. Verify Rollback (2 minutes)

```bash
# Check KPIs via metrics endpoint
curl http://localhost:9090/metrics | grep -E 'maker_taker|p95_latency|risk_ratio'

# Expected:
#   maker_taker_ratio{} >= 0.80
#   p95_latency_ms{} <= 350
#   risk_ratio{} <= 0.45
```

### 4. Monitor (30 minutes)

Watch Grafana dashboard for:
- Maker/taker ratio stabilizing
- P95 latency returning to baseline
- Risk ratio decreasing
- Net BPS recovering

---

## Full Rollback (30 minutes)

If quick rollback insufficient:

### 1. Deploy Previous Version

```bash
# Stop current version
systemctl stop mm-bot

# Checkout previous tag
cd /opt/mm-bot
git fetch --tags
git checkout v0.9.9-stable  # Replace with actual previous version

# Rebuild (if necessary)
pip install -e .

# Start
systemctl start mm-bot
```

### 2. Verify Health

```bash
# Check logs
journalctl -u mm-bot -f --since '5 minutes ago'

# Check health endpoint
curl http://localhost:8080/health

# Verify version
curl http://localhost:8080/version
```

---

## Canary Rollback

If deployed as canary (5% traffic):

```bash
# Scale down canary to 0%
kubectl scale deployment mm-bot-canary --replicas=0

# Or: update traffic split
kubectl patch virtualservice mm-bot \
  -p '{"spec":{"http":[{"route":[{"destination":{"host":"mm-bot-stable","weight":100}}]}]}}'
```

---

## Automatic Rollback Triggers

Immediately rollback if:

| Metric | Trigger | Action |
|--------|---------|--------|
| Maker/Taker | < 70% for 5min | Quick rollback |
| P95 Latency | > 500ms for 3min | Quick rollback |
| Risk Ratio | > 60% for 2min | Full rollback |
| Net BPS | < 0 for 10min | Quick rollback |
| Error Rate | > 5% for 1min | Full rollback |

---

## Escalation

If rollback fails or KPIs don't recover:

1. **Notify:** @trading-ops channel
2. **Escalate:** On-call SRE (PagerDuty)
3. **Emergency:** Kill bot, investigate offline
