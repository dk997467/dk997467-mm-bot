"""
Secret scanner for CI pipeline.

Scans source code for hardcoded credentials using focused patterns.
Exports module-level constants for backward-compatibility with tests.
"""
import os
import re
import sys
import argparse
import fnmatch
from typing import List, Tuple, Set
from pathlib import Path

# Ensure src/ is in path for imports (works locally, CI, and editable install)
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


# Public exports (for backward-compatibility with tests)
__all__ = ['DEFAULT_PATTERNS', 'TARGET_DIRS', 'ALLOWLIST_FILE', 'main']


# Target directories for scanning (source code only)
TARGET_DIRS = ['src', 'tools', 'scripts']

# Directories to ignore during traversal
IGNORE_DIRS = {
    '.git', '.github', '.venv', 'venv', '__pycache__',
    'artifacts', 'reports', 'dist', 'build',
    'node_modules', '.pytest_cache', 'htmlcov',
    'golden', 'presets',  # Tuning/test data
}

# File patterns to ignore (globs)
IGNORE_GLOBS = [
    '**/*.md',           # Documentation (contains examples)
    '**/*.png', '**/*.jpg', '**/*.jpeg', '**/*.gif', '**/*.svg',  # Images
    '**/*.csv', '**/*.parquet', '**/*.arrow',  # Data files
    '**/*.ipynb',        # Jupyter notebooks
    '**/*.pyc', '**/*.pyo',  # Compiled Python
]

# Text file extensions to scan
TEXT_EXT = {'.txt', '.json', '.jsonl', '.yaml', '.yml', '.log', '.ini', '.py', '.sh', ''}

# Focused secret patterns (high-signal only)
# NOTE: These are INDEPENDENT of src.common.redact.DEFAULT_PATTERNS
# We use focused patterns here to reduce false positives in CI scanning
FOCUSED_SECRET_PATTERNS = [
    # AWS credentials
    r'AKIA[0-9A-Z]{16}',  # AWS Access Key ID
    r'ASIA[0-9A-Z]{16}',  # AWS temp key
    r'(?i)aws_secret_access_key\s*[=:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?',
    
    # GitHub tokens
    r'ghp_[0-9A-Za-z]{36,}',  # GitHub PAT
    r'gho_[0-9A-Za-z]{36,}',  # GitHub OAuth
    r'ghs_[0-9A-Za-z]{36,}',  # GitHub server-to-server
    
    # Stripe keys
    r'sk_live_[0-9A-Za-z]{24,}',  # Stripe live secret
    r'sk_test_[0-9A-Za-z]{24,}',  # Stripe test (still sensitive)
    r'rk_live_[0-9A-Za-z]{24,}',  # Stripe restricted
    
    # Slack tokens
    r'xoxb-[0-9A-Za-z\-]{20,}',  # Slack bot token
    r'xoxp-[0-9A-Za-z\-]{20,}',  # Slack user token
    
    # Google API key
    r'AIza[0-9A-Za-z\-_]{35}',
    
    # Facebook token
    r'EAACEdEose0cBA[0-9A-Za-z]+',
    
    # SSH private key blocks
    r'-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----',
    r'-----BEGIN PRIVATE KEY-----',
    
    # Generic high-entropy secrets (key/token/secret in name)
    r'(?i)(?:api_key|api-key|apikey)\s*[=:]\s*["\']([A-Za-z0-9_\-]{16,})["\']',
    r'(?i)(?:secret_key|secret-key|secretkey)\s*[=:]\s*["\']([A-Za-z0-9_\-]{16,})["\']',
    r'(?i)(?:auth_token|auth-token|authtoken)\s*[=:]\s*["\']([A-Za-z0-9_.\-]{20,})["\']',
]

# Backward-compatibility: Export as DEFAULT_PATTERNS for tests that monkeypatch
# This must be a module-level list (not a property) so monkeypatch can replace it
DEFAULT_PATTERNS = FOCUSED_SECRET_PATTERNS

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


def _should_ignore_file(path: str) -> bool:
    """Check if file should be ignored based on IGNORE_GLOBS."""
    normalized = path.replace('\\', '/')
    for glob_pattern in IGNORE_GLOBS:
        if fnmatch.fnmatch(normalized, glob_pattern):
            return True
    return False


def _is_text_file(path: str) -> bool:
    """Check if file is a text file and should be scanned."""
    if _should_ignore_file(path):
        return False
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


def _is_whitelisted(line: str, file_path: str, custom_allowlist: Set[str]) -> bool:
    """
    Check if line or file path matches allowlist.
    
    Args:
        line: Line content to check
        file_path: File path (for glob matching)
        custom_allowlist: Set of custom allowlist patterns from allowlist.txt
    
    Returns:
        True if line/path is whitelisted, False otherwise
    """
    # Check built-in test credentials
    for test_value in TEST_CREDENTIALS_WHITELIST:
        if test_value in line:
            return True
    
    # Normalize file path for matching
    normalized_path = file_path.replace('\\', '/')
    
    # Check custom allowlist (supports regex, glob, and plain strings)
    for pattern in custom_allowlist:
        # 1. Check if pattern is a path glob (contains / or ends with file extension pattern)
        is_path_pattern = '/' in pattern or pattern.endswith('/**') or pattern.startswith('**/') or pattern.endswith('.py') or pattern.endswith('.json') or pattern.endswith('.yaml')
        
        if is_path_pattern:
            # This is a path glob pattern
            try:
                if fnmatch.fnmatch(normalized_path, pattern):
                    return True
                # Also try matching against basename
                if fnmatch.fnmatch(os.path.basename(normalized_path), pattern):
                    return True
            except:
                pass
            continue  # Don't try as line content match
        
        # 2. Check if pattern matches line content
        # First, try as plain string (most common case)
        if pattern in line:
            return True
        
        # 3. If pattern starts with ^ or ends with $, treat as regex
        if pattern.startswith('^') or pattern.endswith('$'):
            try:
                if re.search(pattern, line):
                    return True
            except re.error:
                pass
    
    return False


def _scan_file(path: str, patterns: List[str], custom_allowlist: Set[str]) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    """
    Scan file for secret patterns.
    
    Args:
        path: File path to scan
        patterns: List of regex patterns to match
        custom_allowlist: Custom allowlist patterns from allowlist.txt
    
    Returns:
        Tuple of (real_hits, allowlisted_hits)
        - real_hits: Findings not covered by allowlist
        - allowlisted_hits: Findings covered by allowlist
    """
    real_hits: List[Tuple[int, str]] = []
    allowlisted_hits: List[Tuple[int, str]] = []
    
    try:
        with open(path, 'r', encoding='ascii', errors='ignore') as f:
            for i, line in enumerate(f, start=1):
                s = line.rstrip('\n')
                
                # Check if line matches any pattern
                matched = False
                for pat in patterns:
                    try:
                        if re.search(pat, s):
                            matched = True
                            break
                    except re.error:
                        continue
                
                if not matched:
                    continue
                
                # Check if finding is allowlisted
                if _is_whitelisted(s, path, custom_allowlist):
                    allowlisted_hits.append((i, s))
                else:
                    real_hits.append((i, s))
    except Exception:
        return ([], [])
    
    return (real_hits, allowlisted_hits)


def main(argv=None) -> int:
    """
    Scan for secrets in source code.
    
    Exit codes:
        0: No secrets found OR all findings are allowlisted (unless --strict)
        1: Real secrets found OR allowlisted findings in strict mode
    
    Environment:
        CI_STRICT_SECRETS=1: Enable strict mode (exit 1 on any findings)
    """
    parser = argparse.ArgumentParser(description="Scan for secrets in source code")
    parser.add_argument('--strict', action='store_true', 
                       help='Exit 1 even if all findings are allowlisted')
    parser.add_argument('--paths', nargs='+', 
                       help='Override TARGET_DIRS with custom paths to scan')
    args = parser.parse_args(argv)
    
    # Check for strict mode from env or CLI
    strict_mode = args.strict or os.environ.get('CI_STRICT_SECRETS') == '1'
    
    # Use DEFAULT_PATTERNS (can be monkeypatched by tests)
    patterns = DEFAULT_PATTERNS
    
    # Load custom allowlist
    custom_allowlist = _load_custom_allowlist()
    if custom_allowlist:
        print(f"[INFO] Loaded {len(custom_allowlist)} custom allowlist patterns", file=sys.stderr)
    
    # Determine directories to scan
    scan_dirs = args.paths if args.paths else TARGET_DIRS
    
    real_findings: List[Tuple[str, int, str]] = []
    allowlisted_findings: List[Tuple[str, int, str]] = []
    scan_errors = []
    files_scanned = 0
    
    for root in scan_dirs:
        # Convert relative paths to absolute paths relative to _repo_root
        if not os.path.isabs(root):
            root = os.path.join(_repo_root, root)
        
        if not os.path.exists(root):
            print(f"[WARN] Path does not exist: {root}", file=sys.stderr)
            continue
        
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune ignored directories
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                
                if not _is_text_file(path):
                    continue
                
                files_scanned += 1
                
                try:
                    real_hits, allowlisted_hits = _scan_file(path, patterns, custom_allowlist)
                    
                    # Normalize path for consistent output
                    normalized_path = path.replace('\\', '/')
                    
                    # Collect findings
                    for (ln, s) in real_hits:
                        real_findings.append((normalized_path, ln, s))
                    
                    for (ln, s) in allowlisted_hits:
                        allowlisted_findings.append((normalized_path, ln, s))
                        
                except Exception as e:
                    scan_errors.append(f"{path}: {e}")

    # Deterministic order (ASCII-only, stable sort)
    real_findings.sort(key=lambda x: (x[0], x[1]))
    allowlisted_findings.sort(key=lambda x: (x[0], x[1]))
    
    # Print scan summary
    total_matches = len(real_findings) + len(allowlisted_findings)
    print(f"[INFO] Scanned {files_scanned} file(s), {total_matches} match(es) found", file=sys.stderr)
    print(f"[INFO] Real: {len(real_findings)}, Allowlisted: {len(allowlisted_findings)}", file=sys.stderr)
    
    # Report scan errors (non-fatal warnings)
    if scan_errors:
        print("[WARN] Some files could not be scanned:", file=sys.stderr)
        for err in sorted(scan_errors)[:5]:  # Deterministic order, limit to 5
            print(f"  {err}", file=sys.stderr)
        if len(scan_errors) > 5:
            print(f"  ... and {len(scan_errors) - 5} more", file=sys.stderr)
    
    # Import redact function for output masking
    try:
        from src.common.redact import redact
    except ImportError:
        print("[WARN] Could not import redact function, showing raw findings", file=sys.stderr)
        redact = lambda s, p: s  # Fallback: no redaction
    
    # PRIORITY 1: Real findings in repo (not allowlisted) → exit 1
    if real_findings:
        print("[ERROR] Real secrets detected (NOT allowlisted):", file=sys.stderr)
        for (p, ln, s) in real_findings[:20]:  # Limit output to first 20
            red = redact(s, patterns)
            print(f"  {p}:{ln}: {red}", file=sys.stderr)
        if len(real_findings) > 20:
            print(f"  ... and {len(real_findings) - 20} more", file=sys.stderr)
        
        print("| scan_secrets | FAIL | RESULT=FOUND |")
        print(f"[ERROR] Found {len(real_findings)} real secret(s)", file=sys.stderr)
        return 1  # Fail on real secrets
    
    # PRIORITY 2: Allowlisted findings (strict mode check)
    elif allowlisted_findings:
        if strict_mode:
            print("[WARN] Allowlisted findings detected (strict mode):", file=sys.stderr)
            for (p, ln, s) in allowlisted_findings[:10]:  # Limit output
                red = redact(s, patterns)
                print(f"  {p}:{ln}: {red}", file=sys.stderr)
            if len(allowlisted_findings) > 10:
                print(f"  ... and {len(allowlisted_findings) - 10} more", file=sys.stderr)
            
            print("| scan_secrets | FAIL | RESULT=ALLOWLISTED_STRICT |")
            print(f"[WARN] {len(allowlisted_findings)} allowlisted finding(s) (strict mode: exit 1)", file=sys.stderr)
            return 1  # Fail in strict mode
        else:
            print(f"[INFO] {len(allowlisted_findings)} allowlisted finding(s) (ignored)", file=sys.stderr)
            print("| scan_secrets | OK | RESULT=CLEAN |")
            return 0  # Success: all findings are allowlisted
    
    # PRIORITY 3: No findings at all
    else:
        print("| scan_secrets | OK | RESULT=CLEAN |")
        print("[OK] No secrets found", file=sys.stderr)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())


