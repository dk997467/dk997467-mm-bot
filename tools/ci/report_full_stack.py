#!/usr/bin/env python3
import sys, json
from pathlib import Path

def _overall_status(data: dict) -> str:
    if isinstance(data.get("status"), str):
        return data["status"]
    if isinstance(data.get("result"), str):
        return data["result"]
    secs = data.get("sections") or []
    if isinstance(secs, list) and all((isinstance(s, dict) and s.get("status") == "OK") for s in secs):
        return "OK"
    return "FAIL"

def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print("usage: report_full_stack.py <FULL_STACK_VALIDATION.json>", file=sys.stderr)
        return 2
    jpath = Path(argv[0])
    data = json.loads(jpath.read_text(encoding="ascii"))

    mode = data.get("mode","FULL")
    status = _overall_status(data)
    runtime_utc = (data.get("runtime") or {}).get("utc", "1970-01-01T00:00:00Z")

    wanted = ["linters","tests_whitelist","dry_runs","reports","dashboards","secrets","audit_chain"]
    status_by = {s.get("name"): s.get("status","?") for s in (data.get("sections") or []) if isinstance(s, dict)}

    lines = []
    lines.append(f"# Full Stack Validation ({mode})")
    lines.append("")
    lines.append(f"**Result:** {status}")
    lines.append("")
    lines.append(f"*Runtime UTC:* {runtime_utc}")
    lines.append("")
    lines.append("## Sections")
    for name in wanted:
        lines.append(f"- {name}: {status_by.get(name,'?')}")
    lines.append("")
    md = "\n".join(lines) + "\n"

    out_md = jpath.parent / "FULL_STACK_VALIDATION.md"
    out_md.write_text(md, encoding="ascii", newline="")
    try:
        from src.common.eol import normalize_eol
        normalize_eol(out_md, style="crlf", ensure_trailing=3)
    except Exception:
        pass
    print(str(out_md))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

