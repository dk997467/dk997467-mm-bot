"""
Backtest CLI.

Commands:
  python -m tools.backtest.cli run --ticks PATH --mode queue_aware --out PATH
  python -m tools.backtest.cli wf --ticks PATH --mode queue_aware --train N --test M --out PATH

Writes deterministic JSON via atomic writer; also emits MD next to report for run.
"""

import argparse
import os
from typing import Dict, Any

from src.common.artifacts import write_json_atomic
from src.common.version import utc_now_str, VERSION
from .loader import iter_ticks
from .simulator import run_sim
from .walkforward import run_walkforward


def _fmt6(x: float) -> str:
    return f"{float(x):.6f}"


def _write_md(path_json: str, agg: Dict[str, Any]) -> None:
    md_path = os.path.splitext(path_json)[0] + ".md"
    lines = []
    lines.append("| key | value |\n")
    lines.append("|---|---|\n")
    for k in ["fills_total", "net_bps", "taker_share_pct", "order_age_p95_ms", "fees_bps", "turnover_usd"]:
        v = agg[k]
        # форматируем все числовые значения как %.6f, включая целые
        try:
            v_str = _fmt6(float(v))
        except Exception:
            v_str = str(v)
        lines.append(f"| {k} | {v_str} |\n")
    with open(md_path, 'w', encoding='ascii', newline='\n') as f:
        f.writelines(lines)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass


def cmd_run(args: argparse.Namespace) -> int:
    try:
        ticks = list(iter_ticks(args.ticks))
        agg = run_sim(iter(ticks), args.mode, {})
        payload = {
            "fills_total": int(agg["fills_total"]),
            "fees_bps": float(f"{float(agg['fees_bps']):.6f}"),
            "net_bps": float(f"{float(agg['net_bps']):.6f}"),
            "order_age_p95_ms": float(f"{float(agg['order_age_p95_ms']):.6f}"),
            "taker_share_pct": float(f"{float(agg['taker_share_pct']):.6f}"),
            "turnover_usd": float(f"{float(agg['turnover_usd']):.6f}"),
            "runtime": {"utc": utc_now_str(), "version": VERSION, "mode": "backtest"},
        }
        write_json_atomic(args.out, payload)
        _write_md(args.out, payload)
        try:
            size = os.path.getsize(args.out)
            print(f"WROTE:{args.out}:{size}")
        except Exception:
            print("WROTE:unknown:0")
        return 0
    except Exception as e:
        print("ERROR:cli_run_failed")
        return 1


def cmd_wf(args: argparse.Namespace) -> int:
    try:
        payload = run_walkforward(args.ticks, args.mode, int(args.train), int(args.test), {})
        write_json_atomic(args.out, payload)
        try:
            size = os.path.getsize(args.out)
            print(f"WROTE:{args.out}:{size}")
        except Exception:
            print("WROTE:unknown:0")
        return 0
    except Exception:
        print("ERROR:cli_wf_failed")
        return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="backtest-cli")
    sub = p.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run")
    p_run.add_argument("--ticks", required=True)
    p_run.add_argument("--mode", required=True, choices=["conservative", "queue_aware"])
    p_run.add_argument("--out", required=True)
    p_run.set_defaults(func=cmd_run)

    p_wf = sub.add_parser("wf")
    p_wf.add_argument("--ticks", required=True)
    p_wf.add_argument("--mode", required=True, choices=["conservative", "queue_aware"])
    p_wf.add_argument("--train", required=True)
    p_wf.add_argument("--test", required=True)
    p_wf.add_argument("--out", required=True)
    p_wf.set_defaults(func=cmd_wf)

    # Дет-рантайм
    os.environ.setdefault("MM_FREEZE_UTC", "1")
    args = p.parse_args(argv)
    if not hasattr(args, "func"):
        p.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())


