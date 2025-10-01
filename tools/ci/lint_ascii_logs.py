import os
import re
import sys
from typing import List, Tuple


# Safety limit: skip extremely long lines to prevent memory issues
MAX_LINE_LENGTH = 10_000  # 10KB per line


def is_text_file(path: str) -> bool:
    """Check if file should be linted (only .py files in src/ and tools/)."""
    return (path.endswith('.py') and (path.startswith('src') or path.startswith('tools')))


def check_file_for_non_ascii(path: str) -> List[Tuple[int, str]]:
    """
    Check file for non-ASCII content in print() statements.
    
    Uses streaming read (line-by-line) to avoid memory issues with large files.
    This is critical for soak tests where the script runs repeatedly for 24-72 hours.
    
    Args:
        path: Path to file to check
    
    Returns:
        List of (line_number, violation_message) tuples
    
    Memory usage: O(1) per file (processes one line at a time)
    """
    violations = []
    
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line_no, line in enumerate(f, start=1):
                # Safety: skip extremely long lines to prevent memory issues
                if len(line) > MAX_LINE_LENGTH:
                    violations.append((line_no, f'line too long ({len(line)} bytes, limit: {MAX_LINE_LENGTH})'))
                    continue
                
                # Only check lines that contain print() to reduce false positives
                if 'print(' not in line:
                    continue
                
                # Check for non-ASCII characters in print statements
                # Match print(...) patterns
                for match in re.finditer(r'print\s*\(([^\)]*)\)', line):
                    content = match.group(1)
                    try:
                        content.encode('ascii')
                    except UnicodeEncodeError as e:
                        # Extract the problematic character for better error reporting
                        start = max(0, e.start - 20)
                        end = min(len(content), e.end + 20)
                        snippet = content[start:end]
                        violations.append((line_no, f'non-ascii in print: {snippet!r}'))
                        break  # Only report first violation per line
    
    except FileNotFoundError:
        # File was deleted between os.walk and open
        pass
    except PermissionError:
        # No read permission
        pass
    except Exception as e:
        # Unexpected error, but don't fail the entire linting run
        violations.append((0, f'error reading file: {e.__class__.__name__}'))
    
    return violations


def main() -> int:
    """
    Main linter entry point.
    
    Walks through src/ and tools/ directories checking Python files
    for non-ASCII content in print() statements.
    
    Returns:
        0 if no violations found, 2 if violations found
    """
    all_violations = []
    files_checked = 0
    
    for root, _, files in os.walk('.'):
        # Skip excluded directories
        if any(seg in root for seg in ('/venv', '\\venv', '/dist', '\\dist', '/.git', '\\.git')):
            continue
        
        for fn in files:
            path = os.path.join(root, fn).lstrip('./')
            
            if not is_text_file(path):
                continue
            
            files_checked += 1
            
            # Check file using streaming read (memory-efficient)
            file_violations = check_file_for_non_ascii(path)
            
            # Collect violations with file path
            for line_no, msg in file_violations:
                all_violations.append((path, line_no, msg))
    
    # Report results
    if all_violations:
        for path, line_no, msg in all_violations:
            if line_no > 0:
                print(f'ASCII_LINT {path}:{line_no}: {msg}')
            else:
                print(f'ASCII_LINT {path}: {msg}')
        print(f'\nTotal: {len(all_violations)} violation(s) in {files_checked} file(s)')
        return 2
    
    print(f'ASCII_LINT OK (checked {files_checked} files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())


