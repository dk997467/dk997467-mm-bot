#!/usr/bin/env python3
import sys, json
from pathlib import Path


def main(argv=None):
    args = argv or sys.argv[1:]
    if not args:
        print("Usage: report_sim.py <SIM_REPORT.json>", file=sys.stderr)
        return 2
    src = Path(args[0])
    if not src.exists():
        print("ERROR: report not found", file=sys.stderr)
        return 2
    rep = json.loads(src.read_text(encoding="ascii"))
    md = []
    md.append("# SIM REPORT\n")
    md.append("| metric | value |\n")
    md.append("|---|---:|\n")
    md.append(f"| fills_total | {int(rep.get('fills_total',0))} |\n")
    md.append(f"| net_bps | {float(rep.get('net_bps',0.0)):.6f} |\n")
    md.append(f"| taker_share_pct | {float(rep.get('taker_share_pct',0.0)):.6f} |\n")
    md.append(f"| order_age_p95_ms | {float(rep.get('order_age_p95_ms',0.0)):.6f} |\n")
    md.append(f"| fees_bps | {float(rep.get('fees_bps',0.0)):.6f} |\n")
    md.append(f"| turnover_usd | {float(rep.get('turnover_usd',0.0)):.6f} |\n")
    Path("artifacts").mkdir(parents=True, exist_ok=True)
    out = Path("artifacts")/"REPORT_SIM.md"
    out.write_text("".join(md), encoding="ascii", newline="\n")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


