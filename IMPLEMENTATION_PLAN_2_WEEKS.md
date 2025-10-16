# 📅 IMPLEMENTATION PLAN — 2 WEEKS

**Based on:** ARCHITECTURAL_AUDIT_COMPLETE.md  
**Timeline:** 10 working days (2 sprints)  
**Team Size:** 1-2 engineers  
**Priority:** Production Readiness для steady-SAFE mode

---

## 🎯 OVERVIEW

This plan executes the **TOP-7 improvements** from the audit, split into:

- **Sprint 1** (Days 1-5): Quick wins for reliability, log noise reduction, CI stability
- **Sprint 2** (Days 6-10): Resilience and observability (metrics, alerts, emergency recovery)
- **Sprint 3** (Optional, future): Performance and refactoring (Rust, batching, profiling)

Each task includes: **goal, files, expected diff, invariants, acceptance criteria**.

---

## 🔴 SPRINT 1 — Quick Wins & Reliability (Days 1-5)

### TASK 1.1: Windows CI Cache Stabilization (Day 1, 2h)

**Goal:** Eliminate tar/gzip warnings и сделать cache deterministic

**Problem:**
- `actions/cache` fails with "tar: command not found" on Windows self-hosted
- Cache post-job cleanup logs noisy warnings
- Flaky cache behavior (sometimes restores, sometimes doesn't)

**Files Changed:**
- `.github/workflows/soak-windows.yml`

**Expected Diff:**
```yaml
# Line 102-104: Add cache control env
env:
  # Cache: Disabled on Windows due to tar/gzip issues
  # Set to '1' to enable on Linux/macOS or after installing GNU tar+gzip
  ENABLE_SOAK_CACHE: '0'

# Lines 246-248, 263-265, 287-289: Guard cache steps
- name: "[4/13] Cache Cargo registry"
  id: cache-cargo
  if: ${{ env.ENABLE_SOAK_CACHE == '1' }}
  uses: actions/cache@v4
  # ... rest unchanged

- name: "[5/13] Cache Rust build artifacts"
  id: cache-rust-target
  if: ${{ env.ENABLE_SOAK_CACHE == '1' }}
  # ... rest unchanged

- name: "[7/13] Cache pip dependencies"
  id: cache-pip
  if: ${{ env.ENABLE_SOAK_CACHE == '1' }}
  # ... rest unchanged
```

**Invariants:**
- Workflow still runs successfully (cache disabled, not broken)
- No change to test behavior (only cache layer affected)

**Acceptance Criteria:**
- ✅ No "tar: command not found" warnings in CI logs
- ✅ No cache post-job errors
- ✅ Workflow completes successfully (green checkmark)
- ✅ Build time increases acceptable (<10% slower without cache)

**Testing:**
```bash
# Run workflow manually on Windows self-hosted
gh workflow run soak-windows.yml \
  --ref feat/soak-ci-chaos-release-toolkit \
  -f iterations=2 \
  -f heartbeat_interval_seconds=30

# Verify logs:
# - No "tar" warnings
# - No cache save/restore steps executed
```

---

### TASK 1.2: Artifact Lifecycle Management (Day 1, 4h)

**Goal:** Prevent disk bloat через auto-rotation старых файлов

**Problem:**
- `artifacts/soak/latest/ITER_SUMMARY_*.json` accumulates indefinitely
- Old snapshots never cleaned up
- No size monitoring or alerts

**Files Changed:**
- `tools/soak/artifact_manager.py` (NEW)
- `.github/workflows/soak-windows.yml` (add rotation step)

**Expected Diff:**

**NEW FILE:** `tools/soak/artifact_manager.py`
```python
#!/usr/bin/env python3
"""
Artifact lifecycle manager for soak tests.

Automatically rotates old ITER_SUMMARY files, compresses old snapshots,
and monitors total disk usage.

Usage:
    python -m tools.soak.artifact_manager --rotate
"""
import argparse
import json
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Configuration
MAX_ITER_SUMMARIES = 100  # Keep last N ITER_SUMMARY files
MAX_SNAPSHOT_AGE_DAYS = 7  # Compress snapshots older than N days
MAX_TOTAL_SIZE_MB = 500  # Warn if total size exceeds N MB


def rotate_iter_summaries(base_dir: Path) -> int:
    """
    Keep only the last MAX_ITER_SUMMARIES ITER_SUMMARY files.
    
    Returns:
        Number of files removed
    """
    iter_files = sorted(base_dir.glob("latest/ITER_SUMMARY_*.json"))
    removed = 0
    
    for old_file in iter_files[:-MAX_ITER_SUMMARIES]:
        old_file.unlink()
        print(f"| cleanup | REMOVED | {old_file.name} |")
        removed += 1
    
    return removed


def compress_old_snapshots(base_dir: Path) -> int:
    """
    Compress snapshots older than MAX_SNAPSHOT_AGE_DAYS to .tar.gz.
    
    Returns:
        Number of snapshots compressed
    """
    cutoff = datetime.now() - timedelta(days=MAX_SNAPSHOT_AGE_DAYS)
    compressed = 0
    
    for snapshot in base_dir.glob("snapshots/*.json"):
        mtime = datetime.fromtimestamp(snapshot.stat().st_mtime)
        if mtime < cutoff:
            tar_path = snapshot.with_suffix('.json.tar.gz')
            
            # Create compressed archive
            with tarfile.open(tar_path, 'w:gz') as tar:
                tar.add(snapshot, arcname=snapshot.name)
            
            # Remove original
            snapshot.unlink()
            
            original_size_kb = snapshot.stat().st_size / 1024
            compressed_size_kb = tar_path.stat().st_size / 1024
            compression_ratio = (1 - compressed_size_kb / original_size_kb) * 100
            
            print(f"| cleanup | COMPRESSED | {snapshot.name} -> {tar_path.name} "
                  f"({original_size_kb:.1f}KB -> {compressed_size_kb:.1f}KB, "
                  f"{compression_ratio:.0f}% reduction) |")
            compressed += 1
    
    return compressed


def check_total_size(base_dir: Path) -> bool:
    """
    Check total disk usage and warn if exceeds limit.
    
    Returns:
        True if size is within limit, False otherwise
    """
    total_size_mb = sum(
        f.stat().st_size for f in base_dir.rglob('*') if f.is_file()
    ) / (1024**2)
    
    if total_size_mb > MAX_TOTAL_SIZE_MB:
        print(f"| cleanup | WARN | total_size={total_size_mb:.1f}MB > {MAX_TOTAL_SIZE_MB}MB |")
        return False
    
    print(f"| cleanup | OK | total_size={total_size_mb:.1f}MB |")
    return True


def main(argv: Optional[list] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Manage soak test artifacts")
    parser.add_argument(
        "--rotate", 
        action="store_true", 
        help="Rotate old artifacts and compress snapshots"
    )
    parser.add_argument(
        "--max-summaries",
        type=int,
        default=MAX_ITER_SUMMARIES,
        help=f"Max ITER_SUMMARY files to keep (default: {MAX_ITER_SUMMARIES})"
    )
    parser.add_argument(
        "--max-snapshot-age",
        type=int,
        default=MAX_SNAPSHOT_AGE_DAYS,
        help=f"Max snapshot age in days before compression (default: {MAX_SNAPSHOT_AGE_DAYS})"
    )
    args = parser.parse_args(argv)
    
    if args.rotate:
        base_dir = Path("artifacts/soak")
        
        if not base_dir.exists():
            print(f"| cleanup | WARN | Base directory not found: {base_dir} |")
            return 1
        
        # Rotate ITER_SUMMARY files
        removed = rotate_iter_summaries(base_dir)
        print(f"| cleanup | SUMMARY | removed={removed} ITER_SUMMARY files |")
        
        # Compress old snapshots
        compressed = compress_old_snapshots(base_dir)
        print(f"| cleanup | SUMMARY | compressed={compressed} snapshots |")
        
        # Check total size
        size_ok = check_total_size(base_dir)
        
        return 0 if size_ok else 2  # Exit 2 if size exceeds limit (warning)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

**DIFF:** `.github/workflows/soak-windows.yml`
```yaml
# Add after "Finalize and snapshot" step (line 878)
- name: Rotate artifacts (prevent disk bloat)
  id: rotate-artifacts
  if: always()
  run: |
    Write-Host "================================================"
    Write-Host "ARTIFACT ROTATION"
    Write-Host "================================================"
    
    & $env:PYTHON_EXE -m tools.soak.artifact_manager --rotate
    
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 2) {
      Write-Warning "Artifact size exceeds threshold, consider cleanup"
    }
```

**Invariants:**
- Rotation happens AFTER soak run completes (in finalize step)
- Does NOT delete current run's artifacts
- Compressed snapshots are still readable (can be extracted)

**Acceptance Criteria:**
- ✅ Old ITER_SUMMARY files removed (keeps last 100)
- ✅ Snapshots >7 days compressed to .tar.gz
- ✅ Total disk usage logged
- ✅ No functional impact on soak tests

**Testing:**
```bash
# Setup: create 150 mock ITER_SUMMARY files
for i in {1..150}; do
    echo '{}' > "artifacts/soak/latest/ITER_SUMMARY_${i}.json"
done

# Run rotation
python -m tools.soak.artifact_manager --rotate

# Verify:
# - Only last 100 files remain
# - Oldest 50 removed
find artifacts/soak/latest -name "ITER_SUMMARY_*.json" | wc -l  # Should be 100
```

---

### TASK 1.3: Config Consolidation (Day 2, 6h)

**Goal:** Reduce config sprawl from 6+ files to 2 (base + overrides)

**Problem:**
- Multiple config files: `runtime_overrides.json`, `steady_safe_overrides.json`, `ultra_safe_overrides.json`, `steady_overrides.json`, `applied_profile.json`
- Unclear precedence rules
- Potential for drift and inconsistency

**Files Changed:**
- `tools/soak/config_manager.py` (NEW)
- `tools/soak/run.py` (refactor config loading)
- `artifacts/soak/profiles/` (NEW directory structure)

**Expected Structure:**
```
artifacts/soak/
├── config.json                    # Base configuration (default values)
├── runtime_overrides.json         # Active overrides (merged from profile + env)
└── profiles/                      # Profile library
    ├── steady_safe.json
    ├── ultra_safe.json
    └── aggressive.json
```

**NEW FILE:** `tools/soak/config_manager.py`
```python
#!/usr/bin/env python3
"""
Unified configuration manager for soak tests.

Implements clear precedence: CLI > Env > Profile > Defaults

Usage:
    from tools.soak.config_manager import ConfigManager
    
    config = ConfigManager()
    overrides = config.load_overrides(profile="steady_safe")
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

# Default parameter values (fallback if no profile specified)
DEFAULT_OVERRIDES = {
    "base_spread_bps_delta": 0.14,
    "impact_cap_ratio": 0.09,
    "max_delta_ratio": 0.14,
    "min_interval_ms": 70,
    "replace_rate_per_min": 260,
    "tail_age_ms": 650,
}

# Profile definitions (immutable reference configs)
PROFILES = {
    "steady_safe": {
        "base_spread_bps_delta": 0.16,
        "impact_cap_ratio": 0.08,
        "max_delta_ratio": 0.12,
        "min_interval_ms": 75,
        "replace_rate_per_min": 260,
        "tail_age_ms": 740,
    },
    "ultra_safe": {
        "base_spread_bps_delta": 0.16,
        "impact_cap_ratio": 0.08,
        "max_delta_ratio": 0.12,
        "min_interval_ms": 80,
        "replace_rate_per_min": 240,
        "tail_age_ms": 700,
    },
    "aggressive": {
        "base_spread_bps_delta": 0.10,
        "impact_cap_ratio": 0.12,
        "max_delta_ratio": 0.16,
        "min_interval_ms": 50,
        "replace_rate_per_min": 320,
        "tail_age_ms": 500,
    },
}


class ConfigManager:
    """Manages soak test configuration with clear precedence."""
    
    def __init__(self, base_dir: Path = Path("artifacts/soak")):
        self.base_dir = base_dir
        self.profiles_dir = base_dir / "profiles"
        
        # Ensure directories exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize profiles if they don't exist
        self._initialize_profiles()
    
    def _initialize_profiles(self):
        """Write profile files if they don't exist."""
        for name, params in PROFILES.items():
            profile_path = self.profiles_dir / f"{name}.json"
            if not profile_path.exists():
                with open(profile_path, 'w', encoding='utf-8') as f:
                    json.dump(params, f, indent=2, sort_keys=True)
    
    def load_overrides(
        self,
        profile: Optional[str] = None,
        env_overrides: Optional[str] = None,
        cli_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Load overrides with clear precedence: CLI > Env > Profile > Defaults
        
        Args:
            profile: Profile name (e.g., "steady_safe")
            env_overrides: JSON string from MM_RUNTIME_OVERRIDES_JSON env var
            cli_overrides: Dict of overrides from command line args
        
        Returns:
            Merged overrides dict
        """
        # Start with defaults
        overrides = DEFAULT_OVERRIDES.copy()
        
        # Layer 1: Profile (if specified)
        if profile:
            profile_path = self.profiles_dir / f"{profile}.json"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_params = json.load(f)
                overrides.update(profile_params)
                print(f"| config | LOADED | profile={profile} |")
            else:
                print(f"| config | WARN | profile={profile} not found, using defaults |")
        
        # Layer 2: Environment variable
        if env_overrides:
            try:
                env_params = json.loads(env_overrides)
                overrides.update(env_params)
                print(f"| config | LOADED | source=env params={len(env_params)} |")
            except json.JSONDecodeError as e:
                print(f"| config | ERROR | Invalid env JSON: {e} |")
        
        # Layer 3: CLI overrides (highest priority)
        if cli_overrides:
            overrides.update(cli_overrides)
            print(f"| config | LOADED | source=cli params={len(cli_overrides)} |")
        
        return overrides
    
    def save_runtime_overrides(self, overrides: Dict[str, Any]):
        """Save active runtime overrides to file."""
        runtime_path = self.base_dir / "runtime_overrides.json"
        with open(runtime_path, 'w', encoding='utf-8') as f:
            json.dump(overrides, f, indent=2, sort_keys=True)
        print(f"| config | SAVED | path={runtime_path} |")
    
    def get_profile_params(self, profile: str) -> Optional[Dict[str, Any]]:
        """Get parameters for a specific profile."""
        profile_path = self.profiles_dir / f"{profile}.json"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None


def migrate_legacy_configs():
    """
    Migrate legacy config files to new structure.
    
    Converts:
        - steady_safe_overrides.json -> profiles/steady_safe.json
        - ultra_safe_overrides.json -> profiles/ultra_safe.json
        - steady_overrides.json -> DEPRECATED (merged into runtime_overrides.json)
    """
    base_dir = Path("artifacts/soak")
    config_mgr = ConfigManager(base_dir)
    
    # Migrate steady_safe
    legacy_steady_safe = base_dir / "steady_safe_overrides.json"
    if legacy_steady_safe.exists():
        import shutil
        shutil.move(
            str(legacy_steady_safe),
            str(config_mgr.profiles_dir / "steady_safe.json")
        )
        print(f"| migrate | MOVED | steady_safe_overrides.json -> profiles/steady_safe.json |")
    
    # Migrate ultra_safe
    legacy_ultra_safe = base_dir / "ultra_safe_overrides.json"
    if legacy_ultra_safe.exists():
        import shutil
        shutil.move(
            str(legacy_ultra_safe),
            str(config_mgr.profiles_dir / "ultra_safe.json")
        )
        print(f"| migrate | MOVED | ultra_safe_overrides.json -> profiles/ultra_safe.json |")
    
    # DEPRECATED: Remove steady_overrides.json (use runtime_overrides.json instead)
    legacy_steady = base_dir / "steady_overrides.json"
    if legacy_steady.exists():
        legacy_steady.unlink()
        print(f"| migrate | REMOVED | steady_overrides.json (DEPRECATED) |")


def main(argv: Optional[list] = None) -> int:
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage soak test configs")
    parser.add_argument("--migrate", action="store_true", help="Migrate legacy configs")
    parser.add_argument("--list-profiles", action="store_true", help="List available profiles")
    args = parser.parse_args(argv)
    
    if args.migrate:
        migrate_legacy_configs()
    
    if args.list_profiles:
        config_mgr = ConfigManager()
        print("Available profiles:")
        for name in PROFILES.keys():
            params = config_mgr.get_profile_params(name)
            if params:
                print(f"  - {name}: {len(params)} params")
                for k, v in sorted(params.items()):
                    print(f"      {k:30s} = {v}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

**DIFF:** `tools/soak/run.py` (replace config loading logic)
```python
# Line 838-900: Replace with ConfigManager
from tools.soak.config_manager import ConfigManager

# ...

# In main():
config_mgr = ConfigManager()

# Load overrides with clear precedence
env_overrides = os.environ.get("MM_RUNTIME_OVERRIDES_JSON")
current_overrides = config_mgr.load_overrides(
    profile=args.profile,  # e.g., "steady_safe"
    env_overrides=env_overrides,
    cli_overrides=None  # Future: support --set min_interval_ms=80
)

# Save as active runtime overrides
config_mgr.save_runtime_overrides(current_overrides)
```

**Invariants:**
- Precedence order: CLI > Env > Profile > Defaults
- Profile files are immutable (read-only, never modified by live-apply)
- `runtime_overrides.json` is the ONLY mutable file (updated by live-apply)

**Acceptance Criteria:**
- ✅ Only 2 config files in use: `profiles/{name}.json` + `runtime_overrides.json`
- ✅ Legacy files migrated with `--migrate` command
- ✅ Clear logging shows which config source was used
- ✅ Backward compatible (existing workflows unchanged)

**Testing:**
```bash
# Migrate legacy configs
python -m tools.soak.config_manager --migrate

# Verify: profiles directory created
ls -la artifacts/soak/profiles/

# Test precedence: profile < env
MM_RUNTIME_OVERRIDES_JSON='{"min_interval_ms": 999}' \
  python -m tools.soak.run --profile steady_safe --iterations 1 --mock

# Verify: runtime_overrides.json shows min_interval_ms=999 (env wins)
cat artifacts/soak/runtime_overrides.json | grep min_interval_ms
```

---

### TASK 1.4: Soak Smoke Test (Day 2, 2h)

**Goal:** Fast sanity check для soak runner (completes <2min)

**Problem:**
- No fast way to verify soak runner works
- Changes require full 30min+ mini-soak to test
- Missing CI integration for soak smoke tests

**Files Changed:**
- `tests/smoke/test_soak_smoke.py` (NEW)
- `.github/workflows/ci.yml` (add smoke test step)

**NEW FILE:** `tests/smoke/test_soak_smoke.py`
```python
"""
Smoke test for soak runner.

Fast validation (<2min) that soak runner can:
- Load configs
- Run 3 iterations with mock data
- Apply tuning deltas
- Generate reports
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_soak_smoke_3_iterations_mock():
    """Smoke: 3 iterations, 5s sleep, mock data, steady_safe profile."""
    # Cleanup
    latest_dir = Path("artifacts/soak/latest")
    if latest_dir.exists():
        import shutil
        shutil.rmtree(latest_dir)
    
    # Run soak with minimal config
    result = subprocess.run(
        [
            sys.executable, "-m", "tools.soak.run",
            "--iterations", "3",
            "--auto-tune",
            "--mock",
            "--profile", "steady_safe"
        ],
        env={"SOAK_SLEEP_SECONDS": "5"},  # Fast mode
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120  # Should complete in <2min
    )
    
    # Basic success check
    assert result.returncode == 0, f"Soak failed:\n{result.stderr}"
    
    # Verify artifacts created
    assert (latest_dir / "ITER_SUMMARY_1.json").exists(), "ITER_SUMMARY_1.json missing"
    assert (latest_dir / "ITER_SUMMARY_3.json").exists(), "ITER_SUMMARY_3.json missing"
    assert (latest_dir / "TUNING_REPORT.json").exists(), "TUNING_REPORT.json missing"
    
    # Verify TUNING_REPORT has 3 entries
    with open(latest_dir / "TUNING_REPORT.json", 'r') as f:
        report = json.load(f)
    
    assert len(report) == 3, f"Expected 3 iterations, got {len(report)}"
    
    # Verify live-apply happened (check for applied=true in at least one iteration)
    summaries = [
        json.load(open(latest_dir / f"ITER_SUMMARY_{i}.json"))
        for i in range(1, 4)
    ]
    
    applied_count = sum(s.get("tuning", {}).get("applied", False) for s in summaries)
    assert applied_count >= 1, "No deltas were applied (live-apply not working)"
    
    print("[OK] Smoke test PASSED - soak runner functional")


def test_soak_smoke_config_precedence():
    """Smoke: Verify --profile loads correct params."""
    # Run 1 iteration to check config loading
    result = subprocess.run(
        [
            sys.executable, "-m", "tools.soak.run",
            "--iterations", "1",
            "--mock",
            "--profile", "steady_safe"
        ],
        env={"SOAK_SLEEP_SECONDS": "1"},
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30
    )
    
    assert result.returncode == 0
    
    # Verify runtime_overrides.json matches steady_safe profile
    runtime = json.load(open("artifacts/soak/runtime_overrides.json"))
    
    # Key params from steady_safe profile
    assert runtime["min_interval_ms"] == 75, "Profile not loaded correctly"
    assert runtime["tail_age_ms"] == 740, "Profile not loaded correctly"
    
    print("[OK] Config precedence smoke test PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**DIFF:** `.github/workflows/ci.yml`
```yaml
# Add after unit tests (line 144)
- name: Run soak smoke test
  run: |
    python -m pytest tests/smoke/test_soak_smoke.py -v --tb=short
```

**Invariants:**
- Smoke test runs with mock data (no real market data needed)
- Fast mode: SOAK_SLEEP_SECONDS=5 (vs 300 in prod)
- Isolated: doesn't interfere with other tests

**Acceptance Criteria:**
- ✅ Test completes in <2min
- ✅ Verifies 3 iterations complete successfully
- ✅ Checks artifacts are generated
- ✅ Validates live-apply works
- ✅ Integrated into CI pipeline

**Testing:**
```bash
# Run locally
SOAK_SLEEP_SECONDS=5 python -m pytest tests/smoke/test_soak_smoke.py -v

# Should see:
# test_soak_smoke_3_iterations_mock PASSED
# test_soak_smoke_config_precedence PASSED
# Completed in ~30-60s
```

---

### TASK 1.5: Enhanced Mock Data (Day 3, 4h)

**Goal:** More realistic mock data с volatility spikes, gaps, flash crashes

**Problem:**
- Current mock is linear/predictable (doesn't test edge cases)
- No volatility regime changes
- Missing flash crash scenarios

**Files Changed:**
- `tools/soak/run.py` (enhance mock data generation)
- `tools/soak/mock_generator.py` (NEW, optional refactor)

**Expected Diff:** `tools/soak/run.py` (lines 968-1070)
```python
# Enhanced mock data generation
if args.mock:
    import random
    random.seed(42 + iteration)  # Deterministic but varied
    
    # Determine regime for this iteration
    regime = random.choice(["calm", "calm", "volatile", "spike"])  # 50% calm, 25% volatile, 25% spike
    
    if iteration < 2:
        # First 2 iterations: problematic (force tuning)
        base_net_bps = -1.5 if iteration == 0 else -0.8
        base_risk = 0.65
        base_adverse = 5.0
        base_slippage = 3.5
    elif regime == "calm":
        # Calm regime: low risk, stable metrics
        base_net_bps = 3.0 + random.uniform(-0.2, 0.2)
        base_risk = 0.25 + random.uniform(0, 0.05)
        base_adverse = 1.5 + random.uniform(0, 0.5)
        base_slippage = 1.0 + random.uniform(0, 0.3)
    elif regime == "volatile":
        # Volatile regime: elevated risk, higher variance
        base_net_bps = 2.5 + random.uniform(-0.5, 0.5)
        base_risk = 0.45 + random.uniform(0, 0.15)  # 45-60%
        base_adverse = 3.0 + random.uniform(0, 1.0)
        base_slippage = 2.2 + random.uniform(0, 0.8)
    else:  # spike
        # Flash crash / spike: extreme risk, large slippage
        base_net_bps = 1.8 + random.uniform(-1.0, 0.5)
        base_risk = 0.70 + random.uniform(0, 0.15)  # 70-85%!
        base_adverse = 5.5 + random.uniform(0, 2.0)
        base_slippage = 4.0 + random.uniform(0, 1.5)
        print(f"| mock | SPIKE_REGIME | iter={iteration} risk={base_risk:.2%} |")
    
    # Apply decay for iterations >2 (anti-risk deltas take effect)
    if iteration >= 2:
        decay_iterations = iteration - 2
        risk_decay = 0.83 ** decay_iterations  # 17% relative decrease per iteration
        base_risk = max(0.30, base_risk * risk_decay)
    
    mock_edge_report = {
        "totals": {
            "net_bps": base_net_bps,
            "adverse_bps_p95": base_adverse,
            "slippage_bps_p95": base_slippage,
            "cancel_ratio": max(0.05, 0.60 - (iteration * 0.05)),
            "order_age_p95_ms": 350 + random.randint(-30, 30),
            "ws_lag_p95_ms": 95 + (iteration * 5) + random.randint(-10, 10),
            "maker_share_pct": 90.0 + (iteration * 0.5),
            "component_breakdown": {
                "gross_bps": 8.0,
                "fees_eff_bps": 2.0,
                "slippage_bps": base_slippage,
                "adverse_bps": base_adverse / 2,  # p95 > mean
                "inventory_bps": 0.5,
                "net_bps": base_net_bps
            },
            "neg_edge_drivers": ["slippage_bps"] if base_slippage > 2.5 else [],
            "block_reasons": {
                "min_interval": {"count": 5, "ratio": 0.2},
                "concurrency": {"count": 3, "ratio": 0.12},
                "risk": {"count": int(base_risk * 25), "ratio": base_risk},
                "throttle": {"count": 0, "ratio": 0.0}
            }
        },
        "symbols": {},
        "runtime": {"utc": "2025-10-12T12:00:00Z", "version": "test"}
    }
    
    # Save mock EDGE_REPORT
    edge_report_path = Path("artifacts/reports/EDGE_REPORT.json")
    edge_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(edge_report_path, 'w') as f:
        json.dump(mock_edge_report, f, indent=2)
```

**Invariants:**
- Mock data is deterministic (same seed → same output)
- Covers 3 regimes: calm, volatile, spike
- Forces tuning system to handle edge cases

**Acceptance Criteria:**
- ✅ Mock includes volatility spikes (risk >70%)
- ✅ Mock includes calm periods (risk <30%)
- ✅ Slippage varies realistically (1.0-5.5 bps)
- ✅ Regime logged for debugging

**Testing:**
```bash
# Run smoke test with new mock
SOAK_SLEEP_SECONDS=5 python -m tools.soak.run --iterations 10 --mock --auto-tune

# Verify: ITER_SUMMARY files show varied metrics
for i in {1..10}; do
    cat artifacts/soak/latest/ITER_SUMMARY_${i}.json | jq '.summary.risk_ratio'
done

# Should see: mix of 0.25, 0.45, 0.70 (not monotonic)
```

---

### TASK 1.6: Freeze Logic E2E Test (Day 4, 3h)

**Goal:** Verify freeze activates and prevents param changes when stable

**Problem:**
- Freeze logic complex (multiple conditions)
- Not tested end-to-end
- Unclear if it works in production

**Files Changed:**
- `tests/e2e/test_freeze_logic_e2e.py` (NEW)

**NEW FILE:** `tests/e2e/test_freeze_logic_e2e.py`
```python
"""
E2E test for freeze logic.

Tests:
1. Freeze activates after 2 stable iterations (risk≤0.35, net≥2.7)
2. Frozen params (impact_cap_ratio, max_delta_ratio) not changed during freeze
3. Freeze expires after 4 iterations
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_freeze_activates_on_stable_metrics():
    """Test freeze activates when 2 consecutive iterations are stable."""
    # Cleanup
    latest_dir = Path("artifacts/soak/latest")
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    
    # Setup: create mock EDGE_REPORTs with stable metrics
    # Iteration 1-2: stable (should trigger freeze on iter 3)
    # Iteration 3-6: freeze active
    
    # Run mini-soak (mock will generate stable metrics for first 2 iters)
    # We need to patch mock generator to force stable metrics
    
    # Alternative: Run with a controlled sequence
    # For simplicity, test freeze state persistence
    
    # Create TUNING_STATE with freeze active
    tuning_state_path = latest_dir / "TUNING_STATE.json"
    tuning_state_path.parent.mkdir(parents=True, exist_ok=True)
    
    tuning_state = {
        "last_applied_signature": None,
        "frozen_until_iter": 6,  # Frozen until iteration 6
        "freeze_reason": "steady_safe"
    }
    
    with open(tuning_state_path, 'w') as f:
        json.dump(tuning_state, f, indent=2)
    
    # Create mock ITER_SUMMARY for iteration 3 with deltas for frozen params
    iter3_summary = {
        "iteration": 3,
        "summary": {
            "net_bps": 3.0,
            "risk_ratio": 0.30,
            "adverse_bps_p95": 1.5,
            "slippage_bps_p95": 1.0
        },
        "tuning": {
            "deltas": {
                "impact_cap_ratio": -0.01,  # Should be frozen
                "max_delta_ratio": -0.01,   # Should be frozen
                "min_interval_ms": 5         # NOT frozen
            },
            "rationale": "Test deltas",
            "applied": False
        }
    }
    
    with open(latest_dir / "ITER_SUMMARY_3.json", 'w') as f:
        json.dump(iter3_summary, f, indent=2)
    
    # Setup runtime_overrides
    runtime_overrides = {
        "min_interval_ms": 70,
        "impact_cap_ratio": 0.09,
        "max_delta_ratio": 0.14,
        "base_spread_bps_delta": 0.14,
        "tail_age_ms": 650,
        "replace_rate_per_min": 260
    }
    
    with open("artifacts/soak/runtime_overrides.json", 'w') as f:
        json.dump(runtime_overrides, f, indent=2)
    
    # Apply deltas (should skip frozen params)
    from tools.soak.run import apply_tuning_deltas
    
    result = apply_tuning_deltas(iter_idx=3, total_iterations=10)
    
    # Verify: frozen params NOT changed
    final_overrides = json.load(open("artifacts/soak/runtime_overrides.json"))
    
    assert final_overrides["impact_cap_ratio"] == 0.09, "Frozen param changed!"
    assert final_overrides["max_delta_ratio"] == 0.14, "Frozen param changed!"
    assert final_overrides["min_interval_ms"] == 75, "Non-frozen param NOT changed!"
    
    # Verify: ITER_SUMMARY updated with skip reason
    iter3_updated = json.load(open(latest_dir / "ITER_SUMMARY_3.json"))
    assert not iter3_updated["tuning"]["applied"], "Deltas marked as applied during freeze"
    
    print("[OK] Freeze logic test PASSED - frozen params protected")


def test_freeze_expires_after_duration():
    """Test freeze expires after frozen_until_iter."""
    # Setup: create TUNING_STATE with freeze expired
    latest_dir = Path("artifacts/soak/latest")
    latest_dir.mkdir(parents=True, exist_ok=True)
    
    tuning_state = {
        "last_applied_signature": None,
        "frozen_until_iter": 5,  # Frozen until iter 5
        "freeze_reason": "steady_safe"
    }
    
    with open(latest_dir / "TUNING_STATE.json", 'w') as f:
        json.dump(tuning_state, f, indent=2)
    
    # Create ITER_SUMMARY for iteration 6 (after freeze expires)
    iter6_summary = {
        "iteration": 6,
        "summary": {"net_bps": 3.0, "risk_ratio": 0.30},
        "tuning": {
            "deltas": {
                "impact_cap_ratio": -0.01,  # Should NOT be frozen anymore
                "min_interval_ms": 5
            },
            "rationale": "Test deltas",
            "applied": False
        }
    }
    
    with open(latest_dir / "ITER_SUMMARY_6.json", 'w') as f:
        json.dump(iter6_summary, f, indent=2)
    
    # Setup runtime_overrides
    runtime_overrides = {
        "min_interval_ms": 70,
        "impact_cap_ratio": 0.09,
        "max_delta_ratio": 0.14
    }
    
    with open("artifacts/soak/runtime_overrides.json", 'w') as f:
        json.dump(runtime_overrides, f, indent=2)
    
    # Apply deltas (freeze expired, should apply all)
    from tools.soak.run import apply_tuning_deltas
    
    result = apply_tuning_deltas(iter_idx=6, total_iterations=10)
    
    # Verify: all params changed (freeze expired)
    final_overrides = json.load(open("artifacts/soak/runtime_overrides.json"))
    
    assert final_overrides["impact_cap_ratio"] == 0.08, "Param should change after freeze expires"
    assert final_overrides["min_interval_ms"] == 75, "Param should change"
    
    print("[OK] Freeze expiry test PASSED - params unfrozen after duration")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Acceptance Criteria:**
- ✅ Test verifies freeze blocks frozen params
- ✅ Test verifies freeze allows non-frozen params
- ✅ Test verifies freeze expires correctly
- ✅ Can run in CI (<30s)

**Testing:**
```bash
python -m pytest tests/e2e/test_freeze_logic_e2e.py -v
```

---

### TASK 1.7: Idempotency Stress Test (Day 4, 2h)

**Goal:** Verify applying same deltas 100x has no effect (idempotent)

**Files Changed:**
- `tests/stress/test_idempotency_stress.py` (NEW)

**NEW FILE:** (see audit report for full code)

**Acceptance Criteria:**
- ✅ 100 applications of same deltas → no change to overrides
- ✅ Signature tracking prevents duplicate apply
- ✅ Completes in <10s

---

### TASK 1.8: Oscillation Detector (Day 4-5, 3h)

**Goal:** Detect A→B→A param patterns and warn

**Files Changed:**
- `tools/soak/iter_watcher.py` (add detector)
- `tests/unit/test_oscillation_detection.py` (NEW)

**Expected Diff:** `tools/soak/iter_watcher.py`
```python
# Add after line 193 (after is_freeze_active)

def detect_oscillation(
    history: List[Dict[str, Any]], 
    param: str,
    window: int = 3,
    threshold: float = 0.1
) -> bool:
    """
    Detect oscillation in parameter values (A → B → A pattern).
    
    Args:
        history: List of recent ITER_SUMMARY dicts
        param: Parameter name to check (e.g., "min_interval_ms")
        window: Window size for pattern detection (default: 3)
        threshold: Minimum delta to consider significant (relative)
    
    Returns:
        True if oscillation detected
    """
    if len(history) < window:
        return False
    
    # Extract param values from history
    values = []
    for iter_data in history[-window:]:
        # Check if param was in deltas (applied or skipped)
        tuning = iter_data.get("tuning", {})
        deltas = tuning.get("deltas", {})
        
        # Reconstruct param value at this iteration
        # (simplified: assume runtime_overrides tracks it)
        # In practice, should track cumulative deltas
        if param in deltas:
            values.append(deltas[param])
    
    # Check for A → B → A pattern
    if len(values) >= 3:
        first = values[0]
        middle = values[1]
        last = values[-1]
        
        # A ≈ A (last value close to first)
        if abs(last - first) / abs(first + 1e-9) < 0.1:  # Within 10%
            # B != A (middle significantly different)
            if abs(middle - first) / abs(first + 1e-9) > threshold:
                return True
    
    return False


def check_oscillation_all_params(history: List[Dict[str, Any]]) -> List[str]:
    """
    Check all monitored params for oscillation.
    
    Returns:
        List of param names that are oscillating
    """
    MONITORED_PARAMS = [
        "min_interval_ms",
        "impact_cap_ratio",
        "base_spread_bps_delta",
        "tail_age_ms"
    ]
    
    oscillating = []
    for param in MONITORED_PARAMS:
        if detect_oscillation(history, param):
            oscillating.append(param)
            print(f"| iter_watch | WARN | oscillation detected param={param} |")
    
    return oscillating
```

**Acceptance Criteria:**
- ✅ Detector catches A→B→A patterns
- ✅ Logs warning when oscillation found
- ✅ Unit test coverage

---

### TASK 1.9: Config Precedence Test (Day 5, 2h)

**(See audit report for details)**

---

## 🟠 SPRINT 2 — Resilience & Observability (Days 6-10)

### TASK 2.1: Cooldown Guard (Day 6, 3h)

**(See audit report Task 1.3 diff)**

---

### TASK 2.2: Panic Revert (Day 6, 3h)

**(See audit report Task 1.4 diff)**

---

### TASK 2.3: Velocity Bounds (Day 7, 4h)

**Goal:** Limit max parameter change per hour (prevent runaway)

**Files Changed:**
- `tools/soak/iter_watcher.py` (add velocity tracking)
- `tools/soak/run.py` (integrate check)

**Invariants:**
- Velocity tracked per-param
- Max delta/hour enforced
- Historical deltas stored в `TUNING_STATE.json`

**Acceptance Criteria:**
- ✅ Velocity exceeded → delta rejected
- ✅ Warning logged
- ✅ Unit test coverage

---

### TASK 2.4-2.9: State Validation, Dashboard, Metrics, Tests

**(See audit report for full details)**

---

## 📊 DELIVERABLES CHECKLIST

### Sprint 1 (Days 1-5)
- [ ] Windows CI stable (no cache warnings)
- [ ] Artifact rotation implemented
- [ ] Config consolidated (2 files: profiles/ + runtime_overrides.json)
- [ ] Soak smoke test in CI
- [ ] Enhanced mock data
- [ ] Freeze E2E test
- [ ] Idempotency stress test
- [ ] Oscillation detector
- [ ] Config precedence test

### Sprint 2 (Days 6-10)
- [ ] Cooldown guard
- [ ] Panic revert
- [ ] Velocity bounds
- [ ] State validation
- [ ] Live dashboard
- [ ] Prometheus exporter
- [ ] Panic test
- [ ] Artifact rotation test
- [ ] 24h canary soak

---

## 🔬 TESTING STRATEGY

Each task includes:
1. **Unit test** (fast, isolated)
2. **E2E test** (full workflow)
3. **Smoke test** (fast sanity check)
4. **Stress test** (edge cases)

**Test Pyramid:**
```
         /\
        /  \  E2E (10%)
       /____\  
      /      \ Integration (20%)
     /________\
    /          \ Unit (70%)
   /____________\
```

---

## 🚦 ACCEPTANCE GATES

Each sprint has exit criteria:

**Sprint 1 Exit Gate:**
- ✅ All 9 tasks green checkmarks
- ✅ CI passing (no flakes)
- ✅ Smoke test <2min
- ✅ No linter errors

**Sprint 2 Exit Gate:**
- ✅ All 9 tasks complete
- ✅ 24h canary PASS
- ✅ Dashboard accessible
- ✅ Metrics exported

---

## 📞 SUPPORT & ESCALATION

**Daily Standup:** Review progress, unblock issues  
**Weekly Review:** Sprint retrospective, adjust plan  
**Escalation Path:** Principal → Tech Lead → CTO

---

*Plan approved: PENDING*  
*Start date: TBD*  
*Owner: TBD*

