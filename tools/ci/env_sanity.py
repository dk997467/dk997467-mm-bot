#!/usr/bin/env python3
import os, sys

def main():
    ok = True
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 9):
        print(f"WARN: Python {major}.{minor} < 3.9 may be unsupported for tests")
    try:
        import tempfile, pathlib
        p = pathlib.Path(tempfile.gettempdir()) / "mm_bot_test_write.tmp"
        p.write_text("ok", encoding="ascii", newline="\n")
        p.unlink()
    except Exception as e:
        print(f"ERROR: temp write failed: {e}")
        ok = False
    if not (os.path.isdir(".git") or os.path.exists(".git/HEAD")):
        print("WARN: .git metadata not found; git_sha will be 'unknown'")
    print("OK" if ok else "BROKEN")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())


