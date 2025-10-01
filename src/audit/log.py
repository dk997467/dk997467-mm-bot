from . import writer as audit_writer
from src.common.redact import redact, DEFAULT_PATTERNS
from datetime import datetime, timezone
import os


def audit_event(kind, symbol, fields):
    # Normalize fields to dict with ASCII-safe primitives
    if not isinstance(fields, dict):
        fields = {"value": str(fields)}
    safe_fields = {}
    for k, v in fields.items():
        key = str(k)
        try:
            if isinstance(v, float):
                if v != v or v == float("inf") or v == float("-inf"):
                    v = 0.0
        except Exception:
            pass
        if isinstance(v, str):
            try:
                v = redact(v)  # Uses DEFAULT_PATTERNS by default
            except Exception:
                pass
        safe_fields[key] = v
    try:
        ts = os.environ.get('MM_FREEZE_UTC_ISO') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        # ts is set inside writer.build_record via caller's ts; append handles chain
        audit_writer.append_record('artifacts/audit.jsonl', ts, str(kind), str(symbol or '-'), safe_fields)
    except Exception:
        return


