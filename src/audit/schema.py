import hashlib
import json
from typing import Any, Dict

from src.common.redact import DEFAULT_PATTERNS, redact


def _redact_in_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k in sorted(obj.keys()):
            out[k] = _redact_in_obj(obj[k])
        return out
    if isinstance(obj, list):
        return [_redact_in_obj(x) for x in obj]
    if isinstance(obj, str):
        return redact(obj)  # Uses DEFAULT_PATTERNS by default
    return obj


def canonical_without_hash(ts: str, kind: str, symbol: str, fields: Dict[str, Any], prev_sha256: str) -> Dict[str, Any]:
    safe_fields = _redact_in_obj(fields or {})
    rec = {
        'fields': safe_fields,
        'kind': str(kind),
        'prev_sha256': str(prev_sha256),
        'symbol': str(symbol),
        'ts': str(ts),
    }
    return rec


def compute_sha256_for(rec_no_hash: Dict[str, Any]) -> str:
    payload = json.dumps(rec_no_hash, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(payload).hexdigest()


def build_record(ts: str, kind: str, symbol: str, fields: Dict[str, Any], prev_sha256: str) -> Dict[str, Any]:
    base = canonical_without_hash(ts, kind, symbol, fields, prev_sha256)
    sha = compute_sha256_for(base)
    out = dict(base)
    out['sha256'] = sha
    return out


def json_line(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n'


def validate_chain_line(prev_sha: str, line: str) -> bool:
    try:
        rec = json.loads(line)
    except Exception:
        return False
    if not isinstance(rec, dict):
        return False
    if str(rec.get('prev_sha256', '')) != str(prev_sha):
        return False
    # recompute
    no_hash = {k: rec[k] for k in rec if k != 'sha256'}
    calc = compute_sha256_for(no_hash)
    return str(rec.get('sha256', '')) == calc


