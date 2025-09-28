import glob
import json
import os
import shutil
from datetime import datetime, timezone


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


def _write_json_atomic(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _latest_soak() -> str:
    c = sorted(glob.glob('artifacts/REPORT_SOAK_*.json'))
    return c[-1] if c else ''


def main(argv=None) -> int:
    soak_path = _latest_soak()
    rep = _read_json(soak_path) or {}
    verdict = str(rep.get('verdict', 'OK'))
    drift_reason = ''
    try:
        d = _read_json('artifacts/DRIFT_STOP.json') or {}
        drift_reason = str(d.get('reason', ''))
    except Exception:
        drift_reason = ''
    reg_reason = ''
    try:
        rg = rep.get('reg_guard', {}) or {}
        reg_reason = str(rg.get('reason', ''))
        if not reg_reason:
            rr = _read_json('artifacts/REG_GUARD_STOP.json') or {}
            reg_reason = str(rr.get('reason', ''))
    except Exception:
        reg_reason = ''

    need_rollback = (verdict == 'FAIL') and (bool(drift_reason) or (reg_reason and reg_reason != 'NONE'))
    reason = 'DRIFT' if drift_reason else ('REG' if (reg_reason and reg_reason != 'NONE') else 'NONE')

    src = 'tools/tuning/overlay_profile.yaml'
    dst_prev = 'tools/tuning/overlay_prev.yaml'

    if need_rollback and os.path.exists(src) and os.path.exists(dst_prev):
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        bad = f'tools/tuning/overlay_bad_{ts}.yaml'
        try:
            shutil.copyfile(src, bad)
            shutil.copyfile(dst_prev, src)
            print('ROLLBACK from=overlay_profile.yaml to=overlay_prev.yaml reason=' + reason)
            out = {'reason': reason, 'from': 'overlay_profile.yaml', 'to': 'overlay_prev.yaml', 'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'}}
            _write_json_atomic('artifacts/AUTO_ROLLBACK.json', out)
            print('ROLLBACK=APPLIED')
        except Exception:
            print('ROLLBACK=SKIPPED')
    else:
        print('ROLLBACK=SKIPPED')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())


