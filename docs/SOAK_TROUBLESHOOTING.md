# Soak CI Troubleshooting Guide

## Common Issues and Solutions

### Issue: "No KPI file found for auto-detect mode"

**Symptom:**
```
[kpi_gate] No args and no default artifacts found; failing fast.
Usage: python -m tools.soak.kpi_gate [<path>|--weekly <path>|--iter <path>|--test]
No KPI file found for auto-detect mode
```

**Root Causes:**

1. **kpi_gate called without arguments**
   - **Problem**: Legacy code or workflow step invokes `python -m tools.soak.kpi_gate` with no arguments
   - **Detection**: Check workflow logs for kpi_gate invocation without `--iter` or path argument
   - **Solution**: All kpi_gate calls MUST use explicit arguments:
     ```bash
     # Linux/macOS
     python -m tools.soak.kpi_gate --iter "artifacts/soak/latest/ITER_SUMMARY_*.json"
     
     # Windows PowerShell
     python -m tools.soak.kpi_gate --iter "artifacts/soak/latest/ITER_SUMMARY_*.json"
     ```

2. **No ITER_SUMMARY files generated**
   - **Problem**: Soak run didn't produce any iteration summaries
   - **Detection**: Check diagnostics output:
     ```
     Found 0 ITER_SUMMARY files
     No ITER_SUMMARY files found
     ```
   - **Solution**: 
     - Verify soak run completed successfully
     - Check if soak runner is writing to correct directory
     - Ensure at least 1 iteration ran before report generation

3. **Wrong working directory**
   - **Problem**: CI step runs from subdirectory instead of repo root
   - **Detection**: Check diagnostics:
     ```
     PWD=/some/wrong/path
     workspace=/github/workspace
     ```
   - **Solution**: Add `working-directory: ${{ github.workspace }}` to step

4. **Incorrect PYTHONPATH**
   - **Problem**: Python imports wrong version of kpi_gate module (cached/system)
   - **Detection**: Module behavior doesn't match recent code changes
   - **Solution**: Ensure PYTHONPATH is set in job env:
     ```yaml
     env:
       PYTHONPATH: ${{ github.workspace }}  # Linux
       # OR
       PYTHONPATH: "${{ github.workspace }};${{ github.workspace }}\\src"  # Windows
     ```

5. **SOAK_ARTIFACTS_DIR not set or wrong**
   - **Problem**: Hard fallback in kpi_gate.py uses wrong directory
   - **Detection**: Fallback tries wrong path
   - **Solution**: Set in job env:
     ```yaml
     env:
       SOAK_ARTIFACTS_DIR: artifacts/soak/latest
     ```

---

### Issue: "readiness.json not created"

**Symptom:**
```
⚠ readiness.json not created
```
or downstream unified summary fails with:
```
FileNotFoundError: artifacts/reports/readiness.json
```

**Root Causes:**

1. **write_readiness step skipped**
   - **Problem**: Step has conditional `if:` that evaluates to false
   - **Solution**: Always use `if: always()` for write_readiness step:
     ```yaml
     - name: Write readiness.json
       if: always()
       continue-on-error: true
     ```

2. **No ITER_SUMMARY files found**
   - **Problem**: write_readiness.py can't find input files
   - **Detection**: Check step output:
     ```
     [write_readiness] WARN: No files found matching artifacts/soak/latest/ITER_SUMMARY_*.json
     [write_readiness] Writing HOLD status (no data)
     ```
   - **Solution**: 
     - Verify soak run produced ITER_SUMMARY files
     - Check glob pattern matches file naming convention
     - Ensure working-directory is set correctly

3. **Permission/path issues**
   - **Problem**: Can't write to artifacts/reports/ directory
   - **Detection**: Python traceback with PermissionError or FileNotFoundError
   - **Solution**: Ensure artifacts/reports/ directory exists and is writable

---

### Issue: KPI Gate fails with "glob pattern not expanded"

**Symptom:**
```
FileNotFoundError: artifacts/soak/latest/ITER_SUMMARY_*.json
```
(literal asterisk in path)

**Root Cause:**
Shell expanded glob before passing to Python, but no files matched

**Solution:**
Always quote the glob pattern:
```bash
# ✅ CORRECT (Linux)
python -m tools.soak.kpi_gate --iter "artifacts/soak/latest/ITER_SUMMARY_*.json"

# ✅ CORRECT (Windows PowerShell)
$iterGlob = "artifacts/soak/latest/ITER_SUMMARY_*.json"
python -m tools.soak.kpi_gate --iter "$iterGlob"

# ❌ WRONG (shell expands too early)
python -m tools.soak.kpi_gate --iter artifacts/soak/latest/ITER_SUMMARY_*.json
```

---

## Diagnostic Checklist

When investigating soak CI failures, check these in order:

### 1. Working Directory
```yaml
# In workflow logs, look for:
PWD=/github/workspace          # ✅ GOOD
PWD=/github/workspace/tools    # ❌ BAD
```

**Fix:** Add `working-directory: ${{ github.workspace }}` to step

### 2. PYTHONPATH
```yaml
# In workflow logs:
PYTHONPATH=/github/workspace           # ✅ GOOD (Linux)
PYTHONPATH=C:\actions-runner\_work\... # ✅ GOOD (Windows)
PYTHONPATH=                            # ❌ BAD (not set)
```

**Fix:** Set in job env block

### 3. SOAK_ARTIFACTS_DIR
```yaml
# In workflow logs:
SOAK_ARTIFACTS_DIR=artifacts/soak/latest  # ✅ GOOD
SOAK_ARTIFACTS_DIR=                       # ⚠️ Will use default
```

**Fix:** Set in job env block (optional, has default)

### 4. File Presence
```yaml
# In "List Soak Artifacts" step output:
Found 3 ITER_SUMMARY files           # ✅ GOOD
-rw-r--r-- ITER_SUMMARY_1.json
-rw-r--r-- ITER_SUMMARY_2.json
-rw-r--r-- ITER_SUMMARY_3.json

Found 0 ITER_SUMMARY files           # ❌ BAD
No ITER_SUMMARY files found
```

**Fix:** Debug soak runner; ensure it writes files before report generation

### 5. KPI Gate Invocation
```yaml
# Look for explicit arguments:
python -m tools.soak.kpi_gate --iter "artifacts/soak/latest/ITER_SUMMARY_*.json"  # ✅ GOOD
python -m tools.soak.kpi_gate artifacts/soak/latest/SOAK_KPI.json                 # ✅ GOOD
python -m tools.soak.kpi_gate                                                      # ❌ BAD
```

**Fix:** Add explicit arguments to all kpi_gate calls

---

## Expected Diagnostic Output

### Good Run (Linux)

```
================================================
SOAK ARTIFACTS DIAGNOSTIC (Linux)
================================================
PWD=/home/runner/work/mm-bot/mm-bot
workspace=/home/runner/work/mm-bot/mm-bot
PYTHONPATH=/home/runner/work/mm-bot/mm-bot
SOAK_ARTIFACTS_DIR=artifacts/soak/latest

Artifacts in artifacts/soak/latest:
total 120K
drwxr-xr-x  2 runner docker 4.0K Oct 20 15:30 .
drwxr-xr-x  3 runner docker 4.0K Oct 20 15:25 ..
-rw-r--r--  1 runner docker 8.1K Oct 20 15:27 ITER_SUMMARY_1.json
-rw-r--r--  1 runner docker 8.2K Oct 20 15:28 ITER_SUMMARY_2.json
-rw-r--r--  1 runner docker 8.3K Oct 20 15:29 ITER_SUMMARY_3.json
-rw-r--r--  1 runner docker  12K Oct 20 15:30 SOAK_KPI.json

ITER_SUMMARY files:
Found 3 ITER_SUMMARY files
-rw-r--r-- 1 runner docker 8.1K Oct 20 15:27 artifacts/soak/latest/ITER_SUMMARY_1.json
-rw-r--r-- 1 runner docker 8.2K Oct 20 15:28 artifacts/soak/latest/ITER_SUMMARY_2.json
-rw-r--r-- 1 runner docker 8.3K Oct 20 15:29 artifacts/soak/latest/ITER_SUMMARY_3.json

================================================
KPI GATE (Linux)
================================================
Using SOAK_KPI.json
[kpi_gate] Loaded: artifacts/soak/latest/SOAK_KPI.json
✓ KPI Gate PASSED

================================================
WRITING READINESS.JSON (Linux)
================================================
[write_readiness] Found 3 iteration summaries
[write_readiness] status=OK → artifacts/reports/readiness.json
[write_readiness] maker_taker=0.891 (>= 0.83)
[write_readiness] net_bps=3.12 (>= 2.9)
[write_readiness] p95_latency_ms=285 (<= 330)
[write_readiness] risk_ratio=0.32 (<= 0.40)

✓ readiness.json created:
{
  "status": "OK",
  "maker_taker": 0.891,
  "net_bps": 3.12,
  "p95_latency_ms": 285,
  "risk_ratio": 0.32
}
```

### Good Run (Windows)

```
================================================
SOAK ARTIFACTS DIAGNOSTIC (Windows)
================================================
PWD=C:\actions-runner\_work\mm-bot\mm-bot
workspace=C:\actions-runner\_work\mm-bot\mm-bot
PYTHONPATH=C:\actions-runner\_work\mm-bot\mm-bot;C:\actions-runner\_work\mm-bot\mm-bot\src
SOAK_ARTIFACTS_DIR=artifacts/soak/latest

Artifacts in artifacts\soak\latest:

    Directory: C:\actions-runner\_work\mm-bot\mm-bot\artifacts\soak\latest

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---          20.10.2025    15:27           8301 ITER_SUMMARY_1.json
-a---          20.10.2025    15:28           8421 ITER_SUMMARY_2.json
-a---          20.10.2025    15:29           8502 ITER_SUMMARY_3.json
-a---          20.10.2025    15:30          12405 SOAK_KPI.json

ITER_SUMMARY files:
Found 3 ITER_SUMMARY files

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---          20.10.2025    15:27           8301 ITER_SUMMARY_1.json
-a---          20.10.2025    15:28           8421 ITER_SUMMARY_2.json
-a---          20.10.2025    15:29           8502 ITER_SUMMARY_3.json

================================================
KPI GATE (Windows)
================================================
Using SOAK_KPI.json
[kpi_gate] Loaded: artifacts\soak\latest\SOAK_KPI.json
✓ KPI Gate PASSED

================================================
WRITING READINESS.JSON (Windows)
================================================
[write_readiness] Found 3 iteration summaries
[write_readiness] status=OK → artifacts\reports\readiness.json
[write_readiness] maker_taker=0.891 (>= 0.83)
[write_readiness] net_bps=3.12 (>= 2.9)
[write_readiness] p95_latency_ms=285 (<= 330)
[write_readiness] risk_ratio=0.32 (<= 0.40)

✓ readiness.json created:
{
  "status": "OK",
  "maker_taker": 0.891,
  "net_bps": 3.12,
  "p95_latency_ms": 285,
  "risk_ratio": 0.32
}
```

---

## Quick Fixes

### Fix: Update workflow to remove auto-mode

**Before (❌ BAD):**
```yaml
- name: KPI Gate
  run: python -m tools.soak.kpi_gate
```

**After (✅ GOOD):**
```yaml
- name: KPI Gate (explicit path or iter mask)
  working-directory: ${{ github.workspace }}
  run: |
    if [ -f artifacts/soak/latest/SOAK_KPI.json ] && [ -s artifacts/soak/latest/SOAK_KPI.json ]; then
      python -m tools.soak.kpi_gate artifacts/soak/latest/SOAK_KPI.json
    else
      python -m tools.soak.kpi_gate --iter "artifacts/soak/latest/ITER_SUMMARY_*.json"
    fi
```

### Fix: Ensure readiness.json always created

```yaml
- name: Write readiness.json
  if: always()                           # ← Always run, even if KPI gate failed
  continue-on-error: true                # ← Don't fail job if this fails
  working-directory: ${{ github.workspace }}
  run: |
    python -m tools.soak.write_readiness \
      --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
      --out "artifacts/reports/readiness.json" \
      --min_maker_taker 0.83 --min_edge 2.9 --max_latency 330 --max_risk 0.40
```

### Fix: Add diagnostics before KPI gate

```yaml
- name: List Soak Artifacts
  if: always()
  working-directory: ${{ github.workspace }}
  run: |
    echo "PWD=$(pwd)"
    echo "workspace=${{ github.workspace }}"
    echo "PYTHONPATH=$PYTHONPATH"
    echo "SOAK_ARTIFACTS_DIR=$SOAK_ARTIFACTS_DIR"
    echo ""
    ls -lah artifacts/soak/latest || echo "Directory not found"
    echo ""
    ITER_COUNT=$(ls artifacts/soak/latest/ITER_SUMMARY_*.json 2>/dev/null | wc -l || echo 0)
    echo "Found $ITER_COUNT ITER_SUMMARY files"
```

---

## Artifact Collection on Failure

When soak CI fails, two artifact sets are uploaded:

### 1. Main Artifacts (always uploaded)
- `artifacts/reports/readiness.json` - KPI summary and verdict
- `artifacts/soak/latest/SOAK_KPI.json` - Aggregated KPIs
- `artifacts/soak/latest/ITER_SUMMARY_*.json` - Per-iteration summaries

### 2. Debug Artifacts (failure only)
- **All** files in `artifacts/` (full history)
- All `.log` files in repo root
- All `.err.log` files recursively

**Access:** Download from workflow run → "Artifacts" section

---

## Prevention Checklist

When adding new soak workflow steps:

- [ ] Set `working-directory: ${{ github.workspace }}`
- [ ] Use `if: always()` for report/artifact steps
- [ ] Add `continue-on-error: true` for non-critical steps
- [ ] Pass explicit args to `kpi_gate` (never rely on auto-detect)
- [ ] Add diagnostic output (pwd, file counts, env vars)
- [ ] Test with zero iterations (should fail gracefully, not crash)
- [ ] Verify PYTHONPATH includes repo root

---

## References

- **kpi_gate hard fallback**: `tools/soak/kpi_gate.py` lines 301-333
- **write_readiness**: `tools/soak/write_readiness.py`
- **Workflows**: 
  - Linux: `.github/workflows/soak.yml`
  - Windows: `.github/workflows/soak-windows.yml`

---

## Contact

For issues not covered here, check:
1. Workflow run logs (full output with diagnostics)
2. Downloaded artifacts (ITER_SUMMARY files, logs)
3. Recent commits to `tools/soak/` modules

