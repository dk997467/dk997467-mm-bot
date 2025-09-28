from pathlib import Path
import sys

# Ensure repo root is importable when running `python -m tools.*` from arbitrary cwd
_repo_root = Path(__file__).resolve().parents[1]
_root_str = str(_repo_root)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

# No side effects beyond sys.path bootstrap.


