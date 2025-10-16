# 🔧 OPERATIONS GUIDE — MM-BOT

**Audience:** DevOps, SRE, Oncall Engineers  
**Purpose:** Operational procedures, maintenance tasks, troubleshooting

---

## 📦 Artifact Lifecycle Management

### Overview

Soak tests generate large volumes of artifacts that accumulate over time:
- `ITER_SUMMARY_*.json` — Per-iteration metrics (can reach 1000+ files)
- Snapshot files — Configuration freezes for production
- Logs and reports — EDGE_REPORT, TUNING_REPORT, etc.

**Without rotation**, the `artifacts/soak/` directory can grow to **10+ GB**, causing:
- CI disk full errors
- Slow artifact uploads
- Difficulty finding recent files

### Automatic Rotation (CI)

The **artifact manager** runs automatically after each soak test:

```yaml
# .github/workflows/soak-windows.yml
- name: Rotate soak artifacts
  run: |
    python -m tools.soak.artifact_manager \
      --path artifacts/soak \
      --ttl-days 7 \
      --max-size-mb 900 \
      --keep-latest 100
```

**Default Policy:**
- Keep last **100** ITER_SUMMARY files (≈50 MB)
- Compress snapshots older than **7 days** to `.tar.gz` (60-80% reduction)
- Warn if total size exceeds **900 MB**

### Manual Rotation

For local development or manual cleanup:

```bash
# Standard rotation
python -m tools.soak.artifact_manager --path artifacts/soak

# Custom retention
python -m tools.soak.artifact_manager \
  --path artifacts/soak \
  --ttl-days 14 \
  --max-size-mb 1500 \
  --keep-latest 200

# Dry-run (report only, no changes)
python -m tools.soak.artifact_manager --path artifacts/soak --dry-run
```

### Rotation Log

All operations logged to `artifacts/soak/rotation/ROTATION_LOG.jsonl`:

```json
{
  "timestamp": "2025-10-15T12:34:56Z",
  "rotation": {"deleted": 50, "kept": 100},
  "compression": {"compressed": 5, "total_reduction_kb": 1234.5},
  "disk_usage": {"size_mb": 456.78, "within_limit": true}
}
```

**Monitoring:**
```bash
# Check rotation history
tail -5 artifacts/soak/rotation/ROTATION_LOG.jsonl | jq

# Disk usage trend
cat artifacts/soak/rotation/ROTATION_LOG.jsonl | jq '.disk_usage.size_mb'
```

### Recovery

**If artifacts accidentally deleted:**
1. Check CI artifact uploads: `gh run download <run-id>`
2. Restore from snapshots: `tar -xzf freeze_*.tar.gz`
3. Re-run iteration: Soak tests are idempotent

**If disk full:**
1. Aggressive cleanup: `--keep-latest 50 --ttl-days 3`
2. Purge old runs: `rm -rf artifacts/soak/latest/ITER_SUMMARY_{1..500}.json`
3. Compress all: `tar -czf soak-backup.tar.gz artifacts/soak/`

### Retention Recommendations

| Environment | keep-latest | ttl-days | max-size-mb | Rationale |
|-------------|-------------|----------|-------------|-----------|
| **Local Dev** | 50 | 3 | 500 | Fast iteration, limited disk |
| **CI (PR)** | 20 | 1 | 200 | Disposable, PR-scoped |
| **CI (Main)** | 100 | 7 | 900 | Keep history for regression |
| **Production** | 200 | 30 | 2000 | Audit trail, compliance |

---

## 🚨 Troubleshooting

### "Artifact rotation failed"

**Symptoms:** Exit code 1 from artifact_manager

**Causes:**
- Permission denied (Windows file lock)
- Path doesn't exist
- Corrupted JSONL log

**Resolution:**
```bash
# Check permissions
ls -la artifacts/soak/

# Verify path exists
test -d artifacts/soak && echo "OK" || echo "Missing"

# Validate log
cat artifacts/soak/rotation/ROTATION_LOG.jsonl | jq empty
```

### "Artifact size exceeds threshold"

**Symptoms:** Exit code 2, warning logged

**Causes:**
- Too many iterations (>500)
- Large snapshots not compressed
- TTL too long (>30 days)

**Resolution:**
```bash
# Identify large files
du -sh artifacts/soak/* | sort -h

# Aggressive rotation
python -m tools.soak.artifact_manager \
  --path artifacts/soak \
  --keep-latest 50 \
  --ttl-days 3

# Manual compress
tar -czf snapshots-$(date +%Y%m%d).tar.gz artifacts/soak/snapshots/
rm -rf artifacts/soak/snapshots/*.json
```

### "Permission denied" (Windows)

**Symptoms:** Cannot delete files on Windows self-hosted

**Cause:** File handles held by previous processes

**Resolution:**
```powershell
# Kill zombie processes
Get-Process python | Where-Object {$_.Path -like "*soak*"} | Stop-Process -Force

# Unlock files
Remove-Item -Force -Recurse artifacts\soak\latest\ITER_SUMMARY_*.json
```

---

## 📈 Monitoring & Alerts

### Metrics to Track

1. **Disk Usage Trend**
   ```bash
   # Plot size over time
   cat artifacts/soak/rotation/ROTATION_LOG.jsonl | \
     jq -r '[.timestamp, .disk_usage.size_mb] | @tsv'
   ```

2. **Rotation Efficiency**
   ```bash
   # Average reduction per rotation
   cat artifacts/soak/rotation/ROTATION_LOG.jsonl | \
     jq '.summary.disk_reduction_kb' | \
     awk '{sum+=$1; count++} END {print sum/count " KB avg"}'
   ```

3. **Threshold Violations**
   ```bash
   # Count warnings
   cat artifacts/soak/rotation/ROTATION_LOG.jsonl | \
     jq 'select(.disk_usage.within_limit == false)' | wc -l
   ```

### Alerts (Example Prometheus)

```yaml
# prometheus-rules.yml
groups:
  - name: soak-artifacts
    rules:
      - alert: SoakArtifactsLarge
        expr: soak_artifacts_size_mb > 900
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Soak artifacts directory exceeds 900MB"
          
      - alert: SoakRotationFailed
        expr: soak_rotation_failure_total > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Artifact rotation has failed"
```

---

## 🔄 Runbook: Disk Full Recovery

**Scenario:** CI fails with "No space left on device"

**Steps:**

1. **Assess Impact** (2 min)
   ```bash
   df -h
   du -sh /home/runner/work/mm-bot/mm-bot/artifacts/soak/
   ```

2. **Emergency Cleanup** (5 min)
   ```bash
   # Keep only last 10 iterations
   python -m tools.soak.artifact_manager \
     --path artifacts/soak \
     --keep-latest 10 \
     --ttl-days 1 \
     --max-size-mb 100
   ```

3. **Verify Space** (1 min)
   ```bash
   df -h
   # Should free 500MB-2GB
   ```

4. **Retry Job** (manual)
   ```bash
   gh run rerun <run-id>
   ```

5. **Post-Mortem** (after resolution)
   - Why did rotation fail?
   - Adjust retention policy
   - Add monitoring alert

---

## 📚 See Also

- **Artifact Manager Source:** `tools/soak/artifact_manager.py`
- **CI Integration:** `.github/workflows/soak-windows.yml`
- **Soak Test Guide:** `SOAK_TEST_QUICKSTART.md`
- **Architecture Audit:** `ARCHITECTURAL_AUDIT_COMPLETE.md`

---

*Last Updated: 2025-10-15*

