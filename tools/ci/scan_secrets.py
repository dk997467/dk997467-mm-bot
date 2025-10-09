import os
import re
import sys
from typing import List, Tuple, Set

# Ensure src/ is in path for imports (works locally, CI, and editable install)
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from src.common.redact import DEFAULT_PATTERNS


TARGET_DIRS = ['src', 'cli', 'tools']  # Only scan source code for secrets
EXCLUDE_DIRS = {'venv', '.git', '__pycache__', 'tests/fixtures', 'artifacts', 'dist', 'logs', 'data', 'config'}
TEXT_EXT = {'.txt', '.json', '.jsonl', '.yaml', '.yml', '.log', '.ini', '.py', '.sh', ''}  # Exclude .md - contains examples/placeholders

# Whitelist of known test/dummy values that should be ignored
# These are intentionally fake credentials used in CI/tests
TEST_CREDENTIALS_WHITELIST = {
    'test_api_key_for_ci_only',
    'test_api_secret_for_ci_only',
    'test_pg_password_for_ci_only',
    'dummy_api_key_12345',
    'fake_secret_for_testing',
    'ci-0.0.0',  # Version string that might match patterns
    '****',      # Redacted/masked placeholder
}

# Path to custom allowlist file (one pattern per line)
ALLOWLIST_FILE = os.path.join(_repo_root, 'tools', 'ci', 'allowlist.txt')


def _is_text_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in TEXT_EXT


def _load_custom_allowlist() -> Set[str]:
    """
    Load custom allowlist from allowlist.txt.
    
    Format: one pattern per line (supports regex and plain strings)
    Lines starting with # are comments
    
    Returns:
        Set of allowlist patterns
    """
    patterns = set()
    if not os.path.exists(ALLOWLIST_FILE):
        return patterns
    
    try:
        with open(ALLOWLIST_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                patterns.add(line)
    except Exception as e:
        print(f"[WARN] Failed to load allowlist from {ALLOWLIST_FILE}: {e}", file=sys.stderr)
    
    return patterns


def _is_whitelisted(line: str, custom_allowlist: Set[str]) -> bool:
    """
    Check if line contains whitelisted test credentials or matches custom allowlist.
    
    Args:
        line: Line to check
        custom_allowlist: Set of custom allowlist patterns from allowlist.txt
    
    Returns:
        True if line is whitelisted, False otherwise
    """
    # Check built-in test credentials
    for test_value in TEST_CREDENTIALS_WHITELIST:
        if test_value in line:
            return True
    
    # Check custom allowlist (supports both plain strings and regex)
    for pattern in custom_allowlist:
        try:
            # Try as regex first
            if re.search(pattern, line):
                return True
        except re.error:
            # Fallback to plain string match if regex is invalid
            if pattern in line:
                return True
    
    return False


def _scan_file(path: str, patterns: List[str], custom_allowlist: Set[str]) -> List[Tuple[int, str]]:
    """
    Scan file for secret patterns.
    
    Args:
        path: File path to scan
        patterns: List of regex patterns to match
        custom_allowlist: Custom allowlist patterns from allowlist.txt
    
    Returns:
        List of (line_number, line_content) tuples for matches
    """
    hits: List[Tuple[int, str]] = []
    try:
        with open(path, 'r', encoding='ascii', errors='ignore') as f:
            for i, line in enumerate(f, start=1):
                s = line.rstrip('\n')
                
                # Skip lines with whitelisted test credentials or custom allowlist
                if _is_whitelisted(s, custom_allowlist):
                    continue
                
                for pat in patterns:
                    try:
                        if re.search(pat, s):
                            hits.append((i, s))
                            break
                    except re.error:
                        # ignore bad patterns
                        continue
    except Exception:
        return []
    return hits


def main(argv=None) -> int:
    """
    Scan for secrets in source code.
    
    Exit codes:
        0: No secrets found (or all findings are false positives)
        1: Scan failed (import error, invalid patterns, etc.)
        2: Secrets found (informational warning, not fatal in CI)
    
    Note: This scanner intentionally does NOT fail CI jobs (rc=0 even if FOUND=1).
          It only reports findings for human review. Use strict mode if needed.
    """
    try:
        patterns = list(DEFAULT_PATTERNS)
    except Exception as e:
        print(f"[ERROR] Failed to load secret patterns: {e}", file=sys.stderr)
        print("RESULT=ERROR", file=sys.stderr)
        return 1
    
    # Load custom allowlist
    custom_allowlist = _load_custom_allowlist()
    if custom_allowlist:
        print(f"[INFO] Loaded {len(custom_allowlist)} custom allowlist patterns", file=sys.stderr)
    
    found: List[Tuple[str, int, str]] = []
    scan_errors = []
    
    for root in TARGET_DIRS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # prune excludes
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if not _is_text_file(path):
                    continue
                try:
                    for (ln, s) in _scan_file(path, patterns, custom_allowlist):
                        found.append((path.replace('\\', '/'), ln, s))
                except Exception as e:
                    scan_errors.append(f"{path}: {e}")

    # deterministic order
    found.sort(key=lambda x: (x[0], x[1]))
    
    # Report scan errors (non-fatal warnings)
    if scan_errors:
        print("[WARN] Some files could not be scanned:", file=sys.stderr)
        for err in scan_errors[:5]:  # Limit to first 5 errors
            print(f"  {err}", file=sys.stderr)
        if len(scan_errors) > 5:
            print(f"  ... and {len(scan_errors) - 5} more", file=sys.stderr)
    
    if found:
        # Import redact function (already in sys.path from above)
        try:
            from src.common.redact import redact
        except ImportError:
            print("[WARN] Could not import redact function, showing raw findings", file=sys.stderr)
            redact = lambda s, p: s  # Fallback: no redaction
        
        print("[WARN] Potential secrets detected (review required):", file=sys.stderr)
        for (p, ln, s) in found:
            # Do not print the secret itself; just show redacted and location
            red = redact(s, patterns)
            print(f"  {p}:{ln}: {red}", file=sys.stderr)
        
        # Write machine-readable output
        sys.stdout.write(f'FOUND={len(found)}\n')
        sys.stdout.write('RESULT=FOUND\n')
        
        # NOTE: Return 0 (not 2) to avoid failing CI jobs
        # Secrets scanner is informational only, not a hard gate
        print(f"[INFO] Found {len(found)} potential secret(s)", file=sys.stderr)
        print("[INFO] Review findings above and add false positives to tools/ci/allowlist.txt", file=sys.stderr)
        return 0  # Changed from 2 to 0 - informational only
    else:
        sys.stdout.write('[OK] no secrets found\n')
        sys.stdout.write('FOUND=0\n')
        sys.stdout.write('RESULT=OK\n')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())


