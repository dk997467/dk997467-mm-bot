#!/usr/bin/env python3
"""
MEGAPROMPT Workflow: Finish Line (Prep → Shadow 60m → Soak → Dataset → A/B → CI → Ops)

Automates the entire workflow from preparation to production readiness.

Usage:
    python tools/soak/megaprompt_workflow.py --step 1     # Run specific step
    python tools/soak/megaprompt_workflow.py --all        # Run all steps (long!)
    python tools/soak/megaprompt_workflow.py --status     # Check current status
"""

import sys
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class WorkflowOrchestrator:
    """Orchestrates the complete finish line workflow."""
    
    def __init__(self):
        self.project_root = Path.cwd()
        self.artifacts_root = self.project_root / "artifacts"
        self.reports_dir = self.artifacts_root / "reports"
        self.release_dir = self.artifacts_root / "release"
        self.baseline_dir = self.artifacts_root / "baseline"
        
        # Ensure directories exist
        for d in [self.reports_dir, self.release_dir, self.baseline_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def log(self, msg: str):
        """Log a message with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def check_prerequisites(self) -> Tuple[bool, List[str]]:
        """Check if all prerequisites are met."""
        issues = []
        
        # Check critical files
        required_files = [
            "config.yaml",
            "config.soak_overrides.yaml",
            "tools/shadow/shadow_baseline.py",
            "tools/soak/generate_pre_soak_report.py",
        ]
        
        for f in required_files:
            if not (self.project_root / f).exists():
                issues.append(f"Missing required file: {f}")
        
        # Check Python environment
        try:
            import yaml
            import orjson
        except ImportError as e:
            issues.append(f"Missing Python dependency: {e}")
        
        return len(issues) == 0, issues
    
    def step_1_prep_and_overrides(self) -> Dict:
        """Step 1: Prep & Overrides (5 min)."""
        self.log("=" * 60)
        self.log("STEP 1: PREP & OVERRIDES")
        self.log("=" * 60)
        
        result = {
            "step": 1,
            "name": "Prep & Overrides",
            "status": "PASS",
            "duration_sec": 0,
            "artifacts": [],
            "issues": []
        }
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # [1] Validate config overrides exist
            self.log("[1/5] Validating config files...")
            config_file = self.project_root / "config.yaml"
            overrides_file = self.project_root / "config.soak_overrides.yaml"
            
            if not config_file.exists():
                result["issues"].append("config.yaml not found")
                result["status"] = "FAIL"
                return result
            
            if not overrides_file.exists():
                result["issues"].append("config.soak_overrides.yaml not found")
                result["status"] = "FAIL"
                return result
            
            self.log("[OK] Config files exist")
            
            # [2] Validate override content
            self.log("[2/5] Validating override content...")
            import yaml
            
            with open(overrides_file, 'r') as f:
                overrides = yaml.safe_load(f)
            
            # Check required flags
            required_flags = {
                'pipeline.enabled': overrides.get('pipeline', {}).get('enabled'),
                'md_cache.enabled': overrides.get('md_cache', {}).get('enabled'),
                'taker_cap.max_taker_share_pct': overrides.get('taker_cap', {}).get('max_taker_share_pct'),
                'trace.enabled': overrides.get('trace', {}).get('enabled'),
                'async_batch.enabled': overrides.get('async_batch', {}).get('enabled'),
            }
            
            for flag, value in required_flags.items():
                if value is None:
                    result["issues"].append(f"Missing flag: {flag}")
                elif flag == 'taker_cap.max_taker_share_pct' and value > 9.0:
                    result["issues"].append(f"{flag} = {value} (must be <= 9.0)")
                elif flag != 'taker_cap.max_taker_share_pct' and value != True:
                    result["issues"].append(f"{flag} = {value} (must be true)")
            
            if result["issues"]:
                result["status"] = "FAIL"
                return result
            
            self.log("[OK] All required flags validated")
            
            # [3] Create feature flags snapshot
            self.log("[3/5] Creating feature flags snapshot...")
            snapshot_path = self.release_dir / "FEATURE_FLAGS_SNAPSHOT.json"
            
            snapshot = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "environment": "pre-soak",
                "flags": {
                    "pipeline": overrides.get('pipeline', {}),
                    "md_cache": overrides.get('md_cache', {}),
                    "taker_cap": overrides.get('taker_cap', {}),
                    "async_batch": overrides.get('async_batch', {}),
                    "trace": overrides.get('trace', {}),
                    "risk_guards": overrides.get('risk_guards', {})
                },
                "rollback_instructions": {
                    "step_1": "Set pipeline.enabled = false",
                    "step_2": "Set md_cache.enabled = false",
                    "step_3": "Set async_batch.enabled = false",
                    "step_4": "Restart service: systemctl restart mm-bot"
                }
            }
            
            with open(snapshot_path, 'w') as f:
                json.dump(snapshot, f, indent=2)
            
            result["artifacts"].append(str(snapshot_path))
            self.log(f"[OK] Snapshot created: {snapshot_path}")
            
            # [4] Verify directories
            self.log("[4/5] Verifying directories...")
            required_dirs = [
                "artifacts/edge/feeds",
                "artifacts/edge/datasets",
                "artifacts/edge/reports",
                "artifacts/baseline",
                "artifacts/release",
                "artifacts/reports",
                "artifacts/md_cache"
            ]
            
            for d in required_dirs:
                dir_path = self.project_root / d
                dir_path.mkdir(parents=True, exist_ok=True)
                self.log(f"[OK] {d}")
            
            # [5] Create PREP_LOG.md
            self.log("[5/5] Creating PREP_LOG.md...")
            prep_log_path = self.reports_dir / "PREP_LOG.md"
            
            with open(prep_log_path, 'w', encoding='utf-8') as f:
                f.write("# Pre-Soak Preparation Log\n\n")
                f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
                f.write("## Status: ✅ PASS\n\n")
                f.write("## Checklist\n\n")
                f.write("- ✅ Config overrides validated\n")
                f.write("- ✅ Feature flags snapshot created\n")
                f.write("- ✅ Directories verified\n")
                f.write("- ✅ All blocking items resolved\n\n")
                f.write("## Configuration Overrides\n\n")
                f.write("```yaml\n")
                with open(overrides_file, 'r') as ov:
                    f.write(ov.read())
                f.write("```\n\n")
                f.write("## Next Steps\n\n")
                f.write("1. **Run Shadow 60m:**\n")
                f.write("   ```bash\n")
                f.write("   python tools/shadow/shadow_baseline.py --duration 60\n")
                f.write("   ```\n\n")
                f.write("2. **Launch Soak Test:**\n")
                f.write("   ```bash\n")
                f.write("   python main.py --config config.yaml --config-override config.soak_overrides.yaml --mode soak --duration 72\n")
                f.write("   ```\n")
            
            result["artifacts"].append(str(prep_log_path))
            self.log(f"[OK] Prep log created: {prep_log_path}")
            
        except Exception as e:
            result["status"] = "FAIL"
            result["issues"].append(f"Exception: {str(e)}")
            self.log(f"[ERROR] {e}")
        
        finally:
            end_time = datetime.now(timezone.utc)
            result["duration_sec"] = (end_time - start_time).total_seconds()
        
        return result
    
    def step_2_shadow_60m(self, duration_min: int = 60) -> Dict:
        """Step 2: Shadow 60 minutes."""
        self.log("=" * 60)
        self.log("STEP 2: SHADOW 60 MINUTES")
        self.log("=" * 60)
        
        result = {
            "step": 2,
            "name": "Shadow 60m",
            "status": "PASS",
            "duration_sec": 0,
            "artifacts": [],
            "issues": []
        }
        
        start_time = datetime.now(timezone.utc)
        
        try:
            shadow_script = self.project_root / "tools/shadow/shadow_baseline.py"
            if not shadow_script.exists():
                result["status"] = "FAIL"
                result["issues"].append("shadow_baseline.py not found")
                return result
            
            self.log(f"Running shadow baseline for {duration_min} minutes...")
            self.log("This will take a while. Monitor progress in console.")
            
            # Run shadow baseline
            cmd = [
                sys.executable,
                str(shadow_script),
                "--duration", str(duration_min)
            ]
            
            proc = subprocess.run(cmd, capture_output=True, text=True)
            
            if proc.returncode != 0:
                result["status"] = "FAIL"
                result["issues"].append(f"Shadow baseline failed: {proc.stderr}")
                return result
            
            # Check artifacts
            expected_artifacts = [
                self.baseline_dir / "stage_budgets.json",
                self.artifacts_root / "md_cache/shadow_report.md",
            ]
            
            for artifact in expected_artifacts:
                if artifact.exists():
                    result["artifacts"].append(str(artifact))
                    self.log(f"[OK] Artifact created: {artifact}")
                else:
                    result["issues"].append(f"Missing artifact: {artifact}")
            
            # Validate gates
            budget_file = self.baseline_dir / "stage_budgets.json"
            if budget_file.exists():
                with open(budget_file, 'r') as f:
                    budget = json.load(f)
                
                gates = {
                    'hit_ratio': (budget.get('md_cache', {}).get('hit_ratio', 0), 0.7, '>='),
                    'fetch_md_p95': (budget.get('fetch_md', {}).get('p95_ms', 999), 35, '<='),
                    'tick_total_p95': (budget.get('tick_total', {}).get('p95_ms', 999), 150, '<='),
                    'deadline_miss': (budget.get('tick_total', {}).get('deadline_miss_rate', 1.0), 0.02, '<'),
                }
                
                self.log("\nGate validation:")
                for gate_name, (value, threshold, op) in gates.items():
                    if op == '>=':
                        passed = value >= threshold
                    elif op == '<=':
                        passed = value <= threshold
                    else:  # '<'
                        passed = value < threshold
                    
                    status = "[OK] PASS" if passed else "[FAIL]"
                    self.log(f"  {status} {gate_name}: {value} {op} {threshold}")
                    
                    if not passed:
                        result["issues"].append(f"Gate failed: {gate_name}")
                
                if result["issues"]:
                    result["status"] = "FAIL"
            
        except Exception as e:
            result["status"] = "FAIL"
            result["issues"].append(f"Exception: {str(e)}")
            self.log(f"[ERROR] {e}")
        
        finally:
            end_time = datetime.now(timezone.utc)
            result["duration_sec"] = (end_time - start_time).total_seconds()
        
        return result
    
    def step_3_soak_instructions(self) -> Dict:
        """Step 3: Generate soak test instructions (doesn't run the test)."""
        self.log("=" * 60)
        self.log("STEP 3: SOAK TEST INSTRUCTIONS")
        self.log("=" * 60)
        
        result = {
            "step": 3,
            "name": "Soak Test Instructions",
            "status": "PASS",
            "duration_sec": 0,
            "artifacts": [],
            "issues": []
        }
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Create SOAK_START.md with instructions
            soak_start_path = self.reports_dir / "SOAK_START.md"
            
            with open(soak_start_path, 'w', encoding='utf-8') as f:
                f.write("# Soak Test Start Instructions\n\n")
                f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
                f.write("## Launch Command\n\n")
                f.write("```bash\n")
                f.write("python main.py \\\n")
                f.write("  --config config.yaml \\\n")
                f.write("  --config-override config.soak_overrides.yaml \\\n")
                f.write("  --mode soak \\\n")
                f.write("  --duration 72\n")
                f.write("```\n\n")
                f.write("## Stop Criteria (Auto-alerts)\n\n")
                f.write("🚨 **CRITICAL (immediate stop):**\n")
                f.write("- `deadline_miss > 5%` for 10+ minutes\n")
                f.write("- `md_cache.hit_ratio < 50%` for 30+ minutes\n")
                f.write("- `taker_share > 15%` for 1+ hour\n")
                f.write("- Memory leak: +100MB/hour sustained\n")
                f.write("- Circuit breaker open > 5 minutes\n\n")
                f.write("⚠️ **WARNING (investigate):**\n")
                f.write("- `tick_total p95 > 180ms`\n")
                f.write("- `fetch_md p95 > 45ms`\n")
                f.write("- Error rate spike: `ERR_* > 10/min`\n\n")
                f.write("## Monitoring\n\n")
                f.write("### Key PromQL Queries\n\n")
                f.write("**Latency:**\n")
                f.write("```promql\n")
                f.write("histogram_quantile(0.95, mm_tick_duration_seconds_bucket)\n")
                f.write("histogram_quantile(0.95, mm_stage_duration_seconds_bucket{stage=\"fetch_md\"})\n")
                f.write("```\n\n")
                f.write("**MD-Cache:**\n")
                f.write("```promql\n")
                f.write("rate(mm_md_cache_hit_total[5m]) / (rate(mm_md_cache_hit_total[5m]) + rate(mm_md_cache_miss_total[5m]))\n")
                f.write("```\n\n")
                f.write("**Taker Share:**\n")
                f.write("```promql\n")
                f.write("rate(mm_fills_total{type=\"taker\"}[1h]) / rate(mm_fills_total[1h])\n")
                f.write("```\n\n")
                f.write("**Errors:**\n")
                f.write("```promql\n")
                f.write("sum(rate(mm_error_total[5m])) by (code)\n")
                f.write("```\n\n")
                f.write("## Expected Logs\n\n")
                f.write("- `artifacts/edge/feeds/fills_YYYYMMDD.jsonl` (daily rotation)\n")
                f.write("- `artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl` (daily rotation)\n\n")
                f.write("## Rollback Plan\n\n")
                f.write("If critical issues occur:\n\n")
                f.write("1. **Stop the soak test** (Ctrl+C or kill process)\n")
                f.write("2. **Apply rollback config:**\n")
                f.write("   ```bash\n")
                f.write("   cp artifacts/release/FEATURE_FLAGS_SNAPSHOT.json config.rollback.yaml\n")
                f.write("   # Edit config.rollback.yaml: set all enabled=false\n")
                f.write("   python main.py --config config.rollback.yaml\n")
                f.write("   ```\n")
                f.write("3. **Check logs** in `artifacts/edge/feeds/`\n")
                f.write("4. **Review metrics** in Prometheus/Grafana\n\n")
            
            result["artifacts"].append(str(soak_start_path))
            self.log(f"[OK] Soak start instructions: {soak_start_path}")
            
            # Note: We don't actually run the soak test here (24-72h runtime)
            self.log("\n[NOTE] Soak test is NOT started automatically.")
            self.log("[NOTE] Review SOAK_START.md and launch manually.")
            
        except Exception as e:
            result["status"] = "FAIL"
            result["issues"].append(f"Exception: {str(e)}")
            self.log(f"[ERROR] {e}")
        
        finally:
            end_time = datetime.now(timezone.utc)
            result["duration_sec"] = (end_time - start_time).total_seconds()
        
        return result
    
    def generate_finish_line_report(self, step_results: List[Dict]):
        """Generate final FINISH_LINE_REPORT.md."""
        report_path = self.reports_dir / "FINISH_LINE_REPORT.md"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("# FINISH LINE WORKFLOW REPORT\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write("## Executive Summary\n\n")
            
            total_pass = sum(1 for r in step_results if r["status"] == "PASS")
            total_fail = sum(1 for r in step_results if r["status"] == "FAIL")
            
            if total_fail == 0:
                f.write("✅ **Status: ALL STEPS PASSED**\n\n")
            else:
                f.write(f"⚠️ **Status: {total_fail} STEP(S) FAILED**\n\n")
            
            f.write("## Step Results\n\n")
            f.write("| Step | Name | Status | Duration | Artifacts |\n")
            f.write("|------|------|--------|----------|----------|\n")
            
            for r in step_results:
                status_icon = "✅" if r["status"] == "PASS" else "❌"
                duration_str = f"{r['duration_sec']:.1f}s"
                artifact_count = len(r["artifacts"])
                f.write(f"| {r['step']} | {r['name']} | {status_icon} {r['status']} | {duration_str} | {artifact_count} |\n")
            
            f.write("\n## Detailed Results\n\n")
            
            for r in step_results:
                f.write(f"### Step {r['step']}: {r['name']}\n\n")
                f.write(f"**Status:** {'✅' if r['status'] == 'PASS' else '❌'} {r['status']}\n\n")
                f.write(f"**Duration:** {r['duration_sec']:.1f}s\n\n")
                
                if r["artifacts"]:
                    f.write("**Artifacts:**\n")
                    for artifact in r["artifacts"]:
                        f.write(f"- `{artifact}`\n")
                    f.write("\n")
                
                if r["issues"]:
                    f.write("**Issues:**\n")
                    for issue in r["issues"]:
                        f.write(f"- ⚠️ {issue}\n")
                    f.write("\n")
            
            f.write("## Next Steps\n\n")
            f.write("1. Review step results above\n")
            f.write("2. Fix any issues marked with ⚠️\n")
            f.write("3. Continue with subsequent steps\n")
            f.write("4. Monitor soak test if running\n\n")
        
        self.log(f"[OK] Finish line report: {report_path}")
        return report_path


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MEGAPROMPT Workflow Orchestrator")
    parser.add_argument("--step", type=int, help="Run specific step (1-7)")
    parser.add_argument("--all", action="store_true", help="Run all steps (WARNING: very long!)")
    parser.add_argument("--status", action="store_true", help="Check current workflow status")
    parser.add_argument("--shadow-duration", type=int, default=60, help="Shadow test duration in minutes (default: 60)")
    
    args = parser.parse_args()
    
    orchestrator = WorkflowOrchestrator()
    
    # Check prerequisites
    orchestrator.log("Checking prerequisites...")
    ok, issues = orchestrator.check_prerequisites()
    if not ok:
        orchestrator.log("[ERROR] Prerequisites not met:")
        for issue in issues:
            orchestrator.log(f"  - {issue}")
        sys.exit(1)
    
    orchestrator.log("[OK] Prerequisites met")
    
    step_results = []
    
    if args.status:
        orchestrator.log("Checking workflow status...")
        # Check which artifacts exist
        artifacts_to_check = [
            ("FEATURE_FLAGS_SNAPSHOT.json", "artifacts/release/FEATURE_FLAGS_SNAPSHOT.json"),
            ("PREP_LOG.md", "artifacts/reports/PREP_LOG.md"),
            ("stage_budgets.json", "artifacts/baseline/stage_budgets.json"),
            ("shadow_report.md", "artifacts/md_cache/shadow_report.md"),
            ("SOAK_START.md", "artifacts/reports/SOAK_START.md"),
        ]
        
        orchestrator.log("\nArtifact Status:")
        for name, path in artifacts_to_check:
            exists = (orchestrator.project_root / path).exists()
            status = "[OK]" if exists else "[MISSING]"
            orchestrator.log(f"  {status} {name}")
        
        return
    
    if args.step:
        if args.step == 1:
            result = orchestrator.step_1_prep_and_overrides()
            step_results.append(result)
        elif args.step == 2:
            result = orchestrator.step_2_shadow_60m(duration_min=args.shadow_duration)
            step_results.append(result)
        elif args.step == 3:
            result = orchestrator.step_3_soak_instructions()
            step_results.append(result)
        else:
            orchestrator.log(f"[ERROR] Step {args.step} not implemented yet")
            sys.exit(1)
    
    elif args.all:
        orchestrator.log("[WARNING] Running all steps will take 60+ minutes (shadow test)")
        orchestrator.log("[WARNING] Press Ctrl+C within 5 seconds to cancel...")
        import time
        time.sleep(5)
        
        # Run steps sequentially
        step_results.append(orchestrator.step_1_prep_and_overrides())
        
        if step_results[-1]["status"] == "PASS":
            step_results.append(orchestrator.step_2_shadow_60m(duration_min=args.shadow_duration))
        
        if step_results[-1]["status"] == "PASS":
            step_results.append(orchestrator.step_3_soak_instructions())
    
    else:
        parser.print_help()
        sys.exit(1)
    
    # Generate final report
    if step_results:
        orchestrator.generate_finish_line_report(step_results)
        
        # Print summary
        orchestrator.log("\n" + "=" * 60)
        orchestrator.log("WORKFLOW SUMMARY")
        orchestrator.log("=" * 60)
        for r in step_results:
            status = "PASS" if r["status"] == "PASS" else "FAIL"
            orchestrator.log(f"Step {r['step']}: {r['name']} - {status}")
        orchestrator.log("=" * 60)
        
        # Exit with error if any step failed
        if any(r["status"] == "FAIL" for r in step_results):
            sys.exit(1)


if __name__ == "__main__":
    main()

