#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from typing import Dict, Any

from tools.finops.exporter import load_artifacts, export_pnl_csv, export_fees_csv, export_turnover_csv, export_latency_csv, export_edge_csv
from src.common.version import utc_now_str


def _write(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Use CRLF to match golden files on Windows
    with open(p, 'w', encoding='ascii', newline='\r\n') as f:
        f.write(text)


def build_deck(art: Dict[str, Any]) -> str:
    # Extract key KPIs
    pnl = art.get('pnl', {}) or {}
    net = float(pnl.get('total_net_bps', 0.0))
    taker = float(pnl.get('total_taker_share_pct', 0.0))
    p95 = float(pnl.get('total_order_age_p95_ms', 0.0))
    fees_bps = float((art.get('fees', {}) or {}).get('effective_bps', 0.0))
    turnover_usd = float((art.get('turnover', {}) or {}).get('total_usd', 0.0))
    drawdown_proxy = float((art.get('intraday_caps', {}) or {}).get('drawdown_proxy_pct', 0.0))
    return (
        "# Investor Deck\n\n"
        "## Strategy\n"
        "Market making with micro-signals and HA failover.\n\n"
        "## Infrastructure\n"
        "Rust/Go/Python, Redis-like KV, Prometheus/Grafana, K8s.\n\n"
        "## Controls\n"
        "Caps/guards/HA leader lock with TTL.\n\n"
        "## Performance\n"
        f"net_bps={net:.6f}, taker_share_pct={taker:.6f}, p95_ms={p95:.6f}\n\n"
        "## Costs\n"
        f"fees_bps={fees_bps:.6f}, turnover_usd={turnover_usd:.6f}\n\n"
        "## Risk\n"
        f"drawdown_proxy_pct={drawdown_proxy:.6f}\n"
    )


def build_sop(art: Dict[str, Any]) -> str:
    return (
        "# SOP: Capital Operations\n\n"
        "## Onboarding\nAPI keys and transfers (high level).\n\n"
        "## Limits\nPer-symbol and total budget caps.\n\n"
        "## Reporting\nDaily CSV/JSON exports.\n\n"
        "## Safe Stop/Start\nSilence alerts, drain, switch leader, restart.\n\n"
        "## Contacts (RASCI)\nOwner/Approver/Support contacts.\n"
    )


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("Usage: python -m tools.finops.assemble_investor_pkg <artifacts_metrics_json>")
        return 2
    art_path = argv[0]
    art = load_artifacts(art_path)
    ts = utc_now_str().replace(':', '').replace('-', '')
    dist_dir = Path("dist") / "investor" / ts
    dist_dir.mkdir(parents=True, exist_ok=True)
    # Exports
    export_pnl_csv(art, str(dist_dir / "pnl.csv"))
    export_fees_csv(art, str(dist_dir / "fees.csv"))
    export_turnover_csv(art, str(dist_dir / "turnover.csv"))
    export_latency_csv(art, str(dist_dir / "latency.csv"))
    export_edge_csv(art, str(dist_dir / "edge.csv"))
    # Docs
    _write("docs/INVESTOR_DECK.md", build_deck(art))
    _write("docs/SOP_CAPITAL.md", build_sop(art))
    print(str(dist_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


