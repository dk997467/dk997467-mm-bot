#!/usr/bin/env python3
"""
Tag & Canary Release Script.

Creates annotated git tag with KPI summary and generates canary deployment checklist.

Usage:
    python -m tools.release.tag_and_canary --bundle release/soak-ci-chaos-release-toolkit
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional


def load_snapshot(bundle_dir: Path) -> Optional[Dict[str, Any]]:
    """Load POST_SOAK_SNAPSHOT.json from bundle."""
    snapshot_path = bundle_dir / "POST_SOAK_SNAPSHOT.json"
    
    if not snapshot_path.exists():
        print(f"[ERROR] Snapshot not found: {snapshot_path}", file=sys.stderr)
        return None
    
    try:
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load snapshot: {e}", file=sys.stderr)
        return None


def generate_tag_message(snapshot: Dict[str, Any]) -> str:
    """Generate annotated tag message with KPI summary."""
    lines = []
    
    # Header
    lines.append("Soak-Validated Release: Auto-Tuning Stability Suite")
    lines.append("")
    lines.append(f"Verdict: {snapshot.get('verdict', 'UNKNOWN')}")
    lines.append(f"Freeze Ready: {snapshot.get('freeze_ready', False)}")
    lines.append(f"Generated: {snapshot.get('timestamp', 'Unknown')}")
    lines.append("")
    
    # KPI Summary (Last-N)
    kpi = snapshot.get('kpi_last_n', {})
    iter_range = snapshot.get('iterations_analyzed', [])
    
    if iter_range:
        lines.append(f"KPI Summary (Iterations {min(iter_range)}-{max(iter_range)}):")
    else:
        lines.append("KPI Summary:")
    
    lines.append("")
    
    # Key metrics
    for metric_name in ['maker_taker_ratio', 'p95_latency_ms', 'risk_ratio', 'net_bps']:
        if metric_name in kpi:
            stats = kpi[metric_name]
            lines.append(f"  {metric_name}: mean={stats.get('mean', 0):.3f}, trend={stats.get('trend', 'flat')}")
    
    lines.append("")
    
    # Goals
    goals = snapshot.get('goals_met', {})
    lines.append("Goals:")
    for goal_name, goal_met in goals.items():
        status = "[OK]" if goal_met else "[FAIL]"
        lines.append(f"  {status} {goal_name}")
    
    lines.append("")
    
    # Delta application
    tuning = snapshot.get('tuning_summary', {})
    lines.append(f"Delta Application: {tuning.get('applied_count', 0)} times")
    
    # Guard activity
    guards = snapshot.get('guards_last_n', {})
    guard_counts = guards.get('counts', {})
    active_guards = [k for k, v in guard_counts.items() if v > 0]
    
    if active_guards:
        lines.append(f"Active Guards: {', '.join(active_guards)}")
    else:
        lines.append("Active Guards: None (stable)")
    
    lines.append("")
    lines.append("Bundle: release/soak-ci-chaos-release-toolkit/")
    
    return '\n'.join(lines)


def create_tag(tag_name: str, message: str, dry_run: bool = False) -> bool:
    """Create annotated git tag."""
    try:
        if dry_run:
            print(f"[DRY-RUN] Would create tag: {tag_name}")
            print("Message:")
            print(message)
            return True
        
        # Check if tag already exists
        result = subprocess.run(
            ['git', 'tag', '-l', tag_name],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.stdout.strip():
            print(f"[WARN] Tag {tag_name} already exists", file=sys.stderr)
            response = input("Overwrite? [y/N]: ")
            if response.lower() != 'y':
                print("[INFO] Skipping tag creation")
                return False
            
            # Delete existing tag
            subprocess.run(['git', 'tag', '-d', tag_name], check=True)
        
        # Create annotated tag
        subprocess.run(
            ['git', 'tag', '-a', tag_name, '-m', message],
            check=True
        )
        
        print(f"[OK] Created tag: {tag_name}")
        return True
    
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to create tag: {e}", file=sys.stderr)
        return False


def generate_canary_checklist(bundle_dir: Path, snapshot: Dict[str, Any]) -> bool:
    """Generate canary deployment checklist."""
    checklist_path = bundle_dir / "CANARY_CHECKLIST.md"
    
    try:
        lines = []
        
        # Header
        lines.append("# Canary Deployment Checklist")
        lines.append("")
        lines.append(f"**Version:** v1.0.0-soak-validated")
        lines.append(f"**Status:** {snapshot.get('verdict', 'UNKNOWN')}")
        lines.append(f"**Freeze Ready:** {snapshot.get('freeze_ready', False)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Pre-Deployment
        lines.append("## Pre-Deployment")
        lines.append("")
        lines.append("- [ ] Review POST_SOAK_AUDIT.md")
        lines.append("- [ ] Review RECOMMENDATIONS.md")
        lines.append("- [ ] Verify DELTA_VERIFY_REPORT.json (full_apply_ratio >= 0.95)")
        lines.append("- [ ] Backup current runtime_overrides.json")
        lines.append("- [ ] Notify #trading-ops channel")
        lines.append("- [ ] Verify rollback plan ready (rollback_plan.md)")
        lines.append("")
        
        # Canary Deployment
        lines.append("## Canary Deployment (5% Traffic)")
        lines.append("")
        lines.append("### Step 1: Deploy Canary")
        lines.append("")
        lines.append("```bash")
        lines.append("# Update canary config")
        lines.append("cp release/soak-ci-chaos-release-toolkit/soak_profile.runtime_overrides.json \\")
        lines.append("   config/runtime_overrides.canary.json")
        lines.append("")
        lines.append("# Deploy canary pod")
        lines.append("kubectl apply -f k8s/mm-bot-canary.yaml")
        lines.append("")
        lines.append("# Update traffic split (5% canary)")
        lines.append("kubectl patch virtualservice mm-bot --type merge -p '")
        lines.append('  {"spec":{"http":[{')
        lines.append('    "route":[')
        lines.append('      {"destination":{"host":"mm-bot-stable"},"weight":95},')
        lines.append('      {"destination":{"host":"mm-bot-canary"},"weight":5}')
        lines.append('    ]')
        lines.append('  }]}}"')
        lines.append("```")
        lines.append("")
        
        # Monitoring
        lines.append("### Step 2: Monitor Canary (24-48h)")
        lines.append("")
        lines.append("**Watch Grafana Dashboard:** `mm-bot-canary-metrics`")
        lines.append("")
        lines.append("#### Hour 1: Critical Stability")
        lines.append("")
        lines.append("- [ ] No errors in logs")
        lines.append("- [ ] Maker/taker ratio >= 0.75")
        lines.append("- [ ] P95 latency <= 400ms")
        lines.append("- [ ] Risk ratio <= 0.50")
        lines.append("")
        
        lines.append("#### Hour 6: Performance Verification")
        lines.append("")
        lines.append("- [ ] Maker/taker ratio >= 0.80")
        lines.append("- [ ] P95 latency <= 350ms")
        lines.append("- [ ] Risk ratio <= 0.45")
        lines.append("- [ ] Net BPS positive")
        lines.append("")
        
        lines.append("#### Hour 24: Target KPIs")
        lines.append("")
        kpi = snapshot.get('kpi_last_n', {})
        
        lines.append(f"- [ ] Maker/taker ratio >= {kpi.get('maker_taker_ratio', {}).get('mean', 0.83):.2f}")
        lines.append(f"- [ ] P95 latency <= {kpi.get('p95_latency_ms', {}).get('max', 340):.0f}ms")
        lines.append(f"- [ ] Risk ratio <= {kpi.get('risk_ratio', {}).get('median', 0.40):.2f}")
        lines.append(f"- [ ] Net BPS >= {kpi.get('net_bps', {}).get('mean', 2.5):.1f}")
        lines.append("")
        
        # Auto-Rollback Triggers
        lines.append("### Step 3: Auto-Rollback Triggers")
        lines.append("")
        lines.append("**Immediately rollback if:**")
        lines.append("")
        lines.append("| Metric | Trigger | Duration |")
        lines.append("|--------|---------|----------|")
        lines.append("| Maker/Taker | < 0.70 | 5 min |")
        lines.append("| P95 Latency | > 500ms | 3 min |")
        lines.append("| Risk Ratio | > 0.60 | 2 min |")
        lines.append("| Error Rate | > 5% | 1 min |")
        lines.append("")
        
        lines.append("**Rollback command:**")
        lines.append("```bash")
        lines.append("# Scale down canary")
        lines.append("kubectl scale deployment mm-bot-canary --replicas=0")
        lines.append("")
        lines.append("# Restore 100% stable traffic")
        lines.append("kubectl patch virtualservice mm-bot --type merge -p '")
        lines.append('  {"spec":{"http":[{')
        lines.append('    "route":[{"destination":{"host":"mm-bot-stable"},"weight":100}]')
        lines.append('  }]}}"')
        lines.append("```")
        lines.append("")
        
        # Full Rollout
        lines.append("### Step 4: Full Rollout (after 24-48h)")
        lines.append("")
        lines.append("If canary stable:")
        lines.append("")
        lines.append("- [ ] Increase traffic to 25%")
        lines.append("- [ ] Monitor for 12h")
        lines.append("- [ ] Increase traffic to 50%")
        lines.append("- [ ] Monitor for 6h")
        lines.append("- [ ] Full rollout (100%)")
        lines.append("- [ ] Decommission old stable pods")
        lines.append("")
        
        # Post-Deployment
        lines.append("## Post-Deployment")
        lines.append("")
        lines.append("- [ ] Update production tag")
        lines.append("- [ ] Archive release bundle")
        lines.append("- [ ] Update runbook with new KPI baselines")
        lines.append("- [ ] Notify stakeholders")
        lines.append("- [ ] Schedule post-mortem (if issues)")
        lines.append("")
        
        # Sign-Off
        lines.append("---")
        lines.append("")
        lines.append("## Sign-Off")
        lines.append("")
        lines.append("**Deployed by:** _________________")
        lines.append("")
        lines.append("**Date:** _________________")
        lines.append("")
        lines.append("**Rollback ready:** [ ] Yes [ ] No")
        lines.append("")
        
        # Write file
        with open(checklist_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] Generated canary checklist: {checklist_path}")
        return True
    
    except Exception as e:
        print(f"[ERROR] Failed to generate canary checklist: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Create release tag and canary deployment checklist",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--bundle",
        type=str,
        required=True,
        help="Release bundle directory"
    )
    parser.add_argument(
        "--tag",
        type=str,
        default="v1.0.0-soak-validated",
        help="Git tag name (default: v1.0.0-soak-validated)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually create tag, just show message"
    )
    
    args = parser.parse_args()
    
    bundle_dir = Path(args.bundle).resolve()
    
    print("=" * 80)
    print("TAG & CANARY RELEASE SCRIPT")
    print("=" * 80)
    print(f"Bundle: {bundle_dir}")
    print(f"Tag: {args.tag}")
    print(f"Dry run: {args.dry_run}")
    print()
    
    # Load snapshot
    print("[1/3] Loading snapshot...")
    snapshot = load_snapshot(bundle_dir)
    
    if not snapshot:
        return 1
    
    # Generate tag message
    print("[2/3] Generating tag message...")
    tag_message = generate_tag_message(snapshot)
    
    # Create tag
    print(f"[2/3] Creating tag: {args.tag}...")
    if not create_tag(args.tag, tag_message, dry_run=args.dry_run):
        print("[WARN] Tag creation skipped or failed")
    
    # Generate canary checklist
    print("[3/3] Generating canary checklist...")
    if not generate_canary_checklist(bundle_dir, snapshot):
        return 1
    
    print()
    print("=" * 80)
    print("TAG & CANARY RELEASE COMPLETE")
    print("=" * 80)
    print()
    
    if args.dry_run:
        print("[INFO] This was a dry run. No tag was created.")
        print()
    else:
        print(f"[OK] Tag created: {args.tag}")
        print()
        print("To push tag to remote:")
        print(f"  git push origin {args.tag}")
        print()
    
    print("Canary checklist: {}".format(bundle_dir / "CANARY_CHECKLIST.md"))
    print()
    
    # Print verdict
    if snapshot.get('freeze_ready'):
        print("[OK] READY FOR CANARY DEPLOYMENT")
    else:
        print("[WARN] Review RECOMMENDATIONS.md before deploying")
    
    print("=" * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())

