#!/usr/bin/env python3
"""
Emit short PR summary from POST_SOAK_AUDIT_SUMMARY.json

Usage:
    python -m tools.soak.ci_gates.emit_pr_summary
    python -m tools.soak.ci_gates.emit_pr_summary path/to/POST_SOAK_AUDIT_SUMMARY.json
"""

import json
import pathlib
import sys


def main(p="artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json"):
    """Generate short markdown summary for PR comment."""
    j = json.loads(pathlib.Path(p).read_text())
    pass_ = j["readiness"]["pass"]
    k = j["snapshot_kpis"]
    verdict = "✅ READINESS: OK" if pass_ else "❌ READINESS: HOLD"
    
    lines = [
        "### Post-Soak Readiness (last-8 window)",
        "",
        f"{verdict}",
        "",
        f"- maker_taker_ratio: **{k.get('maker_taker_ratio'):.3f}** (≥ 0.83)",
        f"- net_bps: **{k.get('net_bps'):.3f}** (≥ 2.9)",
        f"- p95_latency_ms: **{k.get('p95_latency_ms'):.0f}** (≤ 330)",
        f"- risk_ratio: **{k.get('risk_ratio'):.3f}** (≤ 0.40)",
    ]
    
    fails = j["readiness"].get("failures") or []
    if fails:
        lines += ["", "**Failures:**"] + [f"- {f}" for f in fails]
    
    print("\n".join(lines))


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "artifacts/soak/latest/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json"
    main(p)

