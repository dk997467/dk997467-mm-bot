# GitHub Actions Secrets Policy

## Overview

This document defines the policy for accessing secrets in GitHub Actions workflows for the MM Bot project.

## Principles

1. **Least Privilege**: Workflows should only have access to secrets they absolutely need
2. **Environment Separation**: Different environments have different access controls
3. **No Production Secrets in CI**: Production credentials must never be accessible from GitHub Actions
4. **OIDC Authentication**: Use OpenID Connect (OIDC) for AWS access instead of long-lived credentials

## Environment Matrix

| Environment | Purpose | Secrets Access | Workflow Trigger |
|-------------|---------|----------------|------------------|
| `dev` | Local development | Memory store (MM_FAKE_SECRETS_JSON) | Manual |
| `shadow` | Paper trading with test accounts | AWS Secrets Manager (shadow path) | Push to main |
| `soak` | Stability testing with minimal capital | AWS Secrets Manager (soak path) | Manual/Scheduled |
| `prod` | Production trading | **NO ACCESS** | **NEVER** |

## Allowed Workflows

### Shadow Trading Workflow

**File**: `.github/workflows/shadow.yml`

**Permissions**:
```yaml
permissions:
  id-token: write  # Required for OIDC
  contents: read
```

**AWS OIDC Role**: `arn:aws:iam::ACCOUNT_ID:role/GitHubActions-Shadow`

**Allowed Secrets Paths**:
- `mm-bot/shadow/*`

**Forbidden**:
- `mm-bot/prod/*` (production credentials)
- `mm-bot/soak/*` (unless explicitly in soak workflow)

### Soak Testing Workflow

**File**: `.github/workflows/soak.yml`

**Permissions**:
```yaml
permissions:
  id-token: write
  contents: read
```

**AWS OIDC Role**: `arn:aws:iam::ACCOUNT_ID:role/GitHubActions-Soak`

**Allowed Secrets Paths**:
- `mm-bot/soak/*`

### CI/CD Workflow

**File**: `.github/workflows/ci.yml`

**Permissions**:
```yaml
permissions:
  contents: read
```

**Secrets Access**: **NONE**

- CI should run without any exchange credentials
- Uses in-memory mock secrets for testing

## IAM Policies

### Shadow Role Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowShadowSecretsRead",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:mm-bot/shadow/*"
    },
    {
      "Sid": "DenyProductionSecrets",
      "Effect": "Deny",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:mm-bot/prod/*"
    }
  ]
}
```

### Soak Role Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSoakSecretsRead",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:mm-bot/soak/*"
    },
    {
      "Sid": "DenyProductionSecrets",
      "Effect": "Deny",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:mm-bot/prod/*"
    }
  ]
}
```

## OIDC Trust Relationship

### Trust Policy for Shadow Role

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
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:environment:shadow"
        }
      }
    }
  ]
}
```

### Trust Policy for Soak Role

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
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:environment:soak"
        }
      }
    }
  ]
}
```

## Implementation Checklist

- [ ] Create OIDC provider in AWS IAM
- [ ] Create IAM roles for Shadow and Soak environments
- [ ] Attach policies to roles
- [ ] Configure trust relationships
- [ ] Create GitHub environments (shadow, soak)
- [ ] Update workflows to use OIDC authentication
- [ ] Test shadow workflow with paper trading
- [ ] Test soak workflow with minimal capital
- [ ] Document incident response procedure

## Monitoring and Auditing

### CloudTrail

Enable CloudTrail logging for all Secrets Manager API calls:

```bash
aws cloudtrail create-trail \
  --name mm-bot-secrets-audit \
  --s3-bucket-name mm-bot-audit-logs
```

### CloudWatch Alarms

Create alarms for suspicious activity:

1. **Unexpected Secret Access**:
   - Alert on any access to `mm-bot/prod/*` secrets
   - Alert on access from unexpected IAM roles

2. **High Volume Access**:
   - Alert if secret access rate exceeds normal patterns

3. **Failed Authentication**:
   - Alert on repeated failed GetSecretValue attempts

### Regular Audits

- Weekly review of CloudTrail logs
- Monthly access pattern analysis
- Quarterly security review

## Incident Response

If a secret is compromised:

1. **Immediate Actions** (< 5 minutes):
   - Disable the compromised API key in exchange UI
   - Revoke GitHub Actions role if necessary

2. **Short-term Actions** (< 1 hour):
   - Generate new API keys
   - Update secrets in AWS Secrets Manager
   - Verify no unauthorized trades occurred

3. **Post-Incident Review**:
   - Document timeline
   - Identify root cause
   - Update policies and procedures
   - Team debrief

## References

- [AWS Secrets Manager Documentation](https://docs.aws.amazon.com/secretsmanager/)
- [GitHub OIDC Documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [SECRETS_OPERATIONS.md](../../SECRETS_OPERATIONS.md)

## Approval

This policy must be approved by:
- [ ] Tech Lead
- [ ] Security Officer
- [ ] Operations Manager

**Last Updated**: 2025-10-27
**Next Review**: 2026-01-27

