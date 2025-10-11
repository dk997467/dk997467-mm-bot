# Scan Secrets - Critical Artifacts Detection

**Purpose:** Scan source code and artifacts for leaked secrets with enhanced criticality detection.

## Overview

The `scan_secrets.py` tool performs static analysis to detect potential secrets in:

1. **Source directories** (`src/`, `cli/`, `tools/`)
2. **Artifacts directory** (`artifacts/**`) - **CRITICAL PATH**

**Key Feature:** Any secret found in `artifacts/**` results in **exit code 2** (CRITICAL), bypassing the allowlist.

## Exit Codes

The tool uses a **3-level exit code system**:

- **Exit 0**: Clean (no secrets) or all secrets are allowlisted
- **Exit 1**: Real secrets found in source code (not allowlisted)
- **Exit 2**: **CRITICAL** - Secrets found in `artifacts/**` (bypasses allowlist)

### Priority Logic

```
IF critical_findings (artifacts/**):
  → Exit 2 (CRITICAL)
ELIF real_findings (source, not allowlisted):
  → Exit 1 (FOUND)
ELIF allowlisted_findings AND strict_mode:
  → Exit 1 (ALLOWLISTED_STRICT)
ELIF allowlisted_findings:
  → Exit 0 (CLEAN)
ELSE:
  → Exit 0 (CLEAN)
```

## Critical Path: `artifacts/**`

### Why Critical?

Artifacts may contain:
- Generated reports with real API keys
- Log files with leaked credentials
- Cache files with sensitive data
- Build outputs with embedded secrets

**Any secret in `artifacts/**` is treated as a critical security incident**, regardless of allowlist status.

### Detection Mechanism

The tool:
1. Resolves `WORK_DIR/artifacts/` path
2. Checks if each finding is under `artifacts/`
3. Classifies as **critical** if inside `artifacts/`
4. **Bypasses allowlist** for critical findings
5. Returns exit code 2 immediately

### Example

```bash
# Artifacts leak detected
$ python -m tools.ci.scan_secrets
[CRITICAL] Secrets found in artifacts/** (bypasses allowlist):
  artifacts/logs/app.log:42: API_KEY=sk_****...
| scan_secrets | FAIL | RESULT=CRITICAL |
[CRITICAL] Found 1 secret(s) in artifacts/
$ echo $?
2
```

## Output Markers

The tool prints a standardized marker to stdout:

### Exit 2 (Critical)
```
| scan_secrets | FAIL | RESULT=CRITICAL |
```

### Exit 1 (Found)
```
| scan_secrets | FAIL | RESULT=FOUND |
```

### Exit 0 (Clean)
```
| scan_secrets | OK | RESULT=CLEAN |
```

### Exit 0 (Allowlisted, strict mode disabled)
```
| scan_secrets | OK | RESULT=CLEAN |
```

### Exit 1 (Allowlisted, strict mode enabled)
```
| scan_secrets | FAIL | RESULT=ALLOWLISTED_STRICT |
```

## Usage

### Basic Usage

```bash
# Scan with default settings
python -m tools.ci.scan_secrets

# Strict mode (fail on allowlisted secrets)
python -m tools.ci.scan_secrets --strict

# Or via env var
CI_STRICT_SECRETS=1 python -m tools.ci.scan_secrets
```

### With Custom Work Directory

```bash
# Specify custom work directory
WORK_DIR=/path/to/repo python -m tools.ci.scan_secrets
```

### CI/CD Pipeline Usage

```yaml
- name: Scan for secrets
  run: |
    python -m tools.ci.scan_secrets
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 2 ]; then
      echo "❌ CRITICAL: Secrets found in artifacts/"
      echo "This is a security incident - investigate immediately"
      exit 1
    elif [ $EXIT_CODE -eq 1 ]; then
      echo "❌ Secrets found in source code"
      exit 1
    else
      echo "✅ No secrets detected"
    fi
```

## Allowlist

### Built-in Test Credentials

The following are automatically allowlisted:

```python
TEST_CREDENTIALS_WHITELIST = {
    'test_api_key_for_ci_only',
    'test_api_secret_for_ci_only',
    'test_pg_password_for_ci_only',
    'dummy_api_key_12345',
    'fake_secret_for_testing',
    'ci-0.0.0',
    '****',
}
```

### Custom Allowlist

Create `tools/ci/allowlist.txt` with patterns (one per line):

```
# Path patterns
tests/fixtures/**
**/*_test.py

# String patterns
dummy_key_.*
EXAMPLE_SECRET_.*

# Regex patterns
(test|mock|fake)_.*_key
```

**Note:** Allowlist is ignored for `artifacts/**` paths.

## Configuration

### Environment Variables

- `WORK_DIR`: Override working directory (default: repo root)
- `CI_STRICT_SECRETS`: Enable strict mode (`1` = enabled)

### Scan Targets

**Directories scanned:**
- `src/`
- `cli/`
- `tools/`
- `artifacts/` (if exists)

**Excluded directories:**
- `venv`, `.git`, `__pycache__`
- `tests/fixtures` (allowlisted test data)
- `artifacts` (in source code scan, but scanned separately)
- `dist`, `logs`, `data`, `config`

**File types:**
- `.txt`, `.json`, `.jsonl`, `.yaml`, `.yml`
- `.log`, `.ini`, `.py`, `.sh`
- Files without extension

**Excluded:**
- `.md` files (contain examples/placeholders)

## Testing

### Unit Tests

**File:** `tests/test_scan_secrets_ci.py`

```bash
# Run unit tests
python tests/test_scan_secrets_ci.py

# With pytest
pytest -q tests/test_scan_secrets_ci.py
```

**Tests:**
- `test_scan_secrets_finds_fixture()` - Verifies exit 2 for secrets in `artifacts/**`
- `test_scan_secrets_clean_repo()` - Verifies exit 0 for clean repo

### Test Output

```
✓ scan_secrets detects artifacts leak → exit 2 (CRITICAL)
✓ scan_secrets clean repo → exit 0
✓ All scan_secrets tests passed
```

## Secret Patterns

The tool detects patterns from `src/common/redact.py`:

- API keys (various formats)
- AWS credentials
- Bearer tokens
- SSH keys
- Database passwords
- OAuth tokens
- And more...

See `src/common/redact.py` for full pattern list.

## Monitoring and Alerts

### Alert Configuration

**Priority 1 (Critical):**
```yaml
- alert: SecretsInArtifacts
  expr: scan_secrets_exit_code == 2
  severity: critical
  summary: "Secrets detected in artifacts/ directory"
  action: "Immediate investigation required"
```

**Priority 2 (High):**
```yaml
- alert: SecretsInSource
  expr: scan_secrets_exit_code == 1
  severity: high
  summary: "Secrets detected in source code"
  action: "Review and remediate"
```

### Metrics

Suggested metrics to export:

```
# Exit code
scan_secrets_exit_code{result="critical|found|clean"}

# Finding counts
scan_secrets_findings_total{type="critical|real|allowlisted"}

# Scan duration
scan_secrets_duration_seconds
```

## Security Response

### If Exit Code 2 (Critical)

1. **Immediate actions:**
   - Stop deployment pipeline
   - Rotate affected credentials
   - Investigate source of leak

2. **Root cause analysis:**
   - Identify which process wrote to `artifacts/`
   - Review recent commits/PRs
   - Check CI/CD logs

3. **Remediation:**
   - Remove leaked file from `artifacts/`
   - Fix code that wrote sensitive data
   - Add tests to prevent recurrence

### If Exit Code 1 (Found)

1. **Review finding:**
   - Check if it's a real secret or false positive
   - If real: rotate credential

2. **Fix:**
   - Remove from source code
   - Use environment variables
   - Update `.gitignore` if file-based

3. **Add to allowlist:**
   - Only if confirmed false positive
   - Add pattern to `tools/ci/allowlist.txt`

## Implementation Notes

- **stdlib-only**: No external dependencies
- **Redaction**: Secrets are redacted in output (shows `****`)
- **Deterministic**: Results are sorted for reproducibility
- **Atomic**: Scan is all-or-nothing (no partial results)

## Known Limitations

1. **Large artifacts:** Scanning large `artifacts/` directories may be slow
   - Mitigated by EXCLUDE_DIRS filtering
   - Consider splitting scans if needed

2. **Binary files:** Only text files are scanned
   - Binary files in `artifacts/` are skipped
   - Secrets in binary files won't be detected

3. **Compressed files:** Archives (`.zip`, `.tar.gz`) are not extracted
   - Scan only checks file metadata/names
   - Consider separate archive scanning if needed

## Integration Checklist

- [ ] Set `WORK_DIR` in CI if needed
- [ ] Configure alerts for exit code 2 (CRITICAL)
- [ ] Add to pre-deployment checks
- [ ] Monitor `artifacts/` creation processes
- [ ] Test with intentional leak (validate exit 2)
- [ ] Document incident response procedures
- [ ] Set up credential rotation automation

---

**Status:** Production ready  
**Last Updated:** 2025-10-11

