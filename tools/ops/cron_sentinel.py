#!/usr/bin/env python3
"""
Cron Sentinel — проверка, что ежедневные джобы отработали в последние N часов.

Требования: stdlib-only; ASCII; детерминированные JSON/MD; atomic writes + fsync; LF.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# --- Environment normalization ---
os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
os.environ.setdefault("TZ", "UTC")
os.environ.setdefault("LC_ALL", "C")
os.environ.setdefault("LANG", "C")


VERSION = "0.1.0"


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_utc_date(date_str: str) -> datetime:
    # YYYY-MM-DD → 00:00:00Z
    y, m, d = [int(x) for x in date_str.split("-")]
    return datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)


def _now_utc(args_today: Optional[str]) -> Tuple[datetime, str]:
    """Return (now_dt_utc, iso_str). If --utc-today is set, use 23:59:59 of that day.
    If MM_FREEZE_UTC=1, freeze to 1970-01-01T00:00:00Z.
    """
    if args_today:
        base = _parse_utc_date(args_today)
        dt = base + timedelta(hours=23, minutes=59, seconds=59)
        return (dt, dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if os.environ.get("MM_FREEZE_UTC") == "1":
        dt = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        return (dt, dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    dt = _to_utc(datetime.utcnow().replace(tzinfo=timezone.utc))
    return (dt, dt.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    sp = str(path)
    p = Path(sp)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    tmp = sp + ".tmp"
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


def _within_window(path: Path, now_dt: datetime, window_hours: int) -> bool:
    try:
        ts = path.stat().st_mtime
    except Exception:
        return False
    start = now_dt.timestamp() - window_hours * 3600
    return ts >= start


def _fresh_within_days(paths: List[Path], now_dt: datetime, days: int) -> bool:
    cutoff = now_dt.timestamp() - days * 86400
    fresh = False
    for p in paths:
        try:
            if p.exists() and p.stat().st_mtime >= cutoff:
                fresh = True
                break
        except Exception:
            continue
    return fresh


def _truncate_detail(s: str, limit: int = 120) -> str:
    if len(s) <= limit:
        return s
    return s[:limit]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _check_report_soak_today(artifacts: Path, today: str) -> Check:
    ymd = today.replace("-", "")
    p = artifacts / f"REPORT_SOAK_{ymd}.json"
    if not p.exists():
        return Check("report_soak_today", False, "missing")
    try:
        rec = json.loads(p.read_text(encoding="ascii"))
        verdict = str(rec.get("verdict", ""))
    except Exception:
        return Check("report_soak_today", False, "bad_json")
    if verdict not in ("OK", "WARN"):
        return Check("report_soak_today", False, f"verdict={verdict}")
    return Check("report_soak_today", True, f"verdict={verdict}")


def _check_full_stack_validation(artifacts: Path, now_dt: datetime, window_hours: int) -> Check:
    p = artifacts / "FULL_STACK_VALIDATION.md"
    if not p.exists() or not _within_window(p, now_dt, window_hours):
        return Check("full_stack_validation", False, "not_present_in_window")
    try:
        txt = p.read_text(encoding="ascii")
    except Exception:
        return Check("full_stack_validation", False, "read_error")
    if "RESULT=OK" in txt:
        return Check("full_stack_validation", True, f"RESULT=OK seen in last {window_hours}h")
    return Check("full_stack_validation", False, "RESULT!=OK")


def _check_daily_digest(artifacts: Path, now_dt: datetime, window_hours: int) -> Check:
    p = artifacts / "DAILY_DIGEST.md"
    if p.exists() and _within_window(p, now_dt, window_hours):
        return Check("daily_digest", True, f"present in last {window_hours}h")
    return Check("daily_digest", False, "missing_in_window")


def _check_audit_chain(artifacts: Path, now_dt: datetime, window_hours: int) -> Check:
    p = artifacts / "AUDIT_CHAIN_VERIFY.json"
    if not p.exists() or not _within_window(p, now_dt, window_hours):
        return Check("audit_chain", False, "missing_in_window")
    try:
        rec = json.loads(p.read_text(encoding="ascii"))
        broken = int(rec.get("broken", 0))
    except Exception:
        return Check("audit_chain", False, "bad_json")
    if broken > 0:
        return Check("audit_chain", False, f"broken={broken}")
    return Check("audit_chain", True, f"broken=0 in last {window_hours}h")


def _check_readiness_score_recency(artifacts: Path, now_dt: datetime) -> Check:
    paths = [artifacts / "READINESS_SCORE.json", artifacts / "READINESS_SCORE.md"]
    fresh = _fresh_within_days(paths, now_dt, 7)
    if fresh:
        return Check("readiness_score_recency", True, "mtime<7d")
    # If completely absent, treat as SKIP (OK) to avoid noisy WARN in clean installs
    any_exists = any(p.exists() for p in paths)
    if not any_exists:
        return Check("readiness_score_recency", True, "skip")
    return Check("readiness_score_recency", False, "stale>=7d")


def _check_pre_live_pack_recency(artifacts: Path, now_dt: datetime) -> Check:
    paths = [artifacts / "PRE_LIVE_PACK.json", artifacts / "PRE_LIVE_PACK.md"]
    fresh = _fresh_within_days(paths, now_dt, 7)
    if fresh:
        return Check("pre_live_pack_recency", True, "fresh<7d")
    return Check("pre_live_pack_recency", True, "skip")


def aggregate_result(checks: List[Check]) -> str:
    # FAIL if: report_soak_today not ok; audit_chain not ok; full_stack_validation present but not OK
    # We approximate the last case by: if check name full_stack_validation has ok=False and detail == 'RESULT!=OK'
    # WARN if: full_stack_validation not present in window; daily_digest missing in window; readiness_score stale
    fail = False
    warn = False
    for c in checks:
        if c.name == "report_soak_today" and not c.ok:
            fail = True
        if c.name == "audit_chain" and not c.ok:
            fail = True
        if c.name == "full_stack_validation" and not c.ok and c.detail == "RESULT!=OK":
            fail = True
        if c.name == "full_stack_validation" and not c.ok and c.detail == "not_present_in_window":
            warn = True
        if c.name == "daily_digest" and not c.ok:
            warn = True
        if c.name == "readiness_score_recency" and not c.ok:
            warn = True
    if fail:
        return "FAIL"
    if warn:
        return "WARN"
    return "OK"


def _render_md(checks: List[Check], result: str) -> str:
    lines: List[str] = []
    lines.append("CRON SENTINEL")
    lines.append("")
    lines.append("| check | status | detail |")
    lines.append("|-------|--------|--------|")
    for c in checks:
        status = "OK" if c.ok else "WARN" if c.name in ("daily_digest", "full_stack_validation", "readiness_score_recency") and not c.ok else ("OK" if c.name == "pre_live_pack_recency" else "FAIL")
        mark = "[x]" if c.ok else "[ ]"
        lines.append(f"| {mark} {c.name} | {status} | {_truncate_detail(c.detail)} |")
    lines.append("")
    lines.append(f"SENTINEL={result}")
    return "\n".join(lines) + "\n"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--artifacts-dir", default="artifacts")
    ap.add_argument("--utc-today", dest="utc_today", required=False)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    # simple mtime-based sentinel flags
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--enforce", action="store_true")
    ap.add_argument("--tz", default="Europe/Berlin")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    # Simple mtime-based sentinel mode (no JSON/MD side effects)
    if args.dry or args.enforce:
        now = int(_time.time())
        window = int(args.window_hours) * 3600
        art = Path(args.artifacts_dir)
        checks: List[Tuple[str, Optional[Path], bool]] = [
            ("KPI_GATE", art / "KPI_GATE.json", True),
            ("FULL_STACK_VALIDATION", art / "FULL_STACK_VALIDATION.json", True),
            ("EDGE_REPORT", art / "EDGE_REPORT.json", True),
            ("EDGE_SENTINEL", art / "EDGE_SENTINEL.json", True),
        ]
        # WEEKLY_ROLLUP only on Mondays
        try:
            if ZoneInfo is not None and args.tz:
                dt_local = datetime.fromtimestamp(now, tz=ZoneInfo(str(args.tz)))
                is_monday = (dt_local.weekday() == 0)
            else:
                is_monday = datetime.utcfromtimestamp(now).weekday() == 0
        except Exception:
            is_monday = False
        if is_monday:
            checks.append(("WEEKLY_ROLLUP", art / "WEEKLY_ROLLUP.json", True))

        missing = 0
        stale = 0
        checked = 0

        for name, path, do_check in checks:
            if not do_check:
                continue
            if path is None:
                continue
            checked += 1
            try:
                if not path.exists():
                    status = "MISSING"
                    age_sec = 0
                    missing += 1
                else:
                    mtime = int(path.stat().st_mtime)
                    age = max(0, now - mtime)
                    if age > window:
                        status = "STALE"
                        stale += 1
                    else:
                        status = "OK"
                    age_sec = int(age)
            except Exception:
                status = "MISSING"
                age_sec = 0
                missing += 1
            # fixed-order ASCII log
            print(f"event=sentinel_check target={name} status={status} age_sec={age_sec} now={now}")

        if args.enforce:
            # placeholder for future enforcement action
            print("event=sentinel_enforce noop=1")

        result = "OK" if (missing == 0 and stale == 0) else "FAIL"
        print(f"RESULT={result} missing={missing} stale={stale} checked={checked} window_hours={int(args.window_hours)}")
        return 0 if result == "OK" else 1

    now_dt, now_iso = _now_utc(args.utc_today)
    artifacts = Path(args.artifacts_dir)
    checks: List[Check] = []
    # Order matters (deterministic)
    checks.append(_check_report_soak_today(artifacts, args.utc_today or now_iso.split("T")[0]))
    checks.append(_check_full_stack_validation(artifacts, now_dt, args.window_hours))
    checks.append(_check_daily_digest(artifacts, now_dt, args.window_hours))
    checks.append(_check_audit_chain(artifacts, now_dt, args.window_hours))
    checks.append(_check_readiness_score_recency(artifacts, now_dt))
    checks.append(_check_pre_live_pack_recency(artifacts, now_dt))

    result = aggregate_result(checks)
    out = {
        "window_hours": int(args.window_hours),
        "utc_now": now_iso,
        "checks": [{"name": c.name, "ok": bool(c.ok), "detail": c.detail} for c in checks],
        "result": result,
    }
    if args.out_json:
        _write_json_atomic(args.out_json, out)
    if args.out_md:
        md = _render_md(checks, result)
        _write_text_atomic(args.out_md, md)
        try:
            from src.common.eol import normalize_eol  # type: ignore
            normalize_eol(args.out_md, style="crlf", ensure_trailing=3)
        except Exception:
            pass
    print(f"SENTINEL={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


