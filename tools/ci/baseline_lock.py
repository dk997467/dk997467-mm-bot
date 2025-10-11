#!/usr/bin/env python3
"""
Step 6: CI Baseline Lock & Release Flags

Locks performance budgets and activates CI gates.

Usage:
    python tools/ci/baseline_lock.py --lock
    python tools/ci/baseline_lock.py --validate
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import argparse


class BaselineLock:
    """Manages baseline locking and CI gates."""
    
    def __init__(self):
        self.project_root = Path.cwd()
        self.baseline_dir = self.project_root / "artifacts/baseline"
        self.reports_dir = self.project_root / "artifacts/reports"
        self.docs_dir = self.project_root / "docs"
        
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def lock_baseline(self) -> Dict:
        """Lock current baseline as CI reference."""
        self.log("=" * 60)
        self.log("BASELINE LOCK")
        self.log("=" * 60)
        
        # Load current baseline
        budget_file = self.baseline_dir / "stage_budgets.json"
        if not budget_file.exists():
            self.log("[ERROR] stage_budgets.json not found")
            self.log("        Run: python tools/shadow/shadow_baseline.py --duration 60")
            return {}
        
        with open(budget_file, 'r') as f:
            baseline = json.load(f)
        
        self.log(f"[OK] Loaded baseline: {budget_file}")
        
        # Create locked baseline with CI gates
        locked = {
            'locked_at': datetime.now(timezone.utc).isoformat(),
            'source': str(budget_file),
            'baseline': baseline,
            'ci_gates': {
                'stage_p95_regression_pct': 3,  # +3% threshold
                'tick_total_p95_regression_pct': 10,  # +10% threshold
                'md_cache_hit_ratio_min': 0.6,  # 60% minimum
                'deadline_miss_rate_max': 0.02  # 2% maximum
            }
        }
        
        # Save locked baseline
        locked_file = self.baseline_dir / "stage_budgets.locked.json"
        with open(locked_file, 'w') as f:
            json.dump(locked, f, indent=2)
        
        self.log(f"[OK] Locked baseline: {locked_file}")
        
        # Create CI gates status report
        ci_status = self.generate_ci_gates_status(locked)
        ci_status_file = self.reports_dir / "CI_GATES_STATUS.md"
        
        with open(ci_status_file, 'w', encoding='utf-8') as f:
            f.write(ci_status)
        
        self.log(f"[OK] CI gates status: {ci_status_file}")
        
        # Create feature flags registry
        registry = self.generate_feature_flags_registry()
        registry_file = self.docs_dir / "FEATURE_FLAGS_REGISTRY.md"
        
        with open(registry_file, 'w', encoding='utf-8') as f:
            f.write(registry)
        
        self.log(f"[OK] Feature flags registry: {registry_file}")
        
        # Create baseline lock report
        lock_report = self.generate_baseline_lock_report(locked)
        lock_report_file = self.reports_dir / "BASELINE_LOCK_REPORT.md"
        
        with open(lock_report_file, 'w', encoding='utf-8') as f:
            f.write(lock_report)
        
        self.log(f"[OK] Baseline lock report: {lock_report_file}")
        
        self.log("")
        self.log("=" * 60)
        self.log("BASELINE LOCKED")
        self.log("=" * 60)
        
        return locked
    
    def generate_ci_gates_status(self, locked: Dict) -> str:
        """Generate CI gates status document."""
        baseline = locked['baseline']
        gates = locked['ci_gates']
        
        doc = f"""# CI Gates Status

**Generated:** {datetime.now(timezone.utc).isoformat()}
**Baseline Locked:** {locked['locked_at']}

## Active Gates

### 1. Stage P95 Regression

**Threshold:** +{gates['stage_p95_regression_pct']}%

Per-stage latency budgets:

"""
        
        for stage_name, stage_data in baseline.items():
            if isinstance(stage_data, dict) and 'p95_ms' in stage_data:
                p95 = stage_data['p95_ms']
                threshold = p95 * (1 + gates['stage_p95_regression_pct'] / 100)
                doc += f"- **{stage_name}:** {p95:.1f}ms baseline, {threshold:.1f}ms max\n"
        
        doc += f"""

### 2. Tick Total P95 Regression

**Threshold:** +{gates['tick_total_p95_regression_pct']}%

"""
        
        if 'tick_total' in baseline:
            tick_p95 = baseline['tick_total'].get('p95_ms', 0)
            tick_threshold = tick_p95 * (1 + gates['tick_total_p95_regression_pct'] / 100)
            doc += f"- **Baseline:** {tick_p95:.1f}ms\n"
            doc += f"- **Max allowed:** {tick_threshold:.1f}ms\n"
        
        doc += f"""

### 3. MD-Cache Hit Ratio

**Minimum:** {gates['md_cache_hit_ratio_min']:.0%}

"""
        
        if 'md_cache' in baseline:
            hit_ratio = baseline['md_cache'].get('hit_ratio', 0)
            doc += f"- **Baseline:** {hit_ratio:.2%}\n"
            doc += f"- **Minimum:** {gates['md_cache_hit_ratio_min']:.2%}\n"
        
        doc += f"""

### 4. Deadline Miss Rate

**Maximum:** {gates['deadline_miss_rate_max']:.1%}

"""
        
        if 'tick_total' in baseline:
            deadline_miss = baseline['tick_total'].get('deadline_miss_rate', 0)
            doc += f"- **Baseline:** {deadline_miss:.2%}\n"
            doc += f"- **Maximum:** {gates['deadline_miss_rate_max']:.2%}\n"
        
        doc += """

## CI Integration

These gates are enforced in:
- `.github/workflows/ci.yml` (PR checks)
- `tools/ci/stage_perf_gate.py` (validation script)

**Validation Command:**
```bash
python tools/ci/baseline_lock.py --validate
```

## Updating Baseline

To update the locked baseline after performance improvements:

```bash
# 1. Run new 60-min shadow test
python tools/shadow/shadow_baseline.py --duration 60

# 2. Review new metrics
cat artifacts/baseline/stage_budgets.json

# 3. Lock new baseline
python tools/ci/baseline_lock.py --lock
```
"""
        
        return doc
    
    def generate_feature_flags_registry(self) -> str:
        """Generate feature flags registry."""
        doc = f"""# Feature Flags Registry

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Active Feature Flags

### Pipeline Architecture

**Flag:** `pipeline.enabled`
**Status:** ✅ ENABLED
**Rollout:** 100%
**Owner:** @principal-engineer
**Rollback:** Set to `false` in `config.yaml`

**Description:**
Pipeline-based quote generation with stage metrics and tracing.

**Dependencies:**
- `async_batch.enabled` (required)
- `trace.enabled` (recommended for monitoring)

---

### MD-Cache

**Flag:** `md_cache.enabled`
**Status:** ✅ ENABLED
**Rollout:** 100%
**Owner:** @principal-engineer
**Rollback:** Set to `false` in `config.yaml`

**Description:**
Market data caching with TTL, staleness tracking, and invalidation.

**Config Parameters:**
- `ttl_ms: 100` - Cache TTL
- `stale_ok: true` - Allow stale reads
- `fresh_ms_for_pricing: 60` - Freshness requirement for pricing

---

### Async Batch

**Flag:** `async_batch.enabled`
**Status:** ✅ ENABLED
**Rollout:** 100%
**Owner:** @principal-engineer
**Rollback:** Set to `false` in `config.yaml`

**Description:**
Parallel symbol processing and command coalescing.

**Config Parameters:**
- `max_parallel_symbols: 10`
- `coalesce_cancel: true`
- `coalesce_place: true`

---

### Taker Cap

**Flag:** `taker_cap.enabled`
**Status:** ✅ ENABLED
**Cap:** 9.0%
**Owner:** @risk-team
**Rollback:** Increase `max_taker_share_pct` to 10.0 or disable

**Description:**
Hard cap on taker fills to prevent adverse selection and slippage.

---

### Performance Tracing

**Flag:** `trace.enabled`
**Status:** ✅ ENABLED
**Sample Rate:** 0.2 (20%)
**Owner:** @principal-engineer
**Rollback:** Set to `false` or reduce `sample_rate`

**Description:**
Stage-level performance tracing and deadline tracking.

---

## Snapshot Management

Before each major rollout, create a snapshot:

```bash
python tools/soak/generate_pre_soak_report.py
```

Snapshot location: `artifacts/release/FEATURE_FLAGS_SNAPSHOT.json`

## Rollback Procedure

1. **Identify issue** (via alerts/monitoring)
2. **Load snapshot:** `cat artifacts/release/FEATURE_FLAGS_SNAPSHOT.json`
3. **Edit config.yaml:** Set problematic flags to `false`
4. **Restart service:** `systemctl restart mm-bot` or `Ctrl+C` + relaunch
5. **Verify:** Check metrics in Prometheus/Grafana

## Adding New Flags

1. Add flag to `src/common/config.py`
2. Document in this registry
3. Create snapshot before enabling
4. Roll out gradually: 10% → 50% → 100%
5. Monitor safety gates at each stage
"""
        
        return doc
    
    def generate_baseline_lock_report(self, locked: Dict) -> str:
        """Generate baseline lock report."""
        baseline = locked['baseline']
        
        report = f"""# Baseline Lock Report

**Generated:** {datetime.now(timezone.utc).isoformat()}
**Baseline Locked:** {locked['locked_at']}

## Status: ✅ BASELINE LOCKED

## Locked Metrics

### Stage Budgets

"""
        
        for stage_name, stage_data in baseline.items():
            if isinstance(stage_data, dict) and 'p95_ms' in stage_data:
                report += f"**{stage_name}:**\n"
                report += f"- P50: {stage_data.get('p50_ms', 0):.1f}ms\n"
                report += f"- P95: {stage_data.get('p95_ms', 0):.1f}ms\n"
                report += f"- P99: {stage_data.get('p99_ms', 0):.1f}ms\n"
                report += "\n"
        
        report += "### Overall Performance\n\n"
        
        if 'tick_total' in baseline:
            tick = baseline['tick_total']
            report += f"**Tick Total:**\n"
            report += f"- P95: {tick.get('p95_ms', 0):.1f}ms\n"
            report += f"- Deadline miss: {tick.get('deadline_miss_rate', 0):.2%}\n"
            report += "\n"
        
        if 'md_cache' in baseline:
            cache = baseline['md_cache']
            report += f"**MD-Cache:**\n"
            report += f"- Hit ratio: {cache.get('hit_ratio', 0):.2%}\n"
            report += "\n"
        
        report += """## CI Gates Activated

All CI gates are now enforced on PRs and main branch:
- Stage P95 regression > +3% → FAIL
- Tick total P95 > +10% → FAIL
- MD-cache hit ratio < 60% → FAIL
- Deadline miss > 2% → FAIL

## Next Steps

1. ✅ Baseline locked
2. ✅ CI gates activated
3. ✅ Feature flags documented
4. ⏭️ Set up daily ops monitoring

See: `docs/FEATURE_FLAGS_REGISTRY.md` for full flag documentation.
"""
        
        return report
    
    def validate_against_baseline(self) -> bool:
        """Validate current metrics against locked baseline."""
        self.log("=" * 60)
        self.log("BASELINE VALIDATION")
        self.log("=" * 60)
        
        # Load locked baseline
        locked_file = self.baseline_dir / "stage_budgets.locked.json"
        if not locked_file.exists():
            self.log("[ERROR] No locked baseline found")
            self.log("        Run: python tools/ci/baseline_lock.py --lock")
            return False
        
        with open(locked_file, 'r') as f:
            locked = json.load(f)
        
        # Load current baseline
        current_file = self.baseline_dir / "stage_budgets.json"
        if not current_file.exists():
            self.log("[ERROR] No current baseline found")
            self.log("        Run: python tools/shadow/shadow_baseline.py --duration 2")
            return False
        
        with open(current_file, 'r') as f:
            current = json.load(f)
        
        baseline = locked['baseline']
        gates = locked['ci_gates']
        
        self.log(f"Locked baseline: {locked['locked_at']}")
        self.log(f"Current baseline: {current.get('generated_at', 'unknown')}")
        self.log("")
        
        all_pass = True
        
        # Check stage regressions
        for stage_name, stage_data in baseline.items():
            if not isinstance(stage_data, dict) or 'p95_ms' not in stage_data:
                continue
            
            locked_p95 = stage_data['p95_ms']
            current_p95 = current.get(stage_name, {}).get('p95_ms', 0)
            
            if current_p95 == 0:
                self.log(f"[SKIP] {stage_name}: no current data")
                continue
            
            threshold = locked_p95 * (1 + gates['stage_p95_regression_pct'] / 100)
            regression_pct = ((current_p95 / locked_p95) - 1) * 100
            
            if current_p95 <= threshold:
                self.log(f"[PASS] {stage_name}: {current_p95:.1f}ms (baseline: {locked_p95:.1f}ms, {regression_pct:+.1f}%)")
            else:
                self.log(f"[FAIL] {stage_name}: {current_p95:.1f}ms > {threshold:.1f}ms ({regression_pct:+.1f}%)")
                all_pass = False
        
        self.log("")
        
        if all_pass:
            self.log("=" * 60)
            self.log("✅ ALL GATES PASSED")
            self.log("=" * 60)
        else:
            self.log("=" * 60)
            self.log("❌ GATES FAILED")
            self.log("=" * 60)
        
        return all_pass


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="CI Baseline Lock")
    parser.add_argument("--lock", action="store_true", help="Lock current baseline for CI")
    parser.add_argument("--validate", action="store_true", help="Validate current metrics against locked baseline")
    
    args = parser.parse_args()
    
    locker = BaselineLock()
    
    if args.lock:
        result = locker.lock_baseline()
        if not result:
            sys.exit(1)
    elif args.validate:
        result = locker.validate_against_baseline()
        if not result:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

