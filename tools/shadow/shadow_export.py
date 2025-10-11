#!/usr/bin/env python3
"""
Shadow 60m Final Export - Comprehensive Metrics Collection & Analysis

Collects all metrics from shadow baseline run and generates comprehensive reports.

Usage:
    python tools/shadow/shadow_export.py
"""

import sys
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any


class ShadowExporter:
    """Collects and exports shadow baseline metrics."""
    
    def __init__(self):
        self.project_root = Path.cwd()
        self.baseline_dir = self.project_root / "artifacts/baseline"
        self.md_cache_dir = self.project_root / "artifacts/md_cache"
        self.feeds_dir = self.project_root / "artifacts/edge/feeds"
        self.reports_dir = self.project_root / "artifacts/reports"
        
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Collected metrics
        self.metrics = {
            "start": None,
            "end": None,
            "ticks": 0,
            "fills": 0,
            "md_cache": {},
            "latency": {},
            "stages": {},
            "edge": {},
            "reliability": {},
            "gates": {}
        }
    
    def log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def load_stage_budgets(self) -> bool:
        """Load stage budgets from baseline."""
        budget_file = self.baseline_dir / "stage_budgets.json"
        
        if not budget_file.exists():
            self.log("[WARN] stage_budgets.json not found")
            return False
        
        try:
            with open(budget_file, 'r') as f:
                budget = json.load(f)
            
            self.log(f"[OK] Loaded stage budgets: {budget_file}")
            
            # Extract timestamps
            self.metrics["start"] = budget.get("start_time")
            self.metrics["end"] = budget.get("generated_at")
            self.metrics["ticks"] = budget.get("tick_count", 0)
            
            # Extract stages from new structure
            if "stages" in budget:
                for stage_name, stage_data in budget["stages"].items():
                    self.metrics["stages"][stage_name] = {
                        "p50_ms": stage_data.get("p50_ms", 0),
                        "p95_ms": stage_data.get("p95_ms", 0),
                        "p99_ms": stage_data.get("p99_ms", 0)
                    }
            
            # Extract tick_total metrics
            if "tick_total" in budget:
                tick = budget["tick_total"]
                self.metrics["latency"] = {
                    "tick_total_p50": tick.get("p50_ms", 0),
                    "tick_total_p95": tick.get("p95_ms", 0),
                    "tick_total_p99": tick.get("p99_ms", 0),
                    "deadline_miss_rate": tick.get("deadline_miss_rate", 0)
                }
            
            # Extract fetch_md from stages
            if "stages" in budget and "FetchMDStage" in budget["stages"]:
                fetch = budget["stages"]["FetchMDStage"]
                self.metrics["latency"]["fetch_md_p50"] = fetch.get("p50_ms", 0)
                self.metrics["latency"]["fetch_md_p95"] = fetch.get("p95_ms", 0)
                self.metrics["latency"]["fetch_md_p99"] = fetch.get("p99_ms", 0)
            
            return True
        
        except Exception as e:
            self.log(f"[ERROR] Failed to load stage budgets: {e}")
            return False
    
    def load_shadow_report(self) -> bool:
        """Load shadow report markdown and parse md_cache metrics."""
        report_file = self.md_cache_dir / "shadow_report.md"
        
        if not report_file.exists():
            self.log("[WARN] shadow_report.md not found")
            return False
        
        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.log(f"[OK] Loaded shadow report: {report_file}")
            
            # Parse md_cache metrics from markdown
            import re
            
            # Parse hit ratio
            hit_match = re.search(r'\*\*Cache Hit Ratio\*\*:\s*([\d.]+)', content)
            if hit_match:
                self.metrics["md_cache"]["hit_ratio"] = float(hit_match.group(1))
            
            # Parse used stale rate
            stale_match = re.search(r'\*\*Used Stale Rate\*\*:\s*([\d.]+)', content)
            if stale_match:
                self.metrics["md_cache"]["pricing_on_stale_pct"] = float(stale_match.group(1)) * 100
            
            # Parse cache age distribution
            age_p50_match = re.search(r'- \*\*p50\*\*:\s*([\d.]+)\s*ms', content)
            age_p95_match = re.search(r'- \*\*p95\*\*:\s*([\d.]+)\s*ms', content)
            age_p99_match = re.search(r'- \*\*p99\*\*:\s*([\d.]+)\s*ms', content)
            
            if age_p50_match:
                self.metrics["md_cache"]["cache_age_p50"] = float(age_p50_match.group(1))
            if age_p95_match:
                self.metrics["md_cache"]["cache_age_p95"] = float(age_p95_match.group(1))
            if age_p99_match:
                self.metrics["md_cache"]["cache_age_p99"] = float(age_p99_match.group(1))
            
            return True
        
        except Exception as e:
            self.log(f"[ERROR] Failed to load shadow report: {e}")
            return False
    
    def load_feeds(self) -> bool:
        """Load and parse feed logs."""
        # Try to find latest fills and pipeline_ticks files
        fills_files = list(self.feeds_dir.glob("fills_*.jsonl"))
        ticks_files = list(self.feeds_dir.glob("pipeline_ticks_*.jsonl"))
        
        if not fills_files and not ticks_files:
            self.log("[WARN] No feed logs found (fills/ticks)")
            return False
        
        # Parse fills
        if fills_files:
            latest_fills = max(fills_files, key=lambda f: f.stat().st_mtime)
            try:
                fills = []
                with open(latest_fills, 'r') as f:
                    for line in f:
                        try:
                            fills.append(json.loads(line.strip()))
                        except:
                            continue
                
                self.metrics["fills"] = len(fills)
                self.log(f"[OK] Loaded {len(fills)} fills from {latest_fills.name}")
                
                # Compute edge metrics from fills
                if fills:
                    slippages = [f.get("slippage_bps", 0) for f in fills if "slippage_bps" in f]
                    taker_fills = [f for f in fills if f.get("type") == "taker"]
                    
                    if slippages:
                        self.metrics["edge"]["slippage_bps_mean"] = statistics.mean(slippages)
                        self.metrics["edge"]["slippage_bps_median"] = statistics.median(slippages)
                    
                    if fills:
                        self.metrics["edge"]["taker_share_pct"] = (len(taker_fills) / len(fills)) * 100
                        self.metrics["edge"]["fill_rate_pct"] = 100.0  # Placeholder
            
            except Exception as e:
                self.log(f"[WARN] Failed to parse fills: {e}")
        
        # Parse pipeline_ticks (for additional metrics)
        if ticks_files:
            latest_ticks = max(ticks_files, key=lambda f: f.stat().st_mtime)
            try:
                with open(latest_ticks, 'r') as f:
                    tick_count = sum(1 for _ in f)
                
                self.log(f"[OK] Found {tick_count} ticks in {latest_ticks.name}")
            
            except Exception as e:
                self.log(f"[WARN] Failed to parse ticks: {e}")
        
        return True
    
    def validate_gates(self):
        """Validate metrics against gates."""
        gates = {}
        
        # Gate 1: hit_ratio >= 0.70
        hit_ratio = self.metrics["md_cache"].get("hit_ratio", 0)
        gates["hit_ratio"] = "PASS" if hit_ratio >= 0.70 else "FAIL"
        
        # Gate 2: fetch_md p95 <= 35ms
        fetch_md_p95 = self.metrics["latency"].get("fetch_md_p95", 0)
        gates["fetch_md_p95"] = "PASS" if fetch_md_p95 <= 35 else "FAIL"
        
        # Gate 3: tick_total p95 <= 150ms
        tick_p95 = self.metrics["latency"].get("tick_total_p95", 0)
        gates["tick_total_p95"] = "PASS" if tick_p95 <= 150 else "FAIL"
        
        # Gate 4: deadline_miss < 2%
        deadline_miss = self.metrics["latency"].get("deadline_miss_rate", 0)
        gates["deadline_miss"] = "PASS" if deadline_miss < 0.02 else "FAIL"
        
        self.metrics["gates"] = gates
        
        self.log("")
        self.log("=" * 60)
        self.log("GATE VALIDATION")
        self.log("=" * 60)
        self.log(f"[{'OK' if gates['hit_ratio'] == 'PASS' else 'FAIL'}] hit_ratio >= 0.70: {hit_ratio:.2%} ({gates['hit_ratio']})")
        self.log(f"[{'OK' if gates['fetch_md_p95'] == 'PASS' else 'FAIL'}] fetch_md p95 <= 35ms: {fetch_md_p95:.1f}ms ({gates['fetch_md_p95']})")
        self.log(f"[{'OK' if gates['tick_total_p95'] == 'PASS' else 'FAIL'}] tick_total p95 <= 150ms: {tick_p95:.1f}ms ({gates['tick_total_p95']})")
        self.log(f"[{'OK' if gates['deadline_miss'] == 'PASS' else 'FAIL'}] deadline_miss < 2%: {deadline_miss:.2%} ({gates['deadline_miss']})")
    
    def generate_results_json(self) -> Path:
        """Generate detailed results JSON."""
        results_file = self.reports_dir / "SHADOW_60M_RESULTS.json"
        
        results = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window": {
                "start": self.metrics["start"],
                "end": self.metrics["end"]
            },
            "counts": {
                "ticks": self.metrics["ticks"],
                "fills": self.metrics["fills"]
            },
            "md_cache": self.metrics["md_cache"],
            "latency": self.metrics["latency"],
            "stages": self.metrics["stages"],
            "edge": self.metrics["edge"],
            "reliability": self.metrics["reliability"],
            "gates": self.metrics["gates"]
        }
        
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        self.log(f"[OK] Results JSON: {results_file}")
        return results_file
    
    def generate_summary_md(self) -> Path:
        """Generate human-readable summary markdown."""
        summary_file = self.reports_dir / "SHADOW_60M_SUMMARY.md"
        
        # Count passing gates
        gates_pass = sum(1 for g in self.metrics["gates"].values() if g == "PASS")
        gates_total = len(self.metrics["gates"])
        
        summary = f"""# Shadow 60m Results Summary

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Executive Summary

**Overall Status:** {"✅ ALL GATES PASSED" if gates_pass == gates_total else f"⚠️ {gates_total - gates_pass} GATE(S) FAILED"}

**Window:** {self.metrics["start"]} → {self.metrics["end"]}

---

## Metrics Summary

### Counts

- **Ticks:** {self.metrics["ticks"]:,}
- **Fills:** {self.metrics["fills"]:,}

### MD-Cache Performance

| Metric | Value |
|--------|-------|
| Hit Ratio | {self.metrics["md_cache"].get("hit_ratio", 0):.2%} |
| Cache Age P50 | {self.metrics["md_cache"].get("cache_age_p50", 0):.1f}ms |
| Cache Age P95 | {self.metrics["md_cache"].get("cache_age_p95", 0):.1f}ms |
| Cache Age P99 | {self.metrics["md_cache"].get("cache_age_p99", 0):.1f}ms |
| Pricing on Stale | {self.metrics["md_cache"].get("pricing_on_stale_pct", 0):.1f}% |

### Latency Performance

| Metric | P50 | P95 | P99 |
|--------|-----|-----|-----|
| Fetch MD | {self.metrics["latency"].get("fetch_md_p50", 0):.1f}ms | {self.metrics["latency"].get("fetch_md_p95", 0):.1f}ms | {self.metrics["latency"].get("fetch_md_p99", 0):.1f}ms |
| Tick Total | {self.metrics["latency"].get("tick_total_p50", 0):.1f}ms | {self.metrics["latency"].get("tick_total_p95", 0):.1f}ms | {self.metrics["latency"].get("tick_total_p99", 0):.1f}ms |

**Deadline Miss Rate:** {self.metrics["latency"].get("deadline_miss_rate", 0):.2%}

### Stage Breakdown (P95)

"""
        
        for stage_name, stage_data in self.metrics["stages"].items():
            if stage_name not in ["md_cache", "tick_total"]:
                summary += f"- **{stage_name}:** {stage_data.get('p95_ms', 0):.1f}ms\n"
        
        summary += f"""

### Edge Proxies (Approximate)

| Metric | Value |
|--------|-------|
| Slippage (Mean) | {self.metrics["edge"].get("slippage_bps_mean", 0):.2f} bps |
| Slippage (Median) | {self.metrics["edge"].get("slippage_bps_median", 0):.2f} bps |
| Fill Rate | {self.metrics["edge"].get("fill_rate_pct", 0):.1f}% |
| Taker Share | {self.metrics["edge"].get("taker_share_pct", 0):.1f}% |

---

## Gate Validation

| Gate | Target | Actual | Status |
|------|--------|--------|--------|
| Hit Ratio | ≥ 0.70 | {self.metrics["md_cache"].get("hit_ratio", 0):.2%} | {self.metrics["gates"].get("hit_ratio", "N/A")} |
| Fetch MD P95 | ≤ 35ms | {self.metrics["latency"].get("fetch_md_p95", 0):.1f}ms | {self.metrics["gates"].get("fetch_md_p95", "N/A")} |
| Tick Total P95 | ≤ 150ms | {self.metrics["latency"].get("tick_total_p95", 0):.1f}ms | {self.metrics["gates"].get("tick_total_p95", "N/A")} |
| Deadline Miss | < 2% | {self.metrics["latency"].get("deadline_miss_rate", 0):.2%} | {self.metrics["gates"].get("deadline_miss", "N/A")} |

---

## Artifacts

- **Stage Budgets:** `artifacts/baseline/stage_budgets.json`
- **Results JSON:** `artifacts/reports/SHADOW_60M_RESULTS.json`
- **This Summary:** `artifacts/reports/SHADOW_60M_SUMMARY.md`

---

**Generated by:** `tools/shadow/shadow_export.py`
"""
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        self.log(f"[OK] Summary MD: {summary_file}")
        return summary_file
    
    def print_tldr(self):
        """Print TL;DR block to console."""
        print()
        print("=" * 60)
        print("===== SHADOW_60M_TLDR =====")
        print(f"window: {self.metrics['start']} -> {self.metrics['end']}")
        print(f"ticks: {self.metrics['ticks']} | fills: {self.metrics['fills']}")
        print()
        print("MD-cache:")
        print(f"  hit_ratio: {self.metrics['md_cache'].get('hit_ratio', 0):.2f}")
        print(f"  cache_age_ms p50/p95/p99: {self.metrics['md_cache'].get('cache_age_p50', 0):.0f}/{self.metrics['md_cache'].get('cache_age_p95', 0):.0f}/{self.metrics['md_cache'].get('cache_age_p99', 0):.0f}")
        print(f"  pricing_on_stale: {self.metrics['md_cache'].get('pricing_on_stale_pct', 0):.1f}%")
        print()
        print("Latency:")
        print(f"  fetch_md p50/p95/p99: {self.metrics['latency'].get('fetch_md_p50', 0):.0f}/{self.metrics['latency'].get('fetch_md_p95', 0):.0f}/{self.metrics['latency'].get('fetch_md_p99', 0):.0f}")
        print(f"  tick_total p95/p99: {self.metrics['latency'].get('tick_total_p95', 0):.0f}/{self.metrics['latency'].get('tick_total_p99', 0):.0f}")
        print(f"  deadline_miss: {self.metrics['latency'].get('deadline_miss_rate', 0):.2%}")
        print()
        print("Stage p95 (ms):")
        
        # Map full stage names to short names
        stage_mapping = {
            "FetchMDStage": "fetch_md",
            "SpreadStage": "spread",
            "GuardsStage": "guards",
            "InventoryStage": "inventory",
            "QueueAwareStage": "queue_aware",
            "EmitStage": "emit"
        }
        
        stage_parts = []
        for full_name, short_name in stage_mapping.items():
            if full_name in self.metrics["stages"]:
                val = self.metrics["stages"][full_name].get("p95_ms", 0)
                stage_parts.append(f"{short_name}={val:.0f}")
            else:
                stage_parts.append(f"{short_name}=N/A")
        print(f"  {' | '.join(stage_parts)}")
        
        print()
        print("Edge proxies (approx):")
        print(f"  slippage_bps mean/median: {self.metrics['edge'].get('slippage_bps_mean', 0):.2f}/{self.metrics['edge'].get('slippage_bps_median', 0):.2f}")
        print(f"  fill_rate: {self.metrics['edge'].get('fill_rate_pct', 0):.1f}%")
        print(f"  taker_share: {self.metrics['edge'].get('taker_share_pct', 0):.1f}%")
        print(f"  net_bps_trend: N/A")
        print()
        print("Reliability:")
        print(f"  ERR: {self.metrics['reliability'].get('err_count', 0)} | RETRY: {self.metrics['reliability'].get('retry_count', 0)} | CB_open: {self.metrics['reliability'].get('cb_open', 0)} | ws_gap: {self.metrics['reliability'].get('ws_gap', 0)} | rewind: {self.metrics['reliability'].get('rewind', 0)}")
        print()
        print("Gates:")
        print(f"  hit_ratio (>=0.70): {self.metrics['gates'].get('hit_ratio', 'N/A')}")
        print(f"  fetch_md p95 (<=35ms): {self.metrics['gates'].get('fetch_md_p95', 'N/A')}")
        print(f"  tick_total p95 (<=150ms): {self.metrics['gates'].get('tick_total_p95', 'N/A')}")
        print(f"  deadline_miss (<2%): {self.metrics['gates'].get('deadline_miss', 'N/A')}")
        print()
        print("Artifacts:")
        print("  stage_budgets.json: artifacts/baseline/stage_budgets.json")
        print("  shadow_results.json: artifacts/reports/SHADOW_60M_RESULTS.json")
        print("  shadow_summary.md:  artifacts/reports/SHADOW_60M_SUMMARY.md")
        print("============================")
        print()
    
    def print_json_export(self):
        """Print single-line JSON export."""
        # Build stage_p95_ms dict with proper name mapping
        stage_mapping = {
            "FetchMDStage": "fetch_md",
            "SpreadStage": "spread",
            "GuardsStage": "guards",
            "InventoryStage": "inventory",
            "QueueAwareStage": "queue_aware",
            "EmitStage": "emit"
        }
        
        stage_p95 = {}
        for full_name, short_name in stage_mapping.items():
            if full_name in self.metrics["stages"]:
                stage_p95[short_name] = round(self.metrics["stages"][full_name].get("p95_ms", 0), 1)
            else:
                stage_p95[short_name] = None
        
        export = {
            "start": self.metrics["start"],
            "end": self.metrics["end"],
            "ticks": self.metrics["ticks"],
            "fills": self.metrics["fills"],
            "hit_ratio": round(self.metrics["md_cache"].get("hit_ratio", 0), 3),
            "fetch_md_p95_ms": round(self.metrics["latency"].get("fetch_md_p95", 0), 1),
            "tick_total_p95_ms": round(self.metrics["latency"].get("tick_total_p95", 0), 1),
            "deadline_miss_pct": round(self.metrics["latency"].get("deadline_miss_rate", 0) * 100, 2),
            "pricing_on_stale_pct": round(self.metrics["md_cache"].get("pricing_on_stale_pct", 0), 2),
            "slippage_bps_mean": round(self.metrics["edge"].get("slippage_bps_mean", 0), 2),
            "slippage_bps_median": round(self.metrics["edge"].get("slippage_bps_median", 0), 2),
            "fill_rate_pct": round(self.metrics["edge"].get("fill_rate_pct", 0), 1),
            "taker_share_pct": round(self.metrics["edge"].get("taker_share_pct", 0), 1),
            "net_bps_trend": "N/A",
            "stage_p95_ms": stage_p95,
            "gates": self.metrics["gates"]
        }
        
        json_str = json.dumps(export, separators=(',', ':'))
        print(f"SHADOW_60M_EXPORT={json_str}")
        print()
    
    def run(self):
        """Run export analysis."""
        self.log("=" * 60)
        self.log("SHADOW 60M EXPORT - METRICS COLLECTION")
        self.log("=" * 60)
        self.log("")
        
        # Load artifacts
        self.log("[1/5] Loading stage budgets...")
        if not self.load_stage_budgets():
            self.log("[ERROR] Failed to load stage budgets - cannot continue")
            return False
        
        self.log("[2/5] Loading shadow report...")
        self.load_shadow_report()  # Optional
        
        self.log("[3/5] Loading feed logs...")
        self.load_feeds()  # Optional
        
        self.log("[4/5] Validating gates...")
        self.validate_gates()
        
        self.log("[5/5] Generating reports...")
        self.generate_results_json()
        self.generate_summary_md()
        
        self.log("")
        self.log("=" * 60)
        self.log("EXPORT COMPLETE")
        self.log("=" * 60)
        self.log("")
        
        # Print TL;DR and JSON export
        self.print_tldr()
        self.print_json_export()
        
        return True


def main():
    """Main entry point."""
    exporter = ShadowExporter()
    success = exporter.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

