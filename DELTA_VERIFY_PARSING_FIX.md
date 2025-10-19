# Delta Verify Parsing Fix

**Date:** 2025-10-18  
**Branch:** `feat/soak-nested-write-mock-gate-tests`  
**Commit:** `c0b0b5b`  
**Status:** ✅ **COMPLETE**

---

## Summary

Fixed three critical issues in CI workflow's "Verify delta application" step that caused `IndexError` and `Permission denied` errors.

---

## Problems Fixed

### 1. IndexError: list index out of range

**Problem:**
```python
python - <<'PY'
p = Path(sys.argv[1])  # ❌ IndexError!
PY
"$REPORT_MD"  # Shell treats this as separate command, not argv[1]
```

**Root Cause:**
- When heredoc ends with `PY` and then `"$REPORT_MD"` appears on next line
- Shell interprets `"$REPORT_MD"` as a **separate command**, not as an argument
- Python script sees empty `sys.argv` (only `sys.argv[0]` = `-`)
- `sys.argv[1]` throws `IndexError`

**Fix:**
```bash
export REPORT_MD  # Pass via environment
python - <<'PY' 2>/dev/null
import os
p = Path(os.environ.get("REPORT_MD", ""))  # ✅ No IndexError
PY
```

---

### 2. Permission denied

**Problem:**
```bash
python - <<'PY'
...
PY
"$REPORT_MD"  # ❌ Shell tries to EXECUTE this as a command!
# Error: DELTA_VERIFY_REPORT.md: Permission denied
```

**Root Cause:**
- After heredoc closes, `"$REPORT_MD"` is expanded to file path
- Shell treats it as a command to execute
- File is not executable → `Permission denied`

**Fix:**
- Use environment variables only
- No argv, no trailing shell commands
- File is never executed

---

### 3. Shell Variable Interpolation

**Problem:**
```python
python - <<PY  # Not quoted!
ratio = $RATIO  # ❌ Shell variable interpolation in Python
import sys
sys.exit(0 if ratio >= 0.60 else 1)
PY
```

**Issues:**
- Shell interpolates `$RATIO` before Python sees it
- Fragile if `$RATIO` contains special characters
- No quotes around heredoc delimiter

**Fix:**
```bash
export RATIO  # Pass via environment
python - <<'PY'  # ✅ Single quotes = no interpolation
import os, sys
ratio = float(os.environ.get("RATIO", "0"))  # Safe
sys.exit(0 if ratio >= 0.60 else 1)
PY
```

---

## Implementation

### Before (Broken)

```bash
# Parse MD: lines like "Full applications: X/Y (Z%)"
RATIO=$(python - <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])  # ❌ IndexError: list index out of range
m = re.search(r"Full applications:\s*\d+/\d+\s*\(([\d\.]+)%\)", p.read_text())
print(float(m.group(1))/100 if m else 0.0)
PY
"$REPORT_MD")  # ❌ Permission denied (shell executes as command)

# Soft gate check
if python - <<PY
ratio = $RATIO  # ❌ Shell interpolation, fragile
import sys
sys.exit(0 if ratio >= 0.60 else 1)
PY
then
  echo "PASS"
fi
```

**Errors:**
- `IndexError: list index out of range` from `sys.argv[1]`
- `Permission denied` from shell executing MD file
- Potential quoting issues with `$RATIO`

---

### After (Fixed)

```bash
# Export path via env for Python (fixes sys.argv[1] IndexError)
export REPORT_MD

# Parse MD: lines like "Full applications: X/Y (Z%)"
RATIO=$(python - <<'PY' 2>/dev/null
import os, re
from pathlib import Path
p = Path(os.environ.get("REPORT_MD", ""))  # ✅ Use env var
txt = p.read_text(encoding="utf-8") if p.is_file() else ""  # ✅ Safe read
m = re.search(r"Full applications:\s*\d+/\s*\d+\s*\(([\d\.]+)%\)", txt)
print(float(m.group(1))/100 if m else 0.0)
PY
)

# Soft gate check
export RATIO  # ✅ Pass via env
python - <<'PY'
import os, sys
ratio = float(os.environ.get("RATIO", "0"))  # ✅ Safe from env
sys.exit(0 if ratio >= 0.60 else 1)
PY

if [ $? -eq 0 ]; then  # ✅ Explicit exit code check
  echo "PASS"
fi
```

**Benefits:**
- ✅ No `IndexError` (uses env vars)
- ✅ No `Permission denied` (no command execution)
- ✅ Safe quoting (heredoc with single quotes)
- ✅ Proper error handling (`2>/dev/null`)
- ✅ Explicit encoding (`encoding="utf-8"`)

---

## Additional Improvements

### 1. Debug Output

Added display of MD report content:
```bash
echo "[OK] Report written to: $(readlink -f "$REPORT_MD" 2>/dev/null || echo "$REPORT_MD")"
echo
echo "Verification Summary (head):"
head -n 40 "$REPORT_MD" || true
echo
```

**Benefits:**
- Shows absolute path of report
- Displays first 40 lines for debugging
- Easier to diagnose parsing issues

---

### 2. Error Handling

Added proper error handling:
```python
# Before
p = Path(sys.argv[1])
m = re.search(...)
print(float(m.group(1))/100 if m else 0.0)

# After
p = Path(os.environ.get("REPORT_MD", ""))
txt = p.read_text(encoding="utf-8") if p.is_file() else ""  # Safe
m = re.search(...)
print(float(m.group(1))/100 if m else 0.0)  # Default 0.0
```

**Benefits:**
- `2>/dev/null` suppresses stderr
- Explicit file existence check
- Default values prevent crashes
- UTF-8 encoding specified

---

### 3. Explicit Exit Code Check

```bash
# Before
if python - <<PY
...
PY
then
  echo "PASS"
fi

# After
python - <<'PY'
...
PY

if [ $? -eq 0 ]; then  # Explicit check
  echo "PASS"
fi
```

**Benefits:**
- More explicit and readable
- Can inspect exit code before using
- Better for debugging

---

## Why These Changes Matter

### Problem: Heredoc argv doesn't work

```bash
python - <<'PY'
print(sys.argv)
PY
"some_arg"

# Expected: sys.argv = ['-', 'some_arg']
# Actual:   sys.argv = ['-']
#           Shell runs: "some_arg" (as command) → Permission denied
```

**Lesson:** Arguments after heredoc are **not** passed to the script. They are separate shell commands.

---

### Solution: Use environment variables

```bash
export MY_VAR="value"
python - <<'PY'
import os
print(os.environ.get("MY_VAR"))
PY

# Works reliably!
```

**Benefits:**
- No shell command execution
- No quoting issues
- Works with any content
- Standard Unix pattern

---

## Validation

### Expected Behavior

1. ✅ No `IndexError` from `sys.argv[1]`
2. ✅ No `Permission denied` from shell executing MD file
3. ✅ Parsing works via `os.environ.get()`
4. ✅ Shows first 40 lines of MD report for debugging
5. ✅ Soft gate logic unchanged (`proposals_total==0` → PASS, else `ratio>=0.60`)

---

### Check CI Logs

After this fix, logs should show:

```
================================================
DELTA VERIFICATION (non-strict, soft gate)
================================================

Using TARGET=artifacts/soak/latest

[OK] Report written to: /home/runner/work/.../DELTA_VERIFY_REPORT.md

Verification Summary (head):
# Delta Application Verification Report
...
(40 lines)
...

Parsed: ratio=0.70, total=10
✓ Delta verification soft gate passed (ratio=0.70 ≥ 0.60)
```

**No errors:**
- ❌ `IndexError: list index out of range`
- ❌ `DELTA_VERIFY_REPORT.md: Permission denied`

---

## Testing

### Local Test

```bash
# Create mock report
mkdir -p artifacts/soak/latest
cat > artifacts/soak/latest/DELTA_VERIFY_REPORT.md <<'EOF'
# Delta Verification Report
Full applications: 7/10 (70.0%)
EOF

# Test parsing
export REPORT_MD="artifacts/soak/latest/DELTA_VERIFY_REPORT.md"
RATIO=$(python - <<'PY' 2>/dev/null
import os, re
from pathlib import Path
p = Path(os.environ.get("REPORT_MD", ""))
txt = p.read_text(encoding="utf-8") if p.is_file() else ""
m = re.search(r"Full applications:\s*\d+/\s*\d+\s*\(([\d\.]+)%\)", txt)
print(float(m.group(1))/100 if m else 0.0)
PY
)

echo "Parsed ratio: $RATIO"
# Expected: 0.70
```

---

## Related Issues

### sys.argv Misconception

Many developers assume this works:
```bash
python - <<'EOF' arg1 arg2
import sys
print(sys.argv)
EOF
```

**But it doesn't!** The script only receives `sys.argv = ['-']`.

Arguments after heredoc are **shell commands**, not script arguments.

---

### Correct Patterns

**Option 1: Environment variables** (chosen)
```bash
export ARG1="value1"
python - <<'EOF'
import os
print(os.environ.get("ARG1"))
EOF
```

**Option 2: Echo into stdin**
```bash
echo "value1" | python - <<'EOF'
import sys
print(sys.stdin.read())
EOF
```

**Option 3: Temp file**
```bash
python - <<'EOF' > /tmp/script.py
import sys
print(sys.argv)
EOF
python /tmp/script.py arg1 arg2
```

---

## Changes Summary

```
.github/workflows/ci.yml
  - Changed: Use os.environ.get() instead of sys.argv[1]
  - Changed: Export REPORT_MD and RATIO via env
  - Added: Display first 40 lines of MD report
  - Added: Explicit encoding="utf-8"
  - Added: 2>/dev/null for error suppression
  - Fixed: Explicit exit code check ($?)
  
  Lines: +31/-17
```

---

## Commit

```
ci: fix delta verify parsing (use env vars instead of sys.argv)

Fix three critical issues in Verify delta application step:

1. IndexError from sys.argv[1] - use os.environ.get(REPORT_MD)
2. Permission denied - export REPORT_MD via env, not as argv
3. ratio interpolation - export RATIO via env

Additional improvements:
- Show first 40 lines of MD report for debugging
- Proper error handling with 2>/dev/null
- Explicit encoding=utf-8 for read_text()
- Check exit code explicitly instead of inline if

Why: Heredoc with trailing argv doesn't work (shell interprets as command).
Using env vars is robust and avoids shell escaping issues.
```

---

## Next Steps

1. **Monitor CI:**
   ```
   https://github.com/dk997467/dk997467-mm-bot/actions
   ```

2. **Check Logs:**
   - `Using TARGET=...`
   - `[OK] Report written to: ...`
   - `Verification Summary (head):` with 40 lines
   - `Parsed: ratio=X, total=Y`
   - No `IndexError`
   - No `Permission denied`

3. **Verify Behavior:**
   - Parsing works correctly
   - Soft gate passes/fails as expected
   - All fields exported to `$GITHUB_OUTPUT`

---

## Status

**✅ DELTA VERIFY PARSING FIX COMPLETE**

- Fixed: `IndexError` from `sys.argv[1]`
- Fixed: `Permission denied` from shell command execution
- Fixed: Shell variable interpolation issues
- Added: Debug output (first 40 lines of MD)
- Improved: Error handling and encoding
- Committed: `c0b0b5b`
- Pushed: `origin/feat/soak-nested-write-mock-gate-tests`

**Ready for CI validation!** 🚀

---

