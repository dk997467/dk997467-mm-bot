import os
import re
from pathlib import Path
from typing import List, Tuple


def _extract_md_links(content: str) -> List[str]:
    # Find [text](link) and [text]: link patterns
    links = []
    # Markdown links [text](url)
    for match in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', content):
        links.append(match.group(2))
    # Reference links [text]: url
    for match in re.finditer(r'^\[([^\]]+)\]:\s*(.+)$', content, re.MULTILINE):
        links.append(match.group(2).strip())
    return links


def _is_relative_file_link(link: str) -> bool:
    # Skip external URLs, anchors, etc.
    if link.startswith(('http://', 'https://', 'mailto:', '#')):
        return False
    # Skip query params and fragments for file check
    link = link.split('?')[0].split('#')[0]
    return bool(link.strip())


def _check_file(doc_path: Path) -> List[Tuple[str, str]]:
    """Returns list of (link, reason) for broken links"""
    try:
        content = doc_path.read_text(encoding='ascii')
    except Exception as e:
        return [('', f'Cannot read {doc_path}: {e}')]
    
    links = _extract_md_links(content)
    broken = []
    
    for link in links:
        if not _is_relative_file_link(link):
            continue
        
        # Resolve relative to doc location
        target = (doc_path.parent / link).resolve()
        if not target.exists():
            broken.append((link, f'File not found: {target}'))
    
    return broken


def main() -> int:
    docs_to_check = [
        'README.md',
        'docs/INDEX.md',
        'docs/RUNBOOKS.md', 
        'docs/GO_CHECKLIST.md',
        'REPORT_EDGE.md',
        'REPORT_RECONCILE.md',
    ]
    
    all_broken = []
    
    for doc in docs_to_check:
        path = Path(doc)
        if not path.exists():
            print(f'[SKIP] {doc} (not found)')
            continue
        
        broken = _check_file(path)
        if broken:
            print(f'[BROKEN] {doc}:')
            for link, reason in broken:
                print(f'  - {link}: {reason}')
            all_broken.extend(broken)
        else:
            print(f'[OK] {doc}')
    
    print()
    if all_broken:
        print(f'Found {len(all_broken)} broken links')
        return 1
    else:
        print('[OK] all links valid')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
