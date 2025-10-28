# Runbook: Secret Rotation

**Audience:** DevOps, Security Team  
**Version:** 1.0  
**Last Updated:** 2025-01-27

---

## Table of Contents

1. [Overview](#overview)
2. [Scheduled Rotation](#scheduled-rotation)
3. [Emergency Rotation](#emergency-rotation)
4. [Break-Glass Procedure](#break-glass-procedure)
5. [Rollback Procedure](#rollback-procedure)
6. [Validation & Testing](#validation--testing)
7. [Troubleshooting](#troubleshooting)

---

## Overview

This runbook covers procedures for rotating API credentials (Bybit, Binance, etc.) stored in AWS Secrets Manager.

### When to Rotate

| Trigger | Rotation Type | Response Time |
|---------|---------------|---------------|
| **Scheduled** (90 days) | Automatic | Non-urgent |
| **Suspected compromise** | Emergency | < 5 minutes |
| **Confirmed leak** | Break-glass | < 2 minutes |
| **Employee offboarding** | Manual | < 24 hours |

---

## Scheduled Rotation

### Automatic Rotation (Preferred)

**Trigger**: AWS Secrets Manager automatic rotation (configured for 90 days)

**Process**:
1. AWS triggers Lambda function: `bybit-api-key-rotator`
2. Lambda calls Bybit API to generate new key
3. Lambda stores new key in Secrets Manager
4. Old key marked as `AWSPENDING` (grace period: 24h)
5. Application caches refresh automatically (TTL: 5 min)
6. After grace period, old key marked `AWSPREVIOUS`

**Monitoring**:
- CloudWatch Alarm: `SecretRotationFailed`
- Slack notification: `#security-alerts`

**No Action Required** (fully automated)

---

## Emergency Rotation

### Scenario: Suspected Credential Compromise

**Indicators**:
- Unusual API activity (high request rate, unfamiliar IPs)
- Exchange security alert
- 403/401 errors spike
- Unauthorized trades detected

### Procedure (< 30 minutes)

#### Step 1: Assess Situation (2 minutes)

```bash
# Check recent secret access (CloudTrail)
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=prod/bybit/api \
  --max-results 50 \
  --query 'Events[*].[EventTime,Username,SourceIPAddress]' \
  --output table

# Check trading bot logs for auth errors
kubectl logs -l app=live-trading-bot --since=1h | grep -i "auth\|401\|403"
```

#### Step 2: Revoke Compromised Key (5 minutes)

**Option A: Via Exchange UI (Bybit example)**
1. Login: https://www.bybit.com/app/user/api-management
2. Find API key (match first 4 chars from secret)
3. Click "Delete" → Confirm

**Option B: Via Exchange API (automated)**
```bash
# Retrieve current key ID
KEY_ID=$(aws secretsmanager get-secret-value \
  --secret-id prod/bybit/api \
  --query SecretString \
  --output text | jq -r '.api_key_id')

# Revoke via API (requires master key)
curl -X DELETE "https://api.bybit.com/v5/user/delete-api" \
  -H "X-BAPI-API-KEY: $MASTER_KEY" \
  -H "X-BAPI-SIGN: $SIGNATURE" \
  -d "{\"api_key_id\": \"$KEY_ID\"}"
```

#### Step 3: Generate New Credentials (5 minutes)

**Option A: Trigger Auto-Rotation**
```bash
# Force immediate rotation
aws secretsmanager rotate-secret \
  --secret-id prod/bybit/api \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:bybit-rotate

# Monitor Lambda execution
aws logs tail /aws/lambda/bybit-rotate --follow
```

**Option B: Manual Generation (if Lambda unavailable)**
```bash
# 1. Generate new key via exchange UI
# 2. Store in Secrets Manager
NEW_SECRET=$(jq -n \
  --arg key "$NEW_API_KEY" \
  --arg secret "$NEW_API_SECRET" \
  --arg key_id "$NEW_KEY_ID" \
  '{
    api_key: $key,
    api_secret: $secret,
    api_key_id: $key_id,
    created_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
    created_by: "'$USER'",
    rotation_reason: "emergency_rotation"
  }')

aws secretsmanager put-secret-value \
  --secret-id prod/bybit/api \
  --secret-string "$NEW_SECRET"
```

#### Step 4: Restart Services (5 minutes)

```bash
# Clear secret cache
kubectl exec -it deployment/live-trading-bot -- \
  python -c "from tools.live.secrets import clear_cache; clear_cache()"

# Rolling restart (zero-downtime)
kubectl rollout restart deployment/live-trading-bot -n prod

# Wait for rollout
kubectl rollout status deployment/live-trading-bot -n prod --timeout=5m
```

#### Step 5: Verify New Credentials (10 minutes)

```bash
# Test API connectivity
kubectl exec -it deployment/live-trading-bot -- \
  python -c "
from tools.live.secrets import get_api_credentials
creds = get_api_credentials('prod', 'bybit')
print(f'Key retrieved: {creds.api_key[:8]}...')
"

# Check for auth errors in logs (5 min window)
kubectl logs -l app=live-trading-bot --since=5m | grep -i "auth\|401\|403"

# Verify active orders
kubectl exec -it deployment/live-trading-bot -- \
  python -m tools.live.cli --action list_orders --symbol BTCUSDT
```

#### Step 6: Post-Rotation Monitoring (1 hour)

```bash
# Watch for errors (CloudWatch Insights query)
aws logs start-query \
  --log-group-name /aws/ecs/live-trading-bot \
  --start-time $(date -u -d '1 hour ago' +%s) \
  --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /401|403|auth/ | sort @timestamp desc | limit 20'
```

---

## Break-Glass Procedure

### Scenario: Confirmed Credential Leak

**Indicators**:
- API key found in public GitHub repo
- Key posted on social media
- Unauthorized trades executed
- Exchange notifies of compromise

### Immediate Actions (< 5 minutes)

#### 1. **STOP ALL TRADING** (30 seconds)

```bash
# Freeze trading bot (set replicas to 0)
kubectl scale deployment/live-trading-bot --replicas=0 -n prod

# Verify shutdown
kubectl get pods -l app=live-trading-bot -n prod
```

#### 2. **REVOKE KEY** (1 minute)

```bash
# Fastest method: Exchange UI
# Navigate to API management and delete key immediately
```

#### 3. **CANCEL ALL OPEN ORDERS** (1 minute)

```bash
# If bot still has access, cancel all orders
kubectl exec -it deployment/live-trading-bot -- \
  python -m tools.live.cli --action cancel_all_orders

# Or via exchange UI: Cancel All button
```

#### 4. **GENERATE NEW KEY** (2 minutes)

```bash
# Option A: Via exchange UI (fastest)
# 1. Generate new API key with permissions: Read, Trade
# 2. Copy key and secret

# Option B: Via API (if available)
# Use master API key to generate new trading key
```

#### 5. **STORE NEW SECRET** (30 seconds)

```bash
NEW_SECRET=$(jq -n \
  --arg key "$NEW_API_KEY" \
  --arg secret "$NEW_API_SECRET" \
  '{
    api_key: $key,
    api_secret: $secret,
    rotation_reason: "break_glass_leak_detected",
    rotated_by: "'$USER'",
    rotated_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ"))
  }')

aws secretsmanager put-secret-value \
  --secret-id prod/bybit/api \
  --secret-string "$NEW_SECRET" \
  --version-stages AWSCURRENT
```

### Recovery (< 10 minutes)

#### 6. **RESTART TRADING BOT** (2 minutes)

```bash
# Scale back up
kubectl scale deployment/live-trading-bot --replicas=3 -n prod

# Force cache clear on startup (already happens automatically)
kubectl rollout restart deployment/live-trading-bot -n prod
```

#### 7. **VERIFY RECOVERY** (5 minutes)

```bash
# Check bot health
kubectl get pods -l app=live-trading-bot -n prod

# Test API calls
kubectl logs -f deployment/live-trading-bot -n prod | head -50

# Verify positions reconcile
kubectl exec -it deployment/live-trading-bot -- \
  python -m tools.live.cli --action reconcile_positions
```

#### 8. **NOTIFY STAKEHOLDERS** (2 minutes)

```bash
# Post to Slack
curl -X POST $SLACK_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "🚨 BREAK-GLASS ROTATION COMPLETED",
    "attachments": [{
      "color": "danger",
      "fields": [
        {"title": "Reason", "value": "API key leaked", "short": true},
        {"title": "Status", "value": "Trading resumed", "short": true},
        {"title": "Duration", "value": "5 minutes downtime", "short": true}
      ]
    }]
  }'
```

---

## Rollback Procedure

### When to Rollback

- New credentials don't work (403/401 errors persist)
- Exchange rejects new key
- Trading bot fails to start

### Rollback to Previous Key (< 2 minutes)

#### Option 1: Via Version Stages

```bash
# List secret versions
aws secretsmanager list-secret-version-ids \
  --secret-id prod/bybit/api \
  --query 'Versions[*].[VersionId,VersionStages]' \
  --output table

# Rollback to AWSPREVIOUS
PREVIOUS_VERSION=$(aws secretsmanager list-secret-version-ids \
  --secret-id prod/bybit/api \
  --query 'Versions[?contains(VersionStages, `AWSPREVIOUS`)].VersionId' \
  --output text)

aws secretsmanager update-secret-version-stage \
  --secret-id prod/bybit/api \
  --version-stage AWSCURRENT \
  --move-to-version-id $PREVIOUS_VERSION
```

#### Option 2: Manual Secret Update

```bash
# If previous version unavailable, manually enter old credentials
OLD_SECRET=$(jq -n \
  --arg key "$OLD_API_KEY" \
  --arg secret "$OLD_API_SECRET" \
  '{api_key: $key, api_secret: $secret}')

aws secretsmanager put-secret-value \
  --secret-id prod/bybit/api \
  --secret-string "$OLD_SECRET"
```

#### Restart Services

```bash
# Force cache clear and restart
kubectl rollout restart deployment/live-trading-bot -n prod
kubectl rollout status deployment/live-trading-bot -n prod --timeout=5m
```

---

## Validation & Testing

### Pre-Rotation Checklist

- [ ] Verify no active trades in progress
- [ ] Check system load (< 70% CPU/memory)
- [ ] Confirm maintenance window (if manual rotation)
- [ ] Notify trading team (if off-hours)

### Post-Rotation Validation

#### 1. **API Connectivity Test**

```bash
# Test secret retrieval
python -c "
from tools.live.secrets import get_api_credentials
creds = get_api_credentials('prod', 'bybit')
print(f'✓ Secret retrieved: {creds.api_key[:8]}...')
"
```

#### 2. **Exchange API Test**

```bash
# Test authenticated endpoint
python -c "
from tools.live.exchange_client import create_client
client = create_client(exchange='bybit', mock=False)
balance = client.get_wallet_balance()
print(f'✓ Balance retrieved: {balance}')
"
```

#### 3. **Order Placement Test** (Staging Only)

```bash
# Place small test order on staging
kubectl exec -it deployment/live-trading-bot -n staging -- \
  python -m tools.live.cli \
    --action place_order \
    --symbol BTCUSDT \
    --side Buy \
    --qty 0.001 \
    --price 30000
```

#### 4. **Monitor Error Rates**

```bash
# Check error rate (should be < 1%)
kubectl top pods -l app=live-trading-bot -n prod

# Watch logs for 5 minutes
kubectl logs -f deployment/live-trading-bot -n prod --since=5m | \
  grep -i "error\|exception\|401\|403"
```

---

## Troubleshooting

### Issue: Rotation Lambda Fails

**Error**: `Lambda execution failed: Timeout`

**Cause**: Exchange API slow or unavailable

**Solution**:
```bash
# Check Lambda logs
aws logs tail /aws/lambda/bybit-rotate --follow

# If timeout, retry with longer timeout
aws lambda update-function-configuration \
  --function-name bybit-rotate \
  --timeout 60

# Retry rotation
aws secretsmanager rotate-secret --secret-id prod/bybit/api
```

---

### Issue: New Key Rejected (403 Forbidden)

**Error**: `InvalidAPIKey` or `InvalidSignature`

**Cause**: Key not activated yet, or IP whitelist not updated

**Solution**:
```bash
# 1. Check key permissions on exchange UI
#    - Ensure "Read" and "Trade" enabled
#    - Verify IP whitelist includes bot IPs

# 2. Wait 1 minute (key activation delay)
sleep 60

# 3. Test again
python -c "
from tools.live.exchange_client import create_client
client = create_client(exchange='bybit', mock=False)
print(client.get_server_time())
"
```

---

### Issue: Bot Not Picking Up New Secret

**Error**: Logs show old API key errors after rotation

**Cause**: Cache not cleared, pod not restarted

**Solution**:
```bash
# Force cache clear
kubectl exec deployment/live-trading-bot -- \
  python -c "from tools.live.secrets import clear_cache; clear_cache()"

# Delete pods (forces recreation)
kubectl delete pods -l app=live-trading-bot -n prod

# Verify new pods use new secret
kubectl logs -f deployment/live-trading-bot -n prod | head -20
```

---

### Issue: Unauthorized Trades After Rotation

**Error**: Orders placed that weren't initiated by bot

**Cause**: Old key still active, unauthorized actor has access

**Solution**:
```bash
# 1. IMMEDIATELY freeze bot
kubectl scale deployment/live-trading-bot --replicas=0 -n prod

# 2. Revoke ALL API keys for this account
#    Via exchange UI: Delete all keys

# 3. Change exchange account password

# 4. Enable 2FA/IP whitelist

# 5. Generate new key with strict permissions (Read-only first)

# 6. Investigate: Who had access? How was key leaked?
```

---

## Appendix: Useful Commands

### Check Current Secret Metadata

```bash
aws secretsmanager describe-secret --secret-id prod/bybit/api
```

### List All Rotation-Enabled Secrets

```bash
aws secretsmanager list-secrets \
  --filters Key=tag-key,Values=RotationEnabled \
  --query 'SecretList[*].[Name,LastRotatedDate,RotationEnabled]' \
  --output table
```

### Test Secret Retrieval Latency

```bash
time python -c "from tools.live.secrets import get_api_credentials; get_api_credentials('prod', 'bybit')"
```

### Force Rotation for All Prod Secrets

```bash
for secret in $(aws secretsmanager list-secrets --query 'SecretList[?contains(Name, `prod`)].Name' --output text); do
  echo "Rotating $secret..."
  aws secretsmanager rotate-secret --secret-id "$secret"
done
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-27 | DevOps Team | Initial version |

---

**Last Updated**: 2025-01-27  
**Next Review**: 2025-04-27 (90 days)

