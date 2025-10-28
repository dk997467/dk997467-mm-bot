# Secrets Operations Guide

## Overview

This document describes the secrets management system for MM Bot live trading. It covers production onboarding, rotation policies, and emergency procedures.

## Architecture

### Storage Backends

1. **Memory Store (Test/Dev):**
   - In-memory storage for local development and testing
   - No persistence
   - Configured via `SECRETS_BACKEND=memory`

2. **AWS Secrets Manager (Production):**
   - Encrypted storage in AWS
   - Audit trail via CloudTrail
   - Automatic rotation support
   - Configured via `SECRETS_BACKEND=aws`

### Environment Separation

Secrets are strictly separated by environment:

- **dev**: Local development (memory store)
- **shadow**: Shadow trading with paper accounts
- **soak**: Long-running stability testing with minimal capital
- **prod**: Production trading with real capital

Each environment has completely isolated credentials.

## Secret Naming Convention

Secrets follow this naming pattern:

```
mm-bot/{env}/{exchange}/{key_type}
```

Examples:
- `mm-bot/dev/bybit/api_key`
- `mm-bot/dev/bybit/api_secret`
- `mm-bot/prod/binance/api_key`
- `mm-bot/prod/binance/api_secret`

## Production Onboarding

### Prerequisites

1. AWS account with Secrets Manager enabled
2. IAM role with permissions:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "secretsmanager:GetSecretValue",
           "secretsmanager:DescribeSecret",
           "secretsmanager:ListSecrets"
         ],
         "Resource": "arn:aws:secretsmanager:*:*:secret:mm-bot/*"
       }
     ]
   }
   ```
3. Exchange API keys with appropriate permissions:
   - Read account data
   - Place/cancel orders
   - **No withdrawal permissions**

### Initial Setup

1. **Generate API Keys:**
   - Log in to exchange (Bybit/Binance/KuCoin)
   - Generate API key with trading permissions only
   - Whitelist IP addresses (if possible)
   - Enable 2FA for API management

2. **Store Credentials:**

   ```bash
   # Set environment
   export SECRETS_BACKEND=aws
   export AWS_REGION=us-east-1
   export MM_ENV=prod

   # Save credentials
   python -m tools.live.secrets_cli save \
     --env prod \
     --exchange bybit \
     --api-key "YOUR_API_KEY" \
     --api-secret "YOUR_API_SECRET"
   ```

3. **Verify Storage:**

   ```bash
   # List all credentials
   python -m tools.live.secrets_cli list

   # Fetch specific credentials (masked)
   python -m tools.live.secrets_cli fetch \
     --env prod \
     --exchange bybit
   ```

### GitHub Actions Configuration

#### OIDC Role Setup

Create an IAM role for GitHub Actions with OIDC trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:*"
        }
      }
    }
  ]
}
```

#### Workflow Configuration

Only `shadow` and `soak` environments should access secrets:

```yaml
name: Shadow Trading

on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

jobs:
  shadow:
    runs-on: ubuntu-latest
    environment: shadow
    steps:
      - uses: actions/checkout@v3

      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          role-to-assume: arn:aws:iam::ACCOUNT_ID:role/GitHubActions-Shadow
          aws-region: us-east-1

      - name: Run Shadow Trading
        env:
          SECRETS_BACKEND: aws
          MM_ENV: shadow
        run: |
          python -m tools.live.run_shadow
```

**Important:** Production credentials must **never** be accessible from GitHub Actions.

## Rotation Policy

### Standard Rotation (Every 90 Days)

API keys should be rotated every 90 days:

1. **Generate New Keys:**
   - Log in to exchange
   - Generate new API key/secret pair
   - Keep old keys active temporarily

2. **Update Secrets:**

   ```bash
   python -m tools.live.secrets_cli rotate \
     --env prod \
     --exchange bybit \
     --new-api-key "NEW_API_KEY" \
     --new-api-secret "NEW_API_SECRET"
   ```

3. **Verify New Credentials:**
   - Test with read-only operations first
   - Monitor for any authentication errors
   - Wait 5-10 minutes for propagation

4. **Revoke Old Keys:**
   - Delete old API keys from exchange
   - Update audit log

### Automated Rotation (Future Enhancement)

AWS Secrets Manager supports automated rotation via Lambda functions. This feature is not yet implemented but is recommended for production.

## Emergency Procedures

### Suspected Key Compromise

If you suspect an API key has been compromised:

1. **Immediate Actions (< 5 minutes):**

   ```bash
   # 1. Freeze all trading
   # (Manual intervention in exchange UI or kill running processes)

   # 2. Revoke compromised keys immediately in exchange UI
   ```

2. **Generate New Keys (< 15 minutes):**

   ```bash
   # 1. Generate new API keys in exchange
   # 2. Update secrets
   python -m tools.live.secrets_cli rotate \
     --env prod \
     --exchange bybit \
     --new-api-key "NEW_API_KEY" \
     --new-api-secret "NEW_API_SECRET"
   ```

3. **Post-Incident Review:**
   - Check CloudTrail logs for secret access
   - Review exchange API access logs
   - Document timeline and root cause
   - Update runbook if needed

### Break-Glass Procedure

In case of complete AWS access loss:

1. **Local Override:**

   ```bash
   # Use environment variables as fallback
   export MM_ENV=prod
   export SECRETS_BACKEND=memory
   export MM_FAKE_SECRETS_JSON='{"mm-bot/prod/bybit/api_key":"EMERGENCY_KEY","mm-bot/prod/bybit/api_secret":"EMERGENCY_SECRET"}'

   # Run trading bot
   python -m tools.live.run_live
   ```

2. **Restore Access:**
   - Work with AWS support to restore IAM access
   - Verify all credentials are still valid
   - Return to normal AWS Secrets Manager operation

3. **Audit:**
   - Document the incident
   - Review what went wrong
   - Update disaster recovery plan

## Security Best Practices

1. **Access Control:**
   - Use IAM roles with least privilege
   - Enable MFA for console access
   - Rotate IAM credentials regularly

2. **Monitoring:**
   - Enable CloudTrail logging
   - Set up alerts for secret access
   - Monitor for unusual API activity

3. **Key Management:**
   - Never commit keys to git
   - Use `.gitignore` for local key files
   - Rotate keys every 90 days minimum

4. **Exchange Settings:**
   - Enable IP whitelisting if possible
   - Disable withdrawal permissions
   - Enable 2FA for API management
   - Set up trade/order limits

5. **Audit Trail:**
   - Keep records of all key rotations
   - Document who has access to what
   - Regular security reviews

## Troubleshooting

### "Secret not found" Error

```bash
# Verify the secret exists
python -m tools.live.secrets_cli list

# Check environment variables
echo $SECRETS_BACKEND
echo $MM_ENV
echo $AWS_REGION

# Test AWS credentials
aws sts get-caller-identity
```

### "Access Denied" Error

```bash
# Verify IAM permissions
aws secretsmanager get-secret-value --secret-id mm-bot/dev/bybit/api_key

# Check IAM role/user permissions
aws iam get-role-policy --role-name YOUR_ROLE --policy-name YOUR_POLICY
```

### Cache Issues

```python
# Clear credential cache
from tools.live.secrets import clear_cache
clear_cache()
```

## Bybit API Keys Configuration (P0.2)

### Overview

Bybit API keys are required for the `BybitRestClient` implementation. This section documents the format, storage, and operational procedures for Bybit credentials.

**⚠️ Important**: In P0.2, the Bybit adapter operates in **dry-run mode only**. No real orders are placed, but proper credential management is critical for future production deployment.

### Secret Name Format

Secrets are stored in AWS Secrets Manager (or memory backend for testing) with the following naming convention:

```
mm-bot/{environment}/bybit/{key_type}
```

Where:
- `environment`: `dev`, `shadow`, `soak`, `prod`
- `key_type`: `api_key`, `api_secret`

Examples:
- `mm-bot/dev/bybit/api_key`
- `mm-bot/shadow/bybit/api_secret`
- `mm-bot/prod/bybit/api_key`

### Credential Format

Bybit API credentials consist of:
- **API Key**: Public identifier (e.g., `abc123xyz...`)
- **API Secret**: Private key for HMAC SHA256 signing (e.g., `secretkey456...`)

Both are generated from the Bybit web UI:
1. Log in to [Bybit](https://www.bybit.com/)
2. Navigate to **API Management**
3. Create new API key with appropriate permissions
4. Copy API key and secret (secret is shown only once!)

### Required Permissions

For shadow/dry-run mode:
- **Read**: Account info, order history, positions
- **Write**: Order placement, cancellation (not executed in dry-run)

For production mode (future):
- **Read**: As above
- **Write**: Order placement, cancellation
- **Transfer**: ❌ **NEVER ENABLE** (security risk)

### Save Credentials

#### Using CLI

**Memory Backend** (for testing):
```bash
export BYBIT_API_KEY="your_api_key_here"
export BYBIT_API_SECRET="your_api_secret_here"

# Verify
python -m tools.live.secrets_cli fetch --exchange bybit --env dev
```

**AWS Secrets Manager** (for production):
```bash
# Save API key
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env shadow \
  --key-type api_key \
  --value "your_api_key_here"

# Save API secret
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env shadow \
  --key-type api_secret \
  --value "your_api_secret_here"
```

#### Using Python API

```python
from tools.live.secrets import SecretProvider

# Memory backend (testing)
provider = SecretProvider(backend="memory")

# AWS backend (production)
provider = SecretProvider(backend="aws", env="shadow")

# Fetch credentials
api_key = provider.get_api_key("shadow", "bybit")
api_secret = provider.get_api_secret("shadow", "bybit")

# Use with BybitRestClient
from tools.live.exchange_bybit import BybitRestClient

client = BybitRestClient(
    secret_provider=provider,
    api_env="shadow",
    network_enabled=False,  # Dry-run mode
)
```

### Fetch Credentials

#### CLI (with masking)

```bash
# Fetch credentials (masked output)
python -m tools.live.secrets_cli fetch \
  --exchange bybit \
  --env shadow

# Output:
# {
#   "api_key": "abc...***",
#   "api_secret": "xyz...***",
#   "exchange": "bybit",
#   "env": "shadow"
# }
```

#### Python API

```python
from tools.live.secrets import SecretProvider

provider = SecretProvider(backend="aws", env="shadow")

# Get credentials
api_key = provider.get_api_key("shadow", "bybit")
api_secret = provider.get_api_secret("shadow", "bybit")

# ⚠️ NEVER log raw secrets
print(f"API Key: {api_key[:3]}...***")  # Masked output
```

### Rotation Policy

**Frequency**:
- **Development**: Every 6 months
- **Shadow/Soak**: Every 3 months
- **Production**: Every 30 days (minimum)

**Process**:
1. Generate new API key in Bybit UI
2. Save new key to secrets store (with `-new` suffix)
3. Test new key in shadow environment
4. Update production secret
5. Verify production deployment
6. Revoke old key in Bybit UI
7. Document rotation in audit log

Example rotation:
```bash
# Step 1: Save new key with suffix
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env prod \
  --key-type api_key \
  --value "new_api_key_here" \
  --suffix "-new"

# Step 2: Test with new key
MM_API_KEY_SUFFIX="-new" python -m tools.live.exec_demo \
  --exchange bybit --shadow --symbols BTCUSDT

# Step 3: Promote to main secret
python -m tools.live.secrets_cli rotate \
  --exchange bybit \
  --env prod \
  --from-suffix "-new"

# Step 4: Revoke old key in Bybit UI
```

### Emergency Revocation

If a key is compromised:

**Immediate Actions** (< 5 minutes):
```bash
# 1. Disable key in Bybit UI
#    - Go to API Management
#    - Click "Revoke" on compromised key

# 2. Generate new key
#    - Create new API key with same permissions
#    - Copy key and secret

# 3. Update secrets
python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env prod \
  --key-type api_key \
  --value "new_emergency_key"

python -m tools.live.secrets_cli save \
  --exchange bybit \
  --env prod \
  --key-type api_secret \
  --value "new_emergency_secret"

# 4. Restart services
# (deployment commands depend on your infrastructure)
```

**Post-Incident** (< 1 hour):
- Review CloudTrail logs for unauthorized access
- Verify no unauthorized trades occurred
- Document incident in audit log
- Update security procedures if necessary

### Validation

Validate credentials before deployment:

```python
from tools.live.exchange_bybit import BybitRestClient
from tools.live.secrets import SecretProvider

# Create client
provider = SecretProvider(backend="aws", env="shadow")
client = BybitRestClient(
    secret_provider=provider,
    api_env="shadow",
    network_enabled=False,  # Dry-run for validation
)

# Test signature generation
signature = client._generate_signature(
    timestamp=1609459200000,
    recv_window=5000,
    params={"symbol": "BTCUSDT"},
)

print(f"Signature generated successfully: {signature[:8]}...***")
```

### Monitoring

Track secret access via CloudTrail:

```bash
# Query recent secret accesses
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=mm-bot/prod/bybit/api_key \
  --max-results 10 \
  --query 'Events[].{Time:EventTime,User:Username,Action:EventName}'
```

Set up CloudWatch alarms:
- Alert on any access to `mm-bot/prod/bybit/*` secrets
- Alert on high-frequency access (> 100/hour)
- Alert on access from unexpected IAM roles

### Security Checklist

Before deploying to production:

- [ ] API keys generated with minimal permissions
- [ ] IP whitelist enabled in Bybit UI
- [ ] Withdrawal permissions disabled
- [ ] 2FA enabled for API management
- [ ] Secrets stored in AWS Secrets Manager (not environment variables)
- [ ] IAM policies restrict access to specific secrets
- [ ] CloudTrail logging enabled
- [ ] CloudWatch alarms configured
- [ ] Rotation schedule documented
- [ ] Emergency revocation procedure tested

### References

- [Bybit API Authentication Guide](https://bybit-exchange.github.io/docs/v5/guide#authentication)
- [AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
- [GitHub Actions Secrets Policy](.github/SECRETS_POLICY.md)
- [P0.7 Secrets Management](P0_7_COMPLETION_SUMMARY.md)

## Appendix

### Supported Exchanges

- Bybit
- Binance
- KuCoin

### AWS Regions

Default: `us-east-1`

Can be overridden via `AWS_REGION` environment variable.

### Credential Format

Credentials are stored as JSON strings:

```json
{
  "api_key": "...",
  "api_secret": "...",
  "exchange": "bybit",
  "env": "prod"
}
```

### Masked Output

When fetching credentials via CLI, only masked values are shown:

```json
{
  "api_key": "abc...***",
  "api_secret": "xyz...***",
  "exchange": "bybit",
  "env": "prod"
}
```

This prevents accidental exposure in logs or terminal history.

