import json
from typing import Any, Dict


def run_case(events_path: str) -> Dict[str, Any]:
    total = 0
    types: Dict[str, int] = {}
    reason = 'NONE'
    fail = False
    with open(events_path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            total += 1
            t = str(ev.get('type', ''))
            types[t] = types.get(t, 0) + 1
            if t == 'guard':
                r = str(ev.get('reason', '')).upper()
                if r.startswith('DRIFT'):
                    reason = 'DRIFT'
                    fail = True
                elif r.startswith('REG'):
                    if not fail:
                        reason = 'REG'
                        fail = True
    # Deterministic metrics
    metrics = {'events_total': total, 'types': {k: types[k] for k in sorted(types.keys())}}
    return {'fail': bool(fail), 'reason': reason, 'metrics': metrics}


