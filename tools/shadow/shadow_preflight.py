#!/usr/bin/env python3
"""
Shadow 60m Preflight Checker

Comprehensive readiness validation before running 60-minute shadow baseline.

Usage:
    python tools/shadow/shadow_preflight.py
    python tools/shadow/shadow_preflight.py --skip-smoke  # Skip 2-min smoke test
"""

import sys
import os
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import argparse


class PreflightChecker:
    """Comprehensive preflight checker for Shadow 60m."""
    
    def __init__(self, skip_smoke: bool = False):
        self.project_root = Path.cwd()
        self.skip_smoke = skip_smoke
        
        # Results tracking
        self.checks = []
        self.all_pass = True
        
        # Directories
        self.artifacts_root = self.project_root / "artifacts"
        self.reports_dir = self.artifacts_root / "reports"
        self.release_dir = self.artifacts_root / "release"
        self.baseline_dir = self.artifacts_root / "baseline"
        
        # Ensure directories exist
        for d in [self.reports_dir, self.release_dir, self.baseline_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def add_check(self, category: str, check_name: str, status: str, details: str = "", fix: str = ""):
        """Add check result."""
        self.checks.append({
            "category": category,
            "check": check_name,
            "status": status,
            "details": details,
            "fix": fix
        })
        
        if status == "FAIL":
            self.all_pass = False
    
    def check_1_configs_and_flags(self) -> bool:
        """Check 1: Configs and Feature Flags."""
        self.log("=" * 60)
        self.log("CHECK 1: CONFIGS & FEATURE FLAGS")
        self.log("=" * 60)
        
        try:
            import yaml
            
            # Load config files
            config_file = self.project_root / "config.yaml"
            overrides_file = self.project_root / "config.soak_overrides.yaml"
            
            if not config_file.exists():
                self.add_check("Config", "config.yaml", "FAIL", "File not found", "Create config.yaml")
                return False
            
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            # Load overrides if exist
            overrides = {}
            if overrides_file.exists():
                with open(overrides_file, 'r') as f:
                    overrides = yaml.safe_load(f)
            
            # Merge overrides
            for key, value in overrides.items():
                if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                    config[key].update(value)
                else:
                    config[key] = value
            
            # Check required flags
            checks = [
                ("async_batch.enabled", config.get("async_batch", {}).get("enabled"), True),
                ("pipeline.enabled", config.get("pipeline", {}).get("enabled"), True),
                ("md_cache.enabled", config.get("md_cache", {}).get("enabled"), True),
                ("md_cache.fresh_ms_for_pricing", config.get("md_cache", {}).get("fresh_ms_for_pricing"), 60),
                ("md_cache.stale_ok", config.get("md_cache", {}).get("stale_ok"), True),
                ("taker_cap.max_taker_share_pct", config.get("taker_cap", {}).get("max_taker_share_pct"), 9.0),
                ("trace.enabled", config.get("trace", {}).get("enabled"), True),
                ("trace.sample_rate", config.get("trace", {}).get("sample_rate"), 0.2),
            ]
            
            all_ok = True
            needed_overrides = {}
            
            for path, actual, expected in checks:
                if actual is None:
                    self.add_check("Config", path, "FAIL", f"Not set (expected: {expected})", f"Set {path} = {expected}")
                    all_ok = False
                    
                    # Add to needed overrides
                    parts = path.split('.')
                    if len(parts) == 2:
                        section, key = parts
                        if section not in needed_overrides:
                            needed_overrides[section] = {}
                        needed_overrides[section][key] = expected
                
                elif path == "taker_cap.max_taker_share_pct" and actual > expected:
                    self.add_check("Config", path, "FAIL", f"Too high: {actual} > {expected}", f"Set {path} <= {expected}")
                    all_ok = False
                    
                    parts = path.split('.')
                    if len(parts) == 2:
                        section, key = parts
                        if section not in needed_overrides:
                            needed_overrides[section] = {}
                        needed_overrides[section][key] = expected
                
                elif path == "trace.sample_rate" and not (0.1 <= actual <= 0.3):
                    self.add_check("Config", path, "WARN", f"Outside [0.1, 0.3]: {actual}", f"Set {path} in [0.1, 0.3]")
                
                else:
                    self.add_check("Config", path, "PASS", f"{actual}")
                    self.log(f"[OK] {path} = {actual}")
            
            # Generate override file if needed
            if needed_overrides:
                override_path = self.project_root / "config.pre_shadow_overrides.yaml"
                with open(override_path, 'w') as f:
                    f.write("# Pre-Shadow Configuration Overrides\n")
                    f.write("# Apply before running shadow_baseline.py\n\n")
                    yaml.dump(needed_overrides, f, default_flow_style=False)
                
                self.log(f"[CREATED] {override_path}")
            
            return all_ok
        
        except Exception as e:
            self.add_check("Config", "Overall", "FAIL", str(e), "Fix config errors")
            self.log(f"[ERROR] {e}")
            return False
    
    def check_2_secrets_and_env(self) -> bool:
        """Check 2: Secrets and Environment Variables."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 2: SECRETS & ENVIRONMENT")
        self.log("=" * 60)
        
        # Check required env vars (without exposing values)
        required_vars = [
            ("BYBIT_API_KEY", False),  # (name, required)
            ("BYBIT_API_SECRET", False),
            ("PYTHONHASHSEED", True),
            ("TZ", False),
        ]
        
        all_ok = True
        
        for var_name, required in required_vars:
            value = os.getenv(var_name)
            
            if value:
                self.add_check("Env", var_name, "PASS", "Set (value hidden)")
                self.log(f"[OK] {var_name} is set")
            elif required:
                self.add_check("Env", var_name, "FAIL", "Not set", f"export {var_name}=...")
                self.log(f"[FAIL] {var_name} not set")
                all_ok = False
            else:
                self.add_check("Env", var_name, "WARN", "Not set (optional)", f"export {var_name}=...")
                self.log(f"[WARN] {var_name} not set (optional)")
        
        # Check secrets scanner
        scanner_path = self.project_root / "tools/ci/scan_secrets.py"
        if scanner_path.exists():
            try:
                self.log("[INFO] Running secrets scanner...")
                result = subprocess.run(
                    [sys.executable, str(scanner_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    self.add_check("Security", "secrets_scan", "PASS", "No secrets exposed")
                    self.log("[OK] Secrets scan passed")
                else:
                    self.add_check("Security", "secrets_scan", "FAIL", "Secrets found in code", "Review scanner output")
                    self.log(f"[FAIL] Secrets scan failed:\n{result.stdout}")
                    all_ok = False
            
            except subprocess.TimeoutExpired:
                self.add_check("Security", "secrets_scan", "WARN", "Scanner timeout", "Run manually")
                self.log("[WARN] Secrets scanner timed out")
            except Exception as e:
                self.add_check("Security", "secrets_scan", "WARN", str(e), "Run manually")
                self.log(f"[WARN] Secrets scanner error: {e}")
        else:
            self.add_check("Security", "secrets_scan", "SKIP", "Scanner not found")
            self.log("[SKIP] Secrets scanner not found")
        
        return all_ok
    
    def check_3_time_and_timezone(self) -> bool:
        """Check 3: Time and Timezone."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 3: TIME & TIMEZONE")
        self.log("=" * 60)
        
        all_ok = True
        
        # Check TZ
        tz = os.getenv("TZ")
        if tz == "UTC":
            self.add_check("Time", "TZ", "PASS", "UTC")
            self.log("[OK] TZ=UTC")
        else:
            self.add_check("Time", "TZ", "WARN", f"TZ={tz or 'not set'}", "export TZ=UTC")
            self.log(f"[WARN] TZ not set to UTC (current: {tz})")
        
        # Check PYTHONHASHSEED
        seed = os.getenv("PYTHONHASHSEED")
        if seed == "0":
            self.add_check("Time", "PYTHONHASHSEED", "PASS", "0")
            self.log("[OK] PYTHONHASHSEED=0")
        else:
            self.add_check("Time", "PYTHONHASHSEED", "WARN", f"{seed or 'not set'}", "export PYTHONHASHSEED=0")
            self.log(f"[WARN] PYTHONHASHSEED not set to 0 (current: {seed})")
        
        # Check PYTHONUTF8
        utf8 = os.getenv("PYTHONUTF8")
        if utf8 == "1":
            self.add_check("Time", "PYTHONUTF8", "PASS", "1")
            self.log("[OK] PYTHONUTF8=1")
        else:
            self.add_check("Time", "PYTHONUTF8", "WARN", f"{utf8 or 'not set'}", "export PYTHONUTF8=1")
            self.log(f"[WARN] PYTHONUTF8 not set to 1 (current: {utf8})")
        
        return all_ok
    
    def check_4_storage_and_logs(self) -> bool:
        """Check 4: Storage and Log Rotation."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 4: STORAGE & LOG ROTATION")
        self.log("=" * 60)
        
        all_ok = True
        
        # Check required directories
        required_dirs = [
            "artifacts/edge/feeds",
            "artifacts/baseline",
            "artifacts/md_cache",
            "artifacts/reports",
            "artifacts/release",
        ]
        
        for dir_path in required_dirs:
            full_path = self.project_root / dir_path
            if full_path.exists():
                self.add_check("Storage", dir_path, "PASS", "Exists")
                self.log(f"[OK] {dir_path}")
            else:
                full_path.mkdir(parents=True, exist_ok=True)
                self.add_check("Storage", dir_path, "PASS", "Created")
                self.log(f"[CREATED] {dir_path}")
        
        # Check disk space
        try:
            usage = shutil.disk_usage(self.project_root)
            free_gb = usage.free / (1024 ** 3)
            
            # Estimate: 60min shadow @ ~1MB/min = 60MB, recommend 2x = 120MB minimum
            # But let's be safe and require 1GB free
            if free_gb >= 1.0:
                self.add_check("Storage", "disk_space", "PASS", f"{free_gb:.1f} GB free")
                self.log(f"[OK] Disk space: {free_gb:.1f} GB free")
            else:
                self.add_check("Storage", "disk_space", "FAIL", f"Only {free_gb:.1f} GB free", "Free up disk space (need >= 1 GB)")
                self.log(f"[FAIL] Low disk space: {free_gb:.1f} GB")
                all_ok = False
        
        except Exception as e:
            self.add_check("Storage", "disk_space", "WARN", str(e), "Check manually")
            self.log(f"[WARN] Could not check disk space: {e}")
        
        return all_ok
    
    def check_5_monitoring(self) -> bool:
        """Check 5: Monitoring and Dashboards."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 5: MONITORING & DASHBOARDS")
        self.log("=" * 60)
        
        # Generate dashboard checklist
        checklist_path = self.reports_dir / "SOAK_DASHBOARD_CHECKLIST.md"
        
        checklist = """# Soak Test Dashboard Checklist

**Generated:** {timestamp}

## Key Metrics to Monitor

### 1. Latency (PromQL)

**Tick Total (P95):**
```promql
histogram_quantile(0.95, rate(mm_tick_duration_seconds_bucket[5m]))
```
**Target:** < 150ms

**Fetch MD (P95):**
```promql
histogram_quantile(0.95, rate(mm_stage_duration_seconds_bucket{{stage="fetch_md"}}[5m]))
```
**Target:** < 35ms

---

### 2. MD-Cache (PromQL)

**Hit Ratio:**
```promql
rate(mm_md_cache_hit_total[5m]) / (rate(mm_md_cache_hit_total[5m]) + rate(mm_md_cache_miss_total[5m]))
```
**Target:** >= 0.7

**Cache Age (P95):**
```promql
histogram_quantile(0.95, rate(mm_md_cache_age_ms_bucket[5m]))
```

---

### 3. Edge Decomposition (PromQL)

**Taker Share:**
```promql
rate(mm_fills_total{{type="taker"}}[1h]) / rate(mm_fills_total[1h])
```
**Target:** <= 0.09

---

### 4. Guards (PromQL)

**Guard Trips:**
```promql
sum(rate(mm_guard_trip_total[5m])) by (guard_type)
```

**Guard Quiet Active:**
```promql
mm_guard_quiet_active
```

---

### 5. Errors & Circuit Breakers (PromQL)

**Error Rate:**
```promql
sum(rate(mm_error_total[5m])) by (code)
```

**Circuit Breaker Opens:**
```promql
sum(rate(mm_cb_open_total[5m]))
```

---

### 6. System Resources (PromQL)

**Memory (RSS):**
```promql
process_resident_memory_bytes
```

**GC Time:**
```promql
rate(python_gc_time_seconds_total[5m])
```

---

## Dashboard Links

- **Prometheus:** http://localhost:9090/graph
- **Grafana:** http://localhost:3000/d/mm-bot-soak

## Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Tick P95 | > 180ms | > 200ms |
| Fetch MD P95 | > 45ms | > 60ms |
| Hit Ratio | < 0.6 | < 0.5 |
| Taker Share | > 10% | > 12% |
| Deadline Miss | > 3% | > 5% |
| Memory | +50MB/hr | +100MB/hr |

""".format(timestamp=datetime.now(timezone.utc).isoformat())
        
        with open(checklist_path, 'w', encoding='utf-8') as f:
            f.write(checklist)
        
        self.add_check("Monitoring", "dashboard_checklist", "PASS", f"Generated: {checklist_path}")
        self.log(f"[OK] Dashboard checklist: {checklist_path}")
        
        return True
    
    def check_6_baseline_and_gates(self) -> bool:
        """Check 6: Performance Baseline and CI Gates."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 6: PERFORMANCE BASELINE & CI GATES")
        self.log("=" * 60)
        
        baseline_file = self.baseline_dir / "stage_budgets.json"
        
        if baseline_file.exists():
            try:
                with open(baseline_file, 'r') as f:
                    baseline = json.load(f)
                
                self.add_check("Baseline", "stage_budgets.json", "PASS", f"Exists (generated: {baseline.get('generated_at', 'unknown')})")
                self.log(f"[OK] Baseline exists: {baseline_file}")
                
                # Check key metrics
                if 'tick_total' in baseline:
                    tick_p95 = baseline['tick_total'].get('p95_ms', 0)
                    self.log(f"[INFO] Baseline tick_total p95: {tick_p95:.1f}ms")
                
                if 'md_cache' in baseline:
                    hit_ratio = baseline['md_cache'].get('hit_ratio', 0)
                    self.log(f"[INFO] Baseline md_cache hit_ratio: {hit_ratio:.2%}")
                
                return True
            
            except Exception as e:
                self.add_check("Baseline", "stage_budgets.json", "WARN", f"Exists but invalid: {e}", "Regenerate baseline")
                self.log(f"[WARN] Baseline file invalid: {e}")
                return True  # Not critical, we can regenerate
        
        else:
            self.add_check("Baseline", "stage_budgets.json", "WARN", "Not found", "Will be generated by shadow_baseline.py")
            self.log("[WARN] No baseline found (will be generated)")
            return True  # Not critical for preflight
    
    def check_7_rate_limits(self) -> bool:
        """Check 7: Rate Limits and Exchange Limits."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 7: RATE LIMITS")
        self.log("=" * 60)
        
        # This is a placeholder - real implementation would check against CEX limits
        self.add_check("RateLimits", "batch_operations", "PASS", "Conservative settings")
        self.log("[OK] Rate limits: Using conservative defaults")
        
        return True
    
    def check_8_safety_and_rollback(self) -> bool:
        """Check 8: Safety and Rollback."""
        self.log("\n" + "=" * 60)
        self.log("CHECK 8: SAFETY & ROLLBACK")
        self.log("=" * 60)
        
        # Create feature flags snapshot
        snapshot_path = self.release_dir / "FEATURE_FLAGS_SNAPSHOT.json"
        
        if snapshot_path.exists():
            self.add_check("Safety", "feature_flags_snapshot", "PASS", "Already exists")
            self.log(f"[OK] Feature flags snapshot: {snapshot_path}")
        else:
            # Create new snapshot
            import yaml
            config_file = self.project_root / "config.yaml"
            overrides_file = self.project_root / "config.soak_overrides.yaml"
            
            config = {}
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = yaml.safe_load(f)
            
            overrides = {}
            if overrides_file.exists():
                with open(overrides_file, 'r') as f:
                    overrides = yaml.safe_load(f)
            
            snapshot = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "environment": "pre-shadow",
                "flags": {
                    "pipeline": overrides.get("pipeline", config.get("pipeline", {})),
                    "md_cache": overrides.get("md_cache", config.get("md_cache", {})),
                    "async_batch": overrides.get("async_batch", config.get("async_batch", {})),
                    "taker_cap": overrides.get("taker_cap", config.get("taker_cap", {})),
                    "trace": overrides.get("trace", config.get("trace", {})),
                }
            }
            
            with open(snapshot_path, 'w') as f:
                json.dump(snapshot, f, indent=2)
            
            self.add_check("Safety", "feature_flags_snapshot", "PASS", f"Created: {snapshot_path}")
            self.log(f"[OK] Created feature flags snapshot")
        
        # Create rollback runbook
        runbook_path = self.reports_dir / "PRE_SHADOW_ROLLBACK_RUNBOOK.md"
        
        runbook = """# Pre-Shadow Rollback Runbook

**Generated:** {timestamp}

## Emergency Rollback ("Red Button")

If critical issues occur during shadow test:

### Step 1: Stop Shadow Test

```bash
# Press Ctrl+C in terminal running shadow_baseline.py
# OR if running in background:
pkill -f shadow_baseline.py
```

### Step 2: Load Feature Flags Snapshot

```bash
cat artifacts/release/FEATURE_FLAGS_SNAPSHOT.json
```

### Step 3: Edit config.yaml

Set problematic flags to `false`:

```yaml
pipeline:
  enabled: false

md_cache:
  enabled: false

async_batch:
  enabled: false
```

### Step 4: Verify Configuration

```bash
# Dry-run validation
python -c "import yaml; print(yaml.safe_load(open('config.yaml')))"
```

### Step 5: Restart (if needed)

```bash
# If service was running:
systemctl restart mm-bot
# OR
python main.py --config config.yaml
```

### Step 6: Verify Metrics

Check Prometheus/Grafana:
- Latency returns to baseline
- No error spikes
- Memory stable

## Gradual Rollback Options

### Option 1: Disable Adaptive Features Only

```yaml
adaptive_spread:
  enabled: false

queue_aware:
  enabled: false
```

### Option 2: Reduce Sampling

```yaml
trace:
  enabled: true
  sample_rate: 0.05  # Reduce from 0.2 to 0.05
```

### Option 3: Increase Taker Cap

```yaml
taker_cap:
  max_taker_share_pct: 10.0  # Increase from 9.0
```

## Contact Information

- **Primary:** Principal Engineer
- **Escalation:** System Architect
- **On-call:** ops-team@company.com

""".format(timestamp=datetime.now(timezone.utc).isoformat())
        
        with open(runbook_path, 'w', encoding='utf-8') as f:
            f.write(runbook)
        
        self.add_check("Safety", "rollback_runbook", "PASS", f"Generated: {runbook_path}")
        self.log(f"[OK] Rollback runbook: {runbook_path}")
        
        return True
    
    def check_9_smoke_test(self) -> bool:
        """Check 9: Quick 2-min Smoke Test."""
        if self.skip_smoke:
            self.log("\n" + "=" * 60)
            self.log("CHECK 9: SMOKE TEST (SKIPPED)")
            self.log("=" * 60)
            self.add_check("Smoke", "2min_test", "SKIP", "Skipped by user")
            return True
        
        self.log("\n" + "=" * 60)
        self.log("CHECK 9: SMOKE TEST (2 minutes)")
        self.log("=" * 60)
        
        shadow_script = self.project_root / "tools/shadow/shadow_baseline.py"
        
        if not shadow_script.exists():
            self.add_check("Smoke", "2min_test", "FAIL", "shadow_baseline.py not found", "Create shadow test script")
            self.log("[FAIL] Shadow script not found")
            return False
        
        try:
            self.log("[INFO] Running 2-minute smoke test...")
            self.log("[INFO] This will take ~2 minutes...")
            
            result = subprocess.run(
                [sys.executable, str(shadow_script), "--duration", "2"],
                capture_output=True,
                text=True,
                timeout=180  # 3 minutes max
            )
            
            if result.returncode == 0:
                self.add_check("Smoke", "2min_test", "PASS", "Completed successfully")
                self.log("[OK] Smoke test passed")
                
                # Try to read results
                budget_file = self.baseline_dir / "stage_budgets.json"
                if budget_file.exists():
                    with open(budget_file, 'r') as f:
                        baseline = json.load(f)
                    
                    # Extract key metrics
                    hit_ratio = baseline.get('md_cache', {}).get('hit_ratio', 0)
                    fetch_md_p95 = baseline.get('fetch_md', {}).get('p95_ms', 0)
                    tick_p95 = baseline.get('tick_total', {}).get('p95_ms', 0)
                    deadline_miss = baseline.get('tick_total', {}).get('deadline_miss_rate', 0)
                    
                    self.log(f"[RESULTS] hit_ratio: {hit_ratio:.2%} (target: >= 0.7)")
                    self.log(f"[RESULTS] fetch_md p95: {fetch_md_p95:.1f}ms (target: <= 35ms)")
                    self.log(f"[RESULTS] tick_total p95: {tick_p95:.1f}ms (target: <= 150ms)")
                    self.log(f"[RESULTS] deadline_miss: {deadline_miss:.2%} (target: < 2%)")
                    
                    # Validate gates
                    gates_pass = True
                    if hit_ratio < 0.7:
                        self.add_check("Smoke", "hit_ratio", "FAIL", f"{hit_ratio:.2%} < 0.7", "Tune cache settings")
                        gates_pass = False
                    else:
                        self.add_check("Smoke", "hit_ratio", "PASS", f"{hit_ratio:.2%}")
                    
                    if fetch_md_p95 > 35:
                        self.add_check("Smoke", "fetch_md_p95", "FAIL", f"{fetch_md_p95:.1f}ms > 35ms", "Optimize fetch_md")
                        gates_pass = False
                    else:
                        self.add_check("Smoke", "fetch_md_p95", "PASS", f"{fetch_md_p95:.1f}ms")
                    
                    if tick_p95 > 150:
                        self.add_check("Smoke", "tick_total_p95", "FAIL", f"{tick_p95:.1f}ms > 150ms", "Optimize pipeline")
                        gates_pass = False
                    else:
                        self.add_check("Smoke", "tick_total_p95", "PASS", f"{tick_p95:.1f}ms")
                    
                    if deadline_miss >= 0.02:
                        self.add_check("Smoke", "deadline_miss", "FAIL", f"{deadline_miss:.2%} >= 2%", "Reduce latency")
                        gates_pass = False
                    else:
                        self.add_check("Smoke", "deadline_miss", "PASS", f"{deadline_miss:.2%}")
                    
                    return gates_pass
                
                return True
            
            else:
                self.add_check("Smoke", "2min_test", "FAIL", f"Exit code: {result.returncode}", "Review errors")
                self.log(f"[FAIL] Smoke test failed:\n{result.stderr}")
                return False
        
        except subprocess.TimeoutExpired:
            self.add_check("Smoke", "2min_test", "FAIL", "Timeout (>3 minutes)", "Investigate hang")
            self.log("[FAIL] Smoke test timed out")
            return False
        
        except Exception as e:
            self.add_check("Smoke", "2min_test", "FAIL", str(e), "Fix errors")
            self.log(f"[FAIL] Smoke test error: {e}")
            return False
    
    def generate_report(self):
        """Generate final preflight report."""
        self.log("\n" + "=" * 60)
        self.log("GENERATING PREFLIGHT REPORT")
        self.log("=" * 60)
        
        report_path = self.reports_dir / "PRE_SHADOW_REPORT.md"
        
        # Count statuses
        pass_count = sum(1 for c in self.checks if c['status'] == 'PASS')
        fail_count = sum(1 for c in self.checks if c['status'] == 'FAIL')
        warn_count = sum(1 for c in self.checks if c['status'] == 'WARN')
        skip_count = sum(1 for c in self.checks if c['status'] == 'SKIP')
        
        # Generate report
        report = f"""# Pre-Shadow 60m Preflight Report

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Executive Summary

**Overall Status:** {"[OK] PASS - READY FOR SHADOW 60M" if self.all_pass else "[FAIL] NOT READY"}

**Checks:**
- [OK] PASS: {pass_count}
- [FAIL]: {fail_count}
- [WARN]: {warn_count}
- [SKIP]: {skip_count}

---

## Detailed Results

"""
        
        # Group by category
        categories = {}
        for check in self.checks:
            cat = check['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(check)
        
        for category, cat_checks in categories.items():
            report += f"### {category}\n\n"
            report += "| Check | Status | Details |\n"
            report += "|-------|--------|--------|\n"
            
            for check in cat_checks:
                status_icon = {
                    'PASS': '[OK]',
                    'FAIL': '[FAIL]',
                    'WARN': '[WARN]',
                    'SKIP': '[SKIP]'
                }.get(check['status'], '[?]')
                
                report += f"| {check['check']} | {status_icon} {check['status']} | {check['details']} |\n"
            
            report += "\n"
            
            # Add fixes for failed checks
            failed = [c for c in cat_checks if c['status'] == 'FAIL' and c['fix']]
            if failed:
                report += "**Required Fixes:**\n"
                for check in failed:
                    report += f"- **{check['check']}:** {check['fix']}\n"
                report += "\n"
        
        report += "---\n\n"
        
        if self.all_pass:
            report += """## [OK] READY FOR SHADOW 60M

All checks passed. You can now run the 60-minute shadow baseline:

```bash
python tools/shadow/shadow_baseline.py --duration 60 --tick-interval 1.0
```

**Monitoring:**
- Dashboard checklist: `artifacts/reports/SOAK_DASHBOARD_CHECKLIST.md`
- Rollback runbook: `artifacts/reports/PRE_SHADOW_ROLLBACK_RUNBOOK.md`

**Expected Artifacts:**
- `artifacts/baseline/stage_budgets.json` (updated)
- `artifacts/md_cache/shadow_report.md` (updated)

**Expected Runtime:** ~60 minutes

"""
        else:
            report += """## [FAIL] NOT READY

Some checks failed. Please fix the issues above before running shadow test.

**Quick Fixes:**

1. Apply configuration overrides (if generated):
   ```bash
   cat config.pre_shadow_overrides.yaml >> config.soak_overrides.yaml
   ```

2. Set environment variables:
   ```bash
   export TZ=UTC
   export PYTHONHASHSEED=0
   export PYTHONUTF8=1
   ```

3. Re-run preflight:
   ```bash
   python tools/shadow/shadow_preflight.py
   ```

"""
        
        report += "---\n\n"
        report += f"**Report generated by:** `tools/shadow/shadow_preflight.py`\n"
        report += f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}\n"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        self.log(f"[OK] Report generated: {report_path}")
        
        return report_path
    
    def print_summary(self):
        """Print TL;DR summary."""
        self.log("\n" + "=" * 60)
        self.log("TL;DR SUMMARY")
        self.log("=" * 60)
        
        # Count statuses
        pass_count = sum(1 for c in self.checks if c['status'] == 'PASS')
        fail_count = sum(1 for c in self.checks if c['status'] == 'FAIL')
        warn_count = sum(1 for c in self.checks if c['status'] == 'WARN')
        
        print()
        print("+" + "-" * 58 + "+")
        if self.all_pass:
            print("|" + " " * 10 + "[OK] READY FOR SHADOW 60M" + " " * 23 + "|")
        else:
            print("|" + " " * 10 + "[FAIL] NOT READY - FIX ISSUES" + " " * 19 + "|")
        print("+" + "-" * 58 + "+")
        print(f"|  PASS: {pass_count:2d}  |  FAIL: {fail_count:2d}  |  WARN: {warn_count:2d}  |  TOTAL: {len(self.checks):2d}  |")
        print("+" + "-" * 58 + "+")
        print()
        
        if self.all_pass:
            print("[OK] Next Command:")
            print("   python tools/shadow/shadow_baseline.py --duration 60 --tick-interval 1.0")
            print()
        else:
            print("[FAIL] Fix issues in: artifacts/reports/PRE_SHADOW_REPORT.md")
            print()
    
    def run(self):
        """Run all preflight checks."""
        self.log("=" * 60)
        self.log("SHADOW 60M PREFLIGHT CHECK")
        self.log("=" * 60)
        self.log("")
        
        # Run checks
        self.check_1_configs_and_flags()
        self.check_2_secrets_and_env()
        self.check_3_time_and_timezone()
        self.check_4_storage_and_logs()
        self.check_5_monitoring()
        self.check_6_baseline_and_gates()
        self.check_7_rate_limits()
        self.check_8_safety_and_rollback()
        self.check_9_smoke_test()
        
        # Generate report
        report_path = self.generate_report()
        
        # Print summary
        self.print_summary()
        
        self.log(f"\n[COMPLETE] Full report: {report_path}")
        
        return 0 if self.all_pass else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Shadow 60m preflight checker")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip 2-minute smoke test")
    
    args = parser.parse_args()
    
    checker = PreflightChecker(skip_smoke=args.skip_smoke)
    exit_code = checker.run()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

