#!/usr/bin/env python3
"""
Pre-Freeze Sanity Validator - One-shot comprehensive check before production freeze.

Validates:
  1. Smoke tests (6 iterations)
  2. Post-soak gates (8 iterations with KPI validation)
  3. RUN isolation (--run-isolated flag)
  4. Guards functionality (Debounce, PartialFreezeState)
  5. Prometheus metrics export
  6. Release bundle completeness

Exit Codes:
  0 = All checks PASS
  1 = Internal error (IO/JSON/subprocess)
  2 = KPI/post-soak fail
  3 = Smoke fail
  4 = Isolation/materialization fail
  5 = Guards fail
  6 = Metrics fail
  7 = Bundle fail

Usage:
    python -m tools.release.pre_freeze_sanity \\
        --src "artifacts/soak/latest" \\
        --smoke-iters 6 \\
        --post-iters 8 \\
        --run-isolated
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


# Exit codes
EXIT_OK = 0
EXIT_INTERNAL_ERROR = 1
EXIT_POST_SOAK_FAIL = 2
EXIT_SMOKE_FAIL = 3
EXIT_ISOLATION_FAIL = 4
EXIT_GUARDS_FAIL = 5
EXIT_METRICS_FAIL = 6
EXIT_BUNDLE_FAIL = 7


class SanityChecker:
    """Pre-freeze sanity checker orchestrator."""
    
    def __init__(self, src_dir: Path, smoke_iters: int, post_iters: int, run_isolated: bool):
        self.src_dir = src_dir.resolve()
        self.smoke_iters = smoke_iters
        self.post_iters = post_iters
        self.run_isolated = run_isolated
        
        self.results: Dict[str, Dict[str, Any]] = {}
        self.python_exe = sys.executable
    
    def log(self, section: str, message: str, level: str = "INFO"):
        """Log message with section prefix."""
        prefix = {
            "INFO": "[INFO]",
            "WARN": "[WARN]",
            "ERROR": "[ERROR]",
            "OK": "[OK]"
        }.get(level, "[INFO]")
        
        print(f"{prefix} [{section}] {message}")
    
    def run_subprocess(self, cmd: List[str], section: str) -> Tuple[bool, str, str]:
        """Run subprocess and return (success, stdout, stderr)."""
        try:
            self.log(section, f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            success = result.returncode == 0
            return success, result.stdout, result.stderr
        
        except Exception as e:
            self.log(section, f"Subprocess failed: {e}", "ERROR")
            return False, "", str(e)
    
    def check_smoke(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 1: Smoke tests (6 iterations)."""
        section = "SMOKE"
        self.log(section, f"Starting smoke test ({self.smoke_iters} iterations)")
        
        # Clean src directory
        if self.src_dir.exists():
            shutil.rmtree(self.src_dir)
        self.src_dir.mkdir(parents=True, exist_ok=True)
        
        # Run smoke
        cmd = [
            self.python_exe, "-m", "tools.soak.run",
            "--iterations", str(self.smoke_iters),
            "--artifact-root", str(self.src_dir),
            "--auto-tune",
            "--mock"
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Smoke run failed", "ERROR")
            return False, {"status": "FAIL", "reason": "run_failed"}
        
        # Validate artifacts
        soak_latest = self.src_dir / "soak" / "latest"
        
        # Check ITER_SUMMARY files
        missing = []
        for i in range(1, self.smoke_iters + 1):
            iter_file = soak_latest / f"ITER_SUMMARY_{i}.json"
            if not iter_file.exists():
                missing.append(iter_file.name)
        
        if missing:
            self.log(section, f"Missing files: {', '.join(missing)}", "ERROR")
            return False, {"status": "FAIL", "reason": "missing_iter_summaries", "missing": missing}
        
        # Check TUNING_REPORT
        tuning_report_path = soak_latest / "TUNING_REPORT.json"
        if not tuning_report_path.exists():
            self.log(section, "TUNING_REPORT.json not found", "ERROR")
            return False, {"status": "FAIL", "reason": "missing_tuning_report"}
        
        try:
            with open(tuning_report_path, 'r', encoding='utf-8') as f:
                tuning_report = json.load(f)
            
            iterations = tuning_report.get("iterations", [])
            if len(iterations) != self.smoke_iters:
                self.log(section, f"len(iterations)={len(iterations)}, expected {self.smoke_iters}", "ERROR")
                return False, {
                    "status": "FAIL",
                    "reason": "wrong_iteration_count",
                    "expected": self.smoke_iters,
                    "actual": len(iterations)
                }
        
        except Exception as e:
            self.log(section, f"Failed to load TUNING_REPORT: {e}", "ERROR")
            return False, {"status": "FAIL", "reason": "tuning_report_parse_error"}
        
        # Check average maker/taker ratio
        mt_ratios = []
        for i in range(1, self.smoke_iters + 1):
            iter_file = soak_latest / f"ITER_SUMMARY_{i}.json"
            try:
                with open(iter_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    mt = data.get("summary", {}).get("maker_taker_ratio", 0)
                    mt_ratios.append(mt)
            except:
                pass
        
        if mt_ratios:
            avg_mt = sum(mt_ratios) / len(mt_ratios)
            self.log(section, f"Average maker/taker ratio: {avg_mt:.3f}")
            
            if avg_mt < 0.50:
                self.log(section, f"Average m/t {avg_mt:.3f} < 0.50", "WARN")
                # Don't fail, just warn for smoke
        
        self.log(section, "Smoke test PASSED", "OK")
        return True, {
            "status": "PASS",
            "iterations": self.smoke_iters,
            "avg_maker_taker": avg_mt if mt_ratios else 0
        }
    
    def check_post_soak(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 2: Post-soak gates (8 iterations with KPI validation)."""
        section = "POST-SOAK"
        self.log(section, f"Starting post-soak test ({self.post_iters} iterations)")
        
        # Clean src directory
        if self.src_dir.exists():
            shutil.rmtree(self.src_dir)
        self.src_dir.mkdir(parents=True, exist_ok=True)
        
        # Run post-soak
        cmd = [
            self.python_exe, "-m", "tools.soak.run",
            "--iterations", str(self.post_iters),
            "--artifact-root", str(self.src_dir),
            "--auto-tune",
            "--mock"
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Post-soak run failed", "ERROR")
            return False, {"status": "FAIL", "reason": "run_failed"}
        
        # Run delta verification
        soak_latest = self.src_dir / "soak" / "latest"
        reports_dir = self.src_dir / "reports" / "analysis"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        delta_verify_path = reports_dir / "DELTA_VERIFY_REPORT.json"
        
        cmd = [
            self.python_exe, "-m", "tools.soak.verify_deltas_applied",
            "--path", str(soak_latest),
            "--strict",
            "--json"
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        # Write delta verify output
        if stdout:
            with open(delta_verify_path, 'w', encoding='utf-8') as f:
                f.write(stdout)
        
        # Generate reports
        cmd = [
            self.python_exe, "-m", "tools.soak.build_reports",
            "--src", str(self.src_dir),
            "--out", str(reports_dir),
            "--last-n", str(self.post_iters)
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Report generation failed", "ERROR")
            return False, {"status": "FAIL", "reason": "report_generation_failed"}
        
        # Read and validate POST_SOAK_SNAPSHOT
        snapshot_path = reports_dir / "POST_SOAK_SNAPSHOT.json"
        if not snapshot_path.exists():
            self.log(section, "POST_SOAK_SNAPSHOT.json not found", "ERROR")
            return False, {"status": "FAIL", "reason": "missing_snapshot"}
        
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)
        except Exception as e:
            self.log(section, f"Failed to load snapshot: {e}", "ERROR")
            return False, {"status": "FAIL", "reason": "snapshot_parse_error"}
        
        # Validate KPIs (last-8)
        kpi_last_n = snapshot.get("kpi_last_n", {})
        
        maker_taker = kpi_last_n.get("maker_taker_ratio", {}).get("mean", 0)
        p95_latency = kpi_last_n.get("p95_latency_ms", {}).get("max", 999)
        risk_ratio = kpi_last_n.get("risk_ratio", {}).get("median", 1)
        net_bps = kpi_last_n.get("net_bps", {}).get("mean", 0)
        
        self.log(section, f"KPI Last-{self.post_iters}:")
        self.log(section, f"  Maker/Taker: {maker_taker:.3f} (target >= 0.83)")
        self.log(section, f"  P95 Latency: {p95_latency:.0f}ms (target <= 340ms)")
        self.log(section, f"  Risk Ratio: {risk_ratio:.3f} (target <= 0.40)")
        self.log(section, f"  Net BPS: {net_bps:.2f} (target >= 2.5)")
        
        failures = []
        if maker_taker < 0.83:
            failures.append(f"maker_taker {maker_taker:.3f} < 0.83")
        if p95_latency > 340:
            failures.append(f"p95_latency {p95_latency:.0f}ms > 340ms")
        if risk_ratio > 0.40:
            failures.append(f"risk_ratio {risk_ratio:.3f} > 0.40")
        if net_bps < 2.5:
            failures.append(f"net_bps {net_bps:.2f} < 2.5")
        
        # Read delta verification
        full_apply_ratio = 0.0
        if delta_verify_path.exists():
            try:
                with open(delta_verify_path, 'r', encoding='utf-8') as f:
                    delta_verify = json.load(f)
                    full_apply_ratio = delta_verify.get("full_apply_ratio", 0.0)
                
                self.log(section, f"  Delta Apply Ratio: {full_apply_ratio:.3f} (target >= 0.95)")
                
                if full_apply_ratio < 0.95:
                    failures.append(f"full_apply_ratio {full_apply_ratio:.3f} < 0.95")
            
            except:
                self.log(section, "Failed to read delta verify report", "WARN")
        
        if failures:
            self.log(section, f"KPI validation FAILED: {', '.join(failures)}", "ERROR")
            return False, {
                "status": "FAIL",
                "reason": "kpi_thresholds_not_met",
                "failures": failures,
                "kpi": {
                    "maker_taker": maker_taker,
                    "p95_latency": p95_latency,
                    "risk_ratio": risk_ratio,
                    "net_bps": net_bps,
                    "full_apply_ratio": full_apply_ratio
                }
            }
        
        self.log(section, "Post-soak gates PASSED", "OK")
        return True, {
            "status": "PASS",
            "kpi": {
                "maker_taker": maker_taker,
                "p95_latency": p95_latency,
                "risk_ratio": risk_ratio,
                "net_bps": net_bps,
                "full_apply_ratio": full_apply_ratio
            }
        }
    
    def check_isolation(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 3: RUN isolation (--run-isolated flag)."""
        section = "ISOLATION"
        self.log(section, f"Testing RUN isolation ({self.post_iters} iterations)")
        
        # Clean src directory
        if self.src_dir.exists():
            shutil.rmtree(self.src_dir)
        self.src_dir.mkdir(parents=True, exist_ok=True)
        
        # Run with --run-isolated
        cmd = [
            self.python_exe, "-m", "tools.soak.run",
            "--iterations", str(self.post_iters),
            "--artifact-root", str(self.src_dir),
            "--auto-tune",
            "--mock",
            "--run-isolated"
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Isolated run failed", "ERROR")
            return False, {"status": "FAIL", "reason": "run_failed"}
        
        # Check for RUN_<epoch> directory
        run_dirs = list(self.src_dir.glob("RUN_*"))
        
        if not run_dirs:
            self.log(section, "No RUN_<epoch> directory found", "ERROR")
            return False, {"status": "FAIL", "reason": "no_run_directory"}
        
        run_dir = run_dirs[0]
        self.log(section, f"Found isolated directory: {run_dir.name}")
        
        # Check materialization (key files in both RUN_*/ and latest/)
        soak_latest = self.src_dir / "soak" / "latest"
        
        # Files should exist in latest/ (materialized)
        tuning_report_latest = soak_latest / "TUNING_REPORT.json"
        if not tuning_report_latest.exists():
            self.log(section, "TUNING_REPORT.json not materialized to latest/", "ERROR")
            return False, {"status": "FAIL", "reason": "no_materialization"}
        
        # Check ITER_SUMMARY files
        missing_latest = []
        for i in range(1, self.post_iters + 1):
            iter_file = soak_latest / f"ITER_SUMMARY_{i}.json"
            if not iter_file.exists():
                missing_latest.append(iter_file.name)
        
        if missing_latest:
            self.log(section, f"Missing materialized files: {', '.join(missing_latest)}", "ERROR")
            return False, {"status": "FAIL", "reason": "incomplete_materialization"}
        
        self.log(section, "RUN isolation test PASSED", "OK")
        return True, {
            "status": "PASS",
            "run_dir": run_dir.name,
            "materialized_files": self.post_iters + 1  # TUNING_REPORT + ITER_SUMMARY_*
        }
    
    def check_guards(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 4: Guards functionality."""
        section = "GUARDS"
        self.log(section, "Testing guards module")
        
        try:
            from tools.soak.guards import Debounce, PartialFreezeState
        except ImportError as e:
            self.log(section, f"Failed to import guards module: {e}", "ERROR")
            return False, {"status": "FAIL", "reason": "import_error"}
        
        # Test Debounce
        self.log(section, "Testing Debounce (open=2500ms, close=4000ms)")
        
        debounce = Debounce(open_ms=2500, close_ms=4000)
        
        # Signal TRUE but not long enough
        debounce.update(True)
        if debounce.is_active():
            self.log(section, "Debounce activated too early", "ERROR")
            return False, {"status": "FAIL", "reason": "debounce_open_too_fast"}
        
        # Wait 2.6s and signal TRUE again
        time.sleep(2.6)
        changed = debounce.update(True)
        if not changed or not debounce.is_active():
            self.log(section, "Debounce failed to open after 2.6s", "ERROR")
            return False, {"status": "FAIL", "reason": "debounce_open_failed"}
        
        self.log(section, "Debounce open: OK")
        
        # Test close (signal FALSE)
        debounce.update(False)
        if not debounce.is_active():
            self.log(section, "Debounce closed too early", "ERROR")
            return False, {"status": "FAIL", "reason": "debounce_close_too_fast"}
        
        # Wait 4.1s and signal FALSE again
        time.sleep(4.1)
        changed = debounce.update(False)
        if not changed or debounce.is_active():
            self.log(section, "Debounce failed to close after 4.1s", "ERROR")
            return False, {"status": "FAIL", "reason": "debounce_close_failed"}
        
        self.log(section, "Debounce close: OK")
        
        # Test PartialFreezeState
        self.log(section, "Testing PartialFreezeState")
        
        freeze = PartialFreezeState()
        freeze.activate(subsystems=['rebid', 'rescue_taker'], reason='oscillation')
        
        if not freeze.is_frozen('rebid'):
            self.log(section, "rebid not frozen", "ERROR")
            return False, {"status": "FAIL", "reason": "freeze_rebid_failed"}
        
        if not freeze.is_frozen('rescue_taker'):
            self.log(section, "rescue_taker not frozen", "ERROR")
            return False, {"status": "FAIL", "reason": "freeze_rescue_failed"}
        
        if freeze.is_frozen('edge'):
            self.log(section, "edge should never be frozen", "ERROR")
            return False, {"status": "FAIL", "reason": "edge_frozen"}
        
        self.log(section, "PartialFreezeState: OK")
        
        self.log(section, "Guards sanity PASSED", "OK")
        return True, {
            "status": "PASS",
            "debounce_open_ms": 2500,
            "debounce_close_ms": 4000,
            "partial_freeze_subsystems": ['rebid', 'rescue_taker'],
            "edge_never_frozen": True
        }
    
    def check_metrics(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 5: Prometheus metrics export."""
        section = "METRICS"
        self.log(section, "Testing Prometheus metrics export")
        
        # Need post-soak artifacts
        soak_latest = self.src_dir / "soak" / "latest"
        if not soak_latest.exists():
            self.log(section, "No soak artifacts found, running post-soak first", "WARN")
            # Run minimal soak
            success, _ = self.check_post_soak()
            if not success:
                return False, {"status": "FAIL", "reason": "no_artifacts"}
        
        # Export metrics
        metrics_path = self.src_dir / "metrics.prom"
        
        cmd = [
            self.python_exe, "-m", "tools.soak.prometheus_exporter",
            "--path", str(soak_latest),
            "--output", str(metrics_path)
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Metrics export failed", "ERROR")
            return False, {"status": "FAIL", "reason": "export_failed"}
        
        # Read metrics file
        if not metrics_path.exists():
            self.log(section, "metrics.prom not created", "ERROR")
            return False, {"status": "FAIL", "reason": "no_metrics_file"}
        
        try:
            with open(metrics_path, 'r', encoding='utf-8') as f:
                metrics_text = f.read()
        except Exception as e:
            self.log(section, f"Failed to read metrics: {e}", "ERROR")
            return False, {"status": "FAIL", "reason": "read_error"}
        
        # Parse metrics
        metrics_found = {}
        
        for line in metrics_text.split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            
            if 'maker_taker_ratio_hmean' in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics_found['maker_taker_ratio_hmean'] = float(parts[1])
            
            if 'maker_share_pct' in line and 'maker_taker' not in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics_found['maker_share_pct'] = float(parts[1])
            
            if 'partial_freeze_active' in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics_found['partial_freeze_active'] = float(parts[1])
        
        # Validate metrics
        required = ['maker_taker_ratio_hmean', 'maker_share_pct', 'partial_freeze_active']
        missing = [m for m in required if m not in metrics_found]
        
        if missing:
            self.log(section, f"Missing metrics: {', '.join(missing)}", "ERROR")
            return False, {"status": "FAIL", "reason": "missing_metrics", "missing": missing}
        
        self.log(section, f"maker_taker_ratio_hmean = {metrics_found['maker_taker_ratio_hmean']:.3f}")
        self.log(section, f"maker_share_pct = {metrics_found['maker_share_pct']:.2f}%")
        self.log(section, f"partial_freeze_active = {metrics_found['partial_freeze_active']:.0f}")
        
        # Validate partial_freeze_active is 0 or 1
        if metrics_found['partial_freeze_active'] not in [0.0, 1.0]:
            self.log(section, f"partial_freeze_active should be 0 or 1", "WARN")
        
        self.log(section, "Metrics export PASSED", "OK")
        return True, {
            "status": "PASS",
            "metrics": metrics_found
        }
    
    def check_bundle(self) -> Tuple[bool, Dict[str, Any]]:
        """Section 6: Release bundle completeness."""
        section = "BUNDLE"
        self.log(section, "Testing release bundle generation")
        
        # Generate bundle
        bundle_dir = Path("release/soak-ci-chaos-release-toolkit")
        
        cmd = [
            self.python_exe, "-m", "tools.release.build_release_bundle",
            "--src", str(self.src_dir),
            "--out", str(bundle_dir)
        ]
        
        success, stdout, stderr = self.run_subprocess(cmd, section)
        
        if not success:
            self.log(section, "Bundle generation failed", "ERROR")
            return False, {"status": "FAIL", "reason": "generation_failed"}
        
        # Check required files
        required_files = [
            "POST_SOAK_SNAPSHOT.json",
            "POST_SOAK_AUDIT.md",
            "RECOMMENDATIONS.md",
            "FAILURES.md",
            "soak_profile.runtime_overrides.json",
            "CHANGELOG.md",
            "rollback_plan.md"
        ]
        
        optional_files = [
            "DELTA_VERIFY_REPORT.json",
            "CANARY_CHECKLIST.md"
        ]
        
        missing_required = []
        for filename in required_files:
            filepath = bundle_dir / filename
            if not filepath.exists():
                missing_required.append(filename)
        
        if missing_required:
            self.log(section, f"Missing required files: {', '.join(missing_required)}", "ERROR")
            return False, {"status": "FAIL", "reason": "missing_files", "missing": missing_required}
        
        # Check optional files (just warn)
        missing_optional = []
        for filename in optional_files:
            filepath = bundle_dir / filename
            if not filepath.exists():
                missing_optional.append(filename)
        
        if missing_optional:
            self.log(section, f"Missing optional files: {', '.join(missing_optional)}", "WARN")
        
        self.log(section, "Release bundle PASSED", "OK")
        return True, {
            "status": "PASS",
            "bundle_dir": str(bundle_dir),
            "files_count": len(required_files) + len(optional_files) - len(missing_optional)
        }
    
    def run_all_checks(self) -> int:
        """Run all sanity checks and return exit code."""
        print("=" * 80)
        print("PRE-FREEZE SANITY VALIDATOR")
        print("=" * 80)
        print(f"Source directory: {self.src_dir}")
        print(f"Smoke iterations: {self.smoke_iters}")
        print(f"Post-soak iterations: {self.post_iters}")
        print(f"RUN isolation: {self.run_isolated}")
        print("=" * 80)
        print()
        
        # Section 1: Smoke
        print("[1/6] Smoke tests...")
        success, result = self.check_smoke()
        self.results['smoke'] = result
        if not success:
            self.write_summary()
            return EXIT_SMOKE_FAIL
        print()
        
        # Section 2: Post-soak
        print("[2/6] Post-soak gates...")
        success, result = self.check_post_soak()
        self.results['post_soak'] = result
        if not success:
            self.write_summary()
            return EXIT_POST_SOAK_FAIL
        print()
        
        # Section 3: Isolation
        if self.run_isolated:
            print("[3/6] RUN isolation...")
            success, result = self.check_isolation()
            self.results['isolation'] = result
            if not success:
                self.write_summary()
                return EXIT_ISOLATION_FAIL
            print()
        else:
            print("[3/6] RUN isolation... SKIPPED (no --run-isolated flag)")
            self.results['isolation'] = {"status": "SKIPPED"}
            print()
        
        # Section 4: Guards
        print("[4/6] Guards sanity...")
        success, result = self.check_guards()
        self.results['guards'] = result
        if not success:
            self.write_summary()
            return EXIT_GUARDS_FAIL
        print()
        
        # Section 5: Metrics
        print("[5/6] Prometheus metrics...")
        success, result = self.check_metrics()
        self.results['metrics'] = result
        if not success:
            self.write_summary()
            return EXIT_METRICS_FAIL
        print()
        
        # Section 6: Bundle
        print("[6/6] Release bundle...")
        success, result = self.check_bundle()
        self.results['bundle'] = result
        if not success:
            self.write_summary()
            return EXIT_BUNDLE_FAIL
        print()
        
        # All checks passed
        self.write_summary()
        return EXIT_OK
    
    def write_summary(self):
        """Write PRE_FREEZE_SANITY_SUMMARY.md."""
        summary_path = self.src_dir / "PRE_FREEZE_SANITY_SUMMARY.md"
        
        lines = []
        
        # Header
        lines.append("# Pre-Freeze Sanity Summary")
        lines.append("")
        lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Source:** {self.src_dir}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Results table
        lines.append("## Results")
        lines.append("")
        lines.append("| Section | Status | Details |")
        lines.append("|---------|--------|---------|")
        
        for section_name, result in self.results.items():
            status = result.get('status', 'UNKNOWN')
            status_emoji = "✅" if status == "PASS" else "⏭️" if status == "SKIPPED" else "❌"
            
            details = []
            if section_name == 'smoke':
                details.append(f"{result.get('iterations', 0)} iterations")
            elif section_name == 'post_soak' and 'kpi' in result:
                kpi = result['kpi']
                details.append(f"m/t={kpi.get('maker_taker', 0):.2f}")
                details.append(f"p95={kpi.get('p95_latency', 0):.0f}ms")
            elif section_name == 'isolation':
                if 'run_dir' in result:
                    details.append(result['run_dir'])
            
            details_str = ', '.join(details) if details else result.get('reason', '')
            
            lines.append(f"| {section_name} | {status_emoji} {status} | {details_str} |")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Artifacts
        lines.append("## Artifacts")
        lines.append("")
        lines.append(f"- **Soak artifacts:** `{self.src_dir / 'soak' / 'latest'}`")
        lines.append(f"- **Reports:** `{self.src_dir / 'reports' / 'analysis'}`")
        lines.append(f"- **Metrics:** `{self.src_dir / 'metrics.prom'}`")
        lines.append(f"- **Bundle:** `release/soak-ci-chaos-release-toolkit/`")
        lines.append("")
        
        # Final verdict
        all_passed = all(r.get('status') in ['PASS', 'SKIPPED'] for r in self.results.values())
        
        lines.append("## Final Verdict")
        lines.append("")
        if all_passed:
            lines.append("✅ **PASS** - All checks passed, ready for production freeze")
        else:
            failed_sections = [k for k, v in self.results.items() if v.get('status') == 'FAIL']
            lines.append(f"❌ **FAIL** - Failed sections: {', '.join(failed_sections)}")
        
        lines.append("")
        
        # Write file
        try:
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            print(f"\n[OK] Summary written to: {summary_path}")
        
        except Exception as e:
            print(f"\n[ERROR] Failed to write summary: {e}")
        
        # Print final verdict to console
        print()
        print("=" * 80)
        print("FINAL VERDICT")
        print("=" * 80)
        
        for section_name, result in self.results.items():
            status = result.get('status', 'UNKNOWN')
            status_str = "[OK]" if status == "PASS" else "[SKIP]" if status == "SKIPPED" else "[FAIL]"
            print(f"{status_str} {section_name:15s} {status}")
        
        print("=" * 80)
        
        if all_passed:
            print("✅ PASS - Ready for production freeze")
        else:
            print("❌ FAIL - Review failures above")
        
        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-freeze sanity validator - comprehensive check before production freeze",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--src",
        type=str,
        required=True,
        help="Source directory for soak artifacts"
    )
    parser.add_argument(
        "--alt-src",
        type=str,
        help="Alternative source directory (for comparison, optional)"
    )
    parser.add_argument(
        "--smoke-iters",
        type=int,
        default=6,
        help="Number of smoke test iterations (default: 6)"
    )
    parser.add_argument(
        "--post-iters",
        type=int,
        default=8,
        help="Number of post-soak iterations (default: 8)"
    )
    parser.add_argument(
        "--run-isolated",
        action="store_true",
        help="Test RUN isolation (--run-isolated flag)"
    )
    
    args = parser.parse_args()
    
    src_dir = Path(args.src)
    
    checker = SanityChecker(
        src_dir=src_dir,
        smoke_iters=args.smoke_iters,
        post_iters=args.post_iters,
        run_isolated=args.run_isolated
    )
    
    try:
        exit_code = checker.run_all_checks()
        return exit_code
    
    except Exception as e:
        print(f"\n[FATAL] Internal error: {e}")
        import traceback
        traceback.print_exc()
        return EXIT_INTERNAL_ERROR


if __name__ == '__main__':
    sys.exit(main())

