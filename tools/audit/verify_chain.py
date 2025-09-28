#!/usr/bin/env python3
"""
Verify audit jsonl hash-chain for a specific UTC date or the whole file.

Requirements per project META:
- stdlib-only
- ASCII-only deterministic outputs (ensure_ascii, sort_keys, separators=(",", ":"))
- trailing "\n"
- atomic writes with fsync

CLI:
  --audit artifacts/audit.jsonl
  --utc-date YYYY-MM-DD (optional)
  --out-json artifacts/AUDIT_CHAIN_VERIFY.json
  --out-md artifacts/AUDIT_CHAIN_VERIFY.md

Behavior:
- Iterate jsonl sequentially; maintain real chain across entire file
- If --utc-date provided, only count/assess lines whose ts starts with that date
- For counted lines, recompute sha256 over canonical JSON without 'sha256' and
  verify prev_sha256 matches the actual previous record's sha256
- Produce deterministic JSON/MD and print final status line:
    AUDIT_VERIFY=OK|BROKEN
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from src.audit.schema import validate_chain_line, compute_sha256_for
from src.common.artifacts import write_json_atomic


VERSION = "0.1.0"


def _now_utc_iso() -> str:
    freeze = os.environ.get("MM_FREEZE_UTC_ISO")
    if freeze:
        return str(freeze)
    # Avoid non-deterministic time; default to Unix epoch for tests if not frozen
    # but keep a valid ISO UTC shape.
    return "1970-01-01T00:00:00Z"


def _write_text_atomic(path: str, content: str) -> None:
    sp = str(path)
    p = Path(sp)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    tmp = sp + ".tmp"
    data = content if content.endswith("\n") else content + "\n"
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    try:
        os.replace(tmp, sp)
    except Exception:
        os.rename(tmp, sp)
    try:
        dfd = os.open(str(p.parent), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="verify_chain", add_help=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--utc-date", dest="utc_date", required=False)
    ap.add_argument("--out-json", dest="out_json", required=True)
    ap.add_argument("--out-md", dest="out_md", required=True)
    return ap.parse_args(argv)


def _should_count(rec: Dict[str, Any], date: Optional[str]) -> bool:
    if not date:
        return True
    ts = str(rec.get("ts", ""))
    return ts.startswith(str(date) + "T")


def verify(audit_path: str, utc_date: Optional[str]) -> Dict[str, Any]:
    checked = 0
    broken = 0
    first_broken_lineno: Optional[int] = None

    # Real chain tracking across whole file
    prev_sha: str = "GENESIS"

    try:
        with open(audit_path, "r", encoding="ascii", newline=None) as f:
            for idx, line in enumerate(f, start=1):
                if not line:
                    continue
                # Pre-parse to decide whether to count
                try:
                    rec = json.loads(line)
                except Exception:
                    # If selection applies and line would be counted (unknown), we cannot decide;
                    # be conservative: if no date filter, count as broken; otherwise, skip if ts missing.
                    if utc_date is None:
                        checked += 1
                        broken += 1
                        if first_broken_lineno is None:
                            first_broken_lineno = idx
                    # prev_sha remains unchanged to avoid compounding unknown state
                    continue

                count_it = _should_count(rec, utc_date)

                if count_it:
                    checked += 1
                    ok = validate_chain_line(prev_sha, line)
                    if not ok and os.environ.get("AUDIT_CHAIN_FLEX") == "1":
                        # Flexible fallback: recompute over canonized object sans sha256
                        try:
                            no_hash = {k: rec[k] for k in rec if k != 'sha256'}
                            calc = compute_sha256_for(no_hash)
                            ok = (str(rec.get('sha256', '')) == calc) and (str(rec.get('prev_sha256','')) == str(prev_sha))
                        except Exception:
                            ok = False
                    if not ok:
                        broken += 1
                        if first_broken_lineno is None:
                            first_broken_lineno = idx

                # Move chain forward using actual record sha if available
                try:
                    prev_sha = str(rec.get("sha256", prev_sha))
                except Exception:
                    pass
    except FileNotFoundError:
        # Empty/missing file: nothing to check
        checked = 0
        broken = 0
        first_broken_lineno = None

    result: Dict[str, Any] = {
        "checked": int(checked),
        "broken": int(broken),
        "first_broken_lineno": (None if first_broken_lineno is None else int(first_broken_lineno)),
        "runtime": {"utc": _now_utc_iso(), "version": VERSION},
    }
    return result


def _format_md(result: Dict[str, Any], utc_date: Optional[str]) -> str:
    lines = []
    lines.append("AUDIT CHAIN VERIFY")
    lines.append("")
    status = "OK" if int(result.get("broken", 0)) == 0 else "BROKEN"
    scope = str(utc_date) if utc_date else "all"
    lines.append(f"Result: {status}  Scope: {scope}")
    lines.append("")
    lines.append(f"checked: {int(result.get('checked', 0))}")
    lines.append(f"broken: {int(result.get('broken', 0))}")
    fbl = result.get("first_broken_lineno")
    lines.append(f"first_broken_lineno: {('null' if fbl is None else int(fbl))}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    res = verify(args.audit, args.utc_date)
    write_json_atomic(args.out_json, res)
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(args.out_json, style="crlf", ensure_trailing=3)
    except Exception:
        pass
    md = _format_md(res, args.utc_date)
    _write_text_atomic(args.out_md, md)
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(args.out_md, style="crlf", ensure_trailing=3)
    except Exception:
        pass
    status = "OK" if res.get("broken", 0) == 0 else "BROKEN"
    print(f"AUDIT_VERIFY={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


