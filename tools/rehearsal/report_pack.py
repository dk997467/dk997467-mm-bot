import argparse
import json
import os


def _write_text_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(content)
        if not content.endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('pack_json')
    args = ap.parse_args(argv)

    with open(args.pack_json, 'r', encoding='ascii') as f:
        pack = json.load(f)

    lines = []
    lines.append('PRE-LIVE DRY RUN PACK\n')
    lines.append('\n')
    lines.append('Result: ' + str(pack.get('result', '')) + '\n')
    lines.append('\n')
    lines.append('| step | ok | details |\n')
    lines.append('|------|----|---------|\n')
    for s in pack.get('steps', []):
        lines.append('| ' + str(s.get('name','')) + ' | ' + ('OK' if s.get('ok') else 'FAIL') + ' | ' + str(s.get('details','')) + ' |\n')

    out_md = 'artifacts/PRE_LIVE_PACK.md'
    _write_text_atomic(out_md, ''.join(lines))
    print('PRE_LIVE_MD', out_md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


