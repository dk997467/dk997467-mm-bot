import argparse
import json
import os
from typing import Dict, Any

from src.sim.ledger import VirtualLedger


def _read_jsonl(path: str):
    out = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _write_json_atomic(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--trades', required=True)
    ap.add_argument('--prices', required=True)
    args = ap.parse_args(argv)

    trades = _read_jsonl(args.trades)
    prices = _read_jsonl(args.prices)

    led = VirtualLedger()
    # process trades by ts order
    for t in sorted(trades, key=lambda x: x.get('ts')):
        led.on_fill(t['ts'], t['symbol'], t['side'], t['price'], t['qty'], t.get('fee_bps', 0.0), t.get('maker_rebate_bps', 0.0))
        # m2m if price snapshot available for that ts
        # choose closest price at or before ts
        def last_price(ts: str) -> Dict[str, float]:
            mp: Dict[str, float] = {}
            # naive: take all price points with ts<=t['ts'] then last per symbol
            for p in sorted([p for p in prices if p['ts'] <= ts], key=lambda x: (x['symbol'], x['ts'])):
                mp[p['symbol']] = float(p['mid'])
            return mp
        mp = last_price(t['ts'])
        if mp:
            led.mark_to_market(t['ts'], mp)
    # finalize last day
    if led._day:
        led.daily_close(led._day)

    _write_json_atomic('artifacts/LEDGER_DAILY.json', led.daily_reports)
    _write_json_atomic('artifacts/LEDGER_EQUITY.json', led.equity_series)
    print('WROTE artifacts/LEDGER_DAILY.json artifacts/LEDGER_EQUITY.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


