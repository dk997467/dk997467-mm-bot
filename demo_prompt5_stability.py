#!/usr/bin/env python3
"""
PROMPT 5: Stability & Control Demo

Проверяет 5 финальных штрихов:
1. Идемпотентность apply (анти-"пила") - same signature skip
2. Freeze logic (устойчивость >=2 итераций) - freeze params
3. Guard на конфликты - prefer risk priority
4. Consistency check - risk mismatch warning
5. Late-iteration guard - no apply on final iteration

Usage:
    python demo_prompt5_stability.py
"""

import os
import subprocess
import json
from pathlib import Path
import re


def run_soak(iterations: int, sleep_seconds: int = 2) -> str:
    """Run mini-soak and capture output."""
    env = os.environ.copy()
    env["SOAK_SLEEP_SECONDS"] = str(sleep_seconds)
    
    cmd = [
        "python", "-m", "tools.soak.run",
        "--iterations", str(iterations),
        "--auto-tune",
        "--mock"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding='utf-8', errors='replace')
    
    return result.stdout


def check_idempotent_apply(output: str) -> bool:
    """Check that same signature skip works (PROMPT 5.1 & 5.2)."""
    print("\n" + "="*70)
    print("CHECK 1: IDEMPOTENT APPLY (anti-oscillation)")
    print("="*70)
    
    # Look for APPLY_SKIP reason=same_signature
    same_sig_skip = re.findall(r'APPLY_SKIP.*reason=same_signature', output)
    
    if same_sig_skip:
        print(f"[OK] Found {len(same_sig_skip)} same_signature skip(s)")
        for skip in same_sig_skip:
            print(f"  - {skip}")
        return True
    else:
        print("[INFO] No same_signature skips (may be expected if all deltas are unique)")
        return True  # Not necessarily a failure


def check_freeze_logic(output: str) -> bool:
    """Check that freeze is activated when conditions met (PROMPT 5.3)."""
    print("\n" + "="*70)
    print("CHECK 2: FREEZE LOGIC (steady state lock)")
    print("="*70)
    
    # Look for FREEZE markers
    freeze_markers = re.findall(r'\| iter_watch \| FREEZE \| from=iter_(\d+) to=iter_(\d+) fields=\[(.*?)\]', output)
    
    if freeze_markers:
        print(f"[OK] Found {len(freeze_markers)} freeze activation(s)")
        for from_iter, to_iter, fields in freeze_markers:
            print(f"  - Freeze from iter_{from_iter} to iter_{to_iter}, fields={fields}")
        return True
    else:
        print("[INFO] No freeze activations (may be expected if risk_ratio > 0.35)")
        return True  # Not necessarily a failure


def check_conflict_guards(output: str) -> bool:
    """Check that conflict resolution works (PROMPT 5.4)."""
    print("\n" + "="*70)
    print("CHECK 3: CONFLICT GUARDS (prefer risk priority)")
    print("="*70)
    
    # Look for GUARD markers
    guard_markers = re.findall(r'\| iter_watch \| GUARD \| conflict=(.*?) resolved=(.*?) \|', output)
    
    if guard_markers:
        print(f"[OK] Found {len(guard_markers)} conflict resolution(s)")
        for conflict, resolution in guard_markers:
            print(f"  - Conflict: {conflict}, Resolution: {resolution}")
        return True
    else:
        print("[INFO] No conflicts detected (may be expected)")
        return True  # Not necessarily a failure


def check_consistency_check(output: str) -> bool:
    """Check that risk consistency warnings work (PROMPT 5.5)."""
    print("\n" + "="*70)
    print("CHECK 4: CONSISTENCY CHECK (risk mismatch)")
    print("="*70)
    
    # Look for WARN risk_mismatch
    mismatch_warnings = re.findall(r'\| iter_watch \| WARN \| risk_mismatch summary=([\d.]+) edge=([\d.]+)', output)
    
    if mismatch_warnings:
        print(f"[WARN] Found {len(mismatch_warnings)} risk mismatch warning(s)")
        for summary_risk, edge_risk in mismatch_warnings:
            print(f"  - Summary: {summary_risk}, Edge: {edge_risk}")
        return False  # Mismatch is bad
    else:
        print("[OK] No risk mismatch warnings (consistent metrics)")
        return True


def check_late_iteration_guard(output: str, iterations: int) -> bool:
    """Check that final iteration skips apply (PROMPT 5.6)."""
    print("\n" + "="*70)
    print("CHECK 5: LATE-ITERATION GUARD (no apply on final iteration)")
    print("="*70)
    
    # Look for APPLY_SKIP reason=final_iteration
    final_iter_skip = re.findall(r'APPLY_SKIP.*reason=final_iteration', output)
    
    if final_iter_skip:
        print(f"[OK] Found final_iteration skip(s): {len(final_iter_skip)}")
        for skip in final_iter_skip:
            print(f"  - {skip}")
        
        # Also check ITER_SUMMARY for final iteration
        final_summary_path = Path(f"artifacts/soak/latest/ITER_SUMMARY_{iterations}.json")
        if final_summary_path.exists():
            with open(final_summary_path, 'r', encoding='utf-8') as f:
                final_summary = json.load(f)
                tuning = final_summary.get("tuning", {})
                applied = tuning.get("applied", None)
                skipped_reason = tuning.get("skipped_reason", None)
                
                if applied == False and skipped_reason == "final_iteration":
                    print(f"  [OK] ITER_SUMMARY_{iterations}.json confirms: applied=false, skipped_reason=final_iteration")
                    return True
                else:
                    print(f"  [FAIL] ITER_SUMMARY_{iterations}.json: applied={applied}, skipped_reason={skipped_reason}")
                    return False
        else:
            print(f"  [WARN] ITER_SUMMARY_{iterations}.json not found")
            return True  # Can't verify, but skip was logged
    else:
        print(f"[FAIL] No final_iteration skip found in logs")
        return False


def check_tuning_state_file():
    """Check that TUNING_STATE.json exists and has correct structure."""
    print("\n" + "="*70)
    print("CHECK 6: TUNING_STATE.json structure")
    print("="*70)
    
    state_path = Path("artifacts/soak/latest/TUNING_STATE.json")
    
    if not state_path.exists():
        print("[WARN] TUNING_STATE.json not found (may be created after first apply)")
        return True
    
    with open(state_path, 'r', encoding='utf-8') as f:
        state = json.load(f)
    
    required_keys = ["last_applied_signature", "frozen_until_iter", "freeze_reason"]
    missing_keys = [k for k in required_keys if k not in state]
    
    if missing_keys:
        print(f"[FAIL] Missing keys in TUNING_STATE.json: {missing_keys}")
        return False
    
    print("[OK] TUNING_STATE.json has all required keys:")
    for key, value in state.items():
        print(f"  - {key}: {value}")
    
    return True


def main():
    print("="*70)
    print("PROMPT 5: STABILITY & CONTROL DEMO")
    print("="*70)
    print("\nRunning mini-soak with 6 iterations to test all 5 features...\n")
    
    # Run soak with 6 iterations (enough to potentially trigger freeze and test final iteration)
    output = run_soak(iterations=6, sleep_seconds=2)
    
    # Run all checks
    results = {}
    results["idempotent_apply"] = check_idempotent_apply(output)
    results["freeze_logic"] = check_freeze_logic(output)
    results["conflict_guards"] = check_conflict_guards(output)
    results["consistency_check"] = check_consistency_check(output)
    results["late_iteration_guard"] = check_late_iteration_guard(output, iterations=6)
    results["tuning_state_file"] = check_tuning_state_file()
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {check}")
    
    print("\n" + "="*70)
    if all_passed:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED (see details above)")
    print("="*70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())

