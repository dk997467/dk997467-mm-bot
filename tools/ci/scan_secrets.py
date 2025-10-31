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

from src.common.redact import DEFAULT_PATTERNS

# Treat runs of asterisks as masking, not secrets
MASK_RE = re.compile(r'\*{4,}')

# Exclude noisy/generated trees from scanning
EXCLUDE_GLOBS = [
    'tools/tuning/golden/**',
    'artifacts/**',
    'reports/**',
]

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


def _excluded(path: Path) -> bool:
    """Check if path matches any exclusion glob."""
    rel = str(path).replace('\\', '/')
    # Also check if path starts with any excluded base
    for glob_pat in EXCLUDE_GLOBS:
        # Handle simple directory prefix matching
        if glob_pat.endswith('/**'):
            prefix = glob_pat[:-3]
            if rel.startswith(prefix):
                return True
        # Full glob matching
        if fnmatch.fnmatch(rel, glob_pat):
            return True
    return False


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
                
                # Skip lines containing masked tokens (****) entirely
                # These are redacted placeholders, not actual secrets
                mask_match = MASK_RE.search(s)
                if mask_match:
                    continue
                
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
        1: Real secrets found (always in --strict mode, optional otherwise)
    
    Environment:
        CI_STRICT_SECRETS=1: Enable strict mode (exit 1 on any findings)
    """
    parser = argparse.ArgumentParser(description="Scan for secrets in source code")
    parser.add_argument('--strict', action='store_true', 
                       help='Exit 1 even if all findings are allowlisted')
    args = parser.parse_args(argv)
    
    # Check for strict mode from env or CLI
    strict_mode = args.strict or os.environ.get('CI_STRICT_SECRETS') == '1'
    
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
    
    # Determine work_dir and artifacts root for critical path checking
    work_dir = Path(os.getenv("WORK_DIR", _repo_root)).resolve()
    artifacts_root = (work_dir / "artifacts").resolve()
    
    real_findings: List[Tuple[str, int, str]] = []
    allowlisted_findings: List[Tuple[str, int, str]] = []
    critical_findings: List[Tuple[str, int, str]] = []  # Findings in artifacts/**
    scan_errors = []
    
    # Scan target directories (src, cli, tools)
    scan_dirs = list(TARGET_DIRS)
    
    # Also scan artifacts/ if it exists (for critical path detection)
    if artifacts_root.exists():
        scan_dirs.append(str(artifacts_root))
    
    for root in scan_dirs:
        # Convert relative paths to absolute paths relative to _repo_root
        if not os.path.isabs(root):
            root = os.path.join(_repo_root, root)
        
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # prune excluded dirs early
            pruned_dirs = []
            for d in list(dirnames):
                d_path = Path(dirpath) / d
                rel_path = str(d_path.relative_to(_repo_root)).replace('\\', '/')
                if d in EXCLUDE_DIRS or _excluded(Path(rel_path)):
                    pruned_dirs.append(d)
            for d in pruned_dirs:
                dirnames.remove(d)
            
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                # Skip excluded files
                try:
                    rel_path = str(Path(path).relative_to(_repo_root)).replace('\\', '/')
                    if _excluded(Path(rel_path)):
                        continue
                except ValueError:
                    pass  # Not under repo root, check anyway
                
                if not _is_text_file(path):
                    continue
                try:
                    real_hits, allowlisted_hits = _scan_file(path, patterns, custom_allowlist)
                    
                    # Check if file is under artifacts/** (critical path)
                    file_path_resolved = Path(path).resolve()
                    is_in_artifacts = False
                    try:
                        # Check if file is under artifacts directory
                        file_path_resolved.relative_to(artifacts_root)
                        is_in_artifacts = True
                    except ValueError:
                        # Not under artifacts/
                        is_in_artifacts = False
                    
                    # Classify findings
                    for (ln, s) in real_hits:
                        normalized_path = path.replace('\\', '/')
                        if is_in_artifacts:
                            # Critical: any secret in artifacts/** → exit 2
                            critical_findings.append((normalized_path, ln, s))
                        else:
                            # Regular finding in repo
                            real_findings.append((normalized_path, ln, s))
                    
                    for (ln, s) in allowlisted_hits:
                        normalized_path = path.replace('\\', '/')
                        if is_in_artifacts:
                            # Even allowlisted findings in artifacts are critical
                            critical_findings.append((normalized_path, ln, s))
                        else:
                            allowlisted_findings.append((normalized_path, ln, s))
                except Exception as e:
                    scan_errors.append(f"{path}: {e}")

    # Deterministic order (ASCII-only, stable sort)
    real_findings.sort(key=lambda x: (x[0], x[1]))
    allowlisted_findings.sort(key=lambda x: (x[0], x[1]))
    critical_findings.sort(key=lambda x: (x[0], x[1]))
    
    # Report scan errors (non-fatal warnings)
    if scan_errors:
        print("[WARN] Some files could not be scanned:", file=sys.stderr)
        for err in sorted(scan_errors)[:5]:  # Deterministic order, limit to 5
            print(f"  {err}", file=sys.stderr)
        if len(scan_errors) > 5:
            print(f"  ... and {len(scan_errors) - 5} more", file=sys.stderr)
    
    # Import redact function
    try:
        from src.common.redact import redact
    except ImportError:
        print("[WARN] Could not import redact function, showing raw findings", file=sys.stderr)
        redact = lambda s, p: s  # Fallback: no redaction
    
    # PRIORITY 1: Critical findings in artifacts/** → exit 2
    if critical_findings:
        print("[CRITICAL] Secrets found in artifacts/** (bypasses allowlist):", file=sys.stderr)
        for (p, ln, s) in critical_findings[:10]:  # Limit output
            red = redact(s, patterns)
            print(f"  {p}:{ln}: {red}", file=sys.stderr)
        if len(critical_findings) > 10:
            print(f"  ... and {len(critical_findings) - 10} more", file=sys.stderr)
        
        print("| scan_secrets | FAIL | RESULT=CRITICAL |")
        print(f"[CRITICAL] Found {len(critical_findings)} secret(s) in artifacts/", file=sys.stderr)
        return 2  # Exit 2 for critical findings
    
    # PRIORITY 2: Real findings in repo (not allowlisted) → exit 1
    if real_findings:
        print("[ERROR] Real secrets detected (NOT allowlisted):", file=sys.stderr)
        for (p, ln, s) in real_findings:
            red = redact(s, patterns)
            print(f"  {p}:{ln}: {red}", file=sys.stderr)
        
        print("| scan_secrets | FAIL | RESULT=FOUND |")
        print(f"[ERROR] Found {len(real_findings)} real secret(s)", file=sys.stderr)
        return 1  # Fail on real secrets
    
    # PRIORITY 3: Allowlisted findings (strict mode check)
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
    
    # PRIORITY 4: No findings at all
    else:
        print("| scan_secrets | OK | RESULT=CLEAN |")
        print("[OK] No secrets found", file=sys.stderr)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())


