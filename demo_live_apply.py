#!/usr/bin/env python3
"""
DEMO: Live-Apply Mechanism for Iteration Tuning Deltas

This script demonstrates the new live-apply feature where tuning recommendations
from iter_watcher are actually applied between iterations (not just recorded).

Run:
    python demo_live_apply.py

Expected behavior:
    - 3 iterations with mock data
    - Each iteration generates tuning deltas
    - Deltas are applied to runtime_overrides.json
    - ITER_SUMMARY_*.json marked with applied=true
    - Diff shown for first 2 iterations
"""

import subprocess
import sys
from pathlib import Path


def main():
    print("="*70)
    print("DEMO: Live-Apply Mechanism for Iteration Tuning Deltas")
    print("="*70)
    print()
    
    print("Running mini-soak with 3 iterations in mock mode...")
    print("(auto-tuning enabled, live-apply enabled)")
    print()
    
    # Clean up previous artifacts
    artifacts_dir = Path("artifacts/soak/latest")
    if artifacts_dir.exists():
        import shutil
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        print("[CLEANUP] Removed previous artifacts/soak/latest/")
    
    overrides_file = Path("artifacts/soak/runtime_overrides.json")
    if overrides_file.exists():
        overrides_file.unlink()
        print("[CLEANUP] Removed previous runtime_overrides.json")
    
    print()
    
    # Run mini-soak with auto-tuning
    cmd = [
        sys.executable,
        "-m",
        "tools.soak.run",
        "--iterations", "3",
        "--auto-tune",
        "--mock"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    print()
    print("-"*70)
    
    result = subprocess.run(cmd, capture_output=False, text=True)
    
    print("-"*70)
    print()
    
    if result.returncode != 0:
        print(f"[FAIL] Mini-soak failed with exit code {result.returncode}")
        return 1
    
    print("[OK] Mini-soak completed successfully!")
    print()
    
    # Verify artifacts were created
    print("="*70)
    print("VERIFICATION: Checking Generated Artifacts")
    print("="*70)
    print()
    
    expected_files = [
        "artifacts/soak/runtime_overrides.json",
        "artifacts/soak/latest/ITER_SUMMARY_1.json",
        "artifacts/soak/latest/ITER_SUMMARY_2.json",
        "artifacts/soak/latest/ITER_SUMMARY_3.json",
        "artifacts/soak/latest/TUNING_REPORT.json",
    ]
    
    all_present = True
    for file_path in expected_files:
        path = Path(file_path)
        if path.exists():
            size = path.stat().st_size
            print(f"[+] {file_path} ({size} bytes)")
        else:
            print(f"[-] {file_path} MISSING")
            all_present = False
    
    print()
    
    if not all_present:
        print("[FAIL] Some expected artifacts are missing")
        return 1
    
    # Check if applied flag was set
    print("="*70)
    print("VERIFICATION: Checking 'applied' Flag in ITER_SUMMARY Files")
    print("="*70)
    print()
    
    import json
    
    for i in range(1, 4):
        iter_summary_path = Path(f"artifacts/soak/latest/ITER_SUMMARY_{i}.json")
        if iter_summary_path.exists():
            with open(iter_summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tuning = data.get("tuning", {})
            deltas = tuning.get("deltas", {})
            applied = tuning.get("applied", False)
            
            status = "[+] APPLIED" if applied else "[-] NOT APPLIED"
            delta_count = len(deltas)
            
            print(f"Iteration {i}: {status} (deltas: {delta_count})")
            
            if deltas and not applied:
                print(f"  [WARN] Deltas present but not applied!")
                print(f"     Deltas: {deltas}")
        else:
            print(f"Iteration {i}: [-] FILE MISSING")
    
    print()
    
    # Show final runtime_overrides.json
    print("="*70)
    print("FINAL STATE: runtime_overrides.json")
    print("="*70)
    print()
    
    overrides_path = Path("artifacts/soak/runtime_overrides.json")
    if overrides_path.exists():
        with open(overrides_path, 'r', encoding='utf-8') as f:
            overrides = json.load(f)
        
        print(json.dumps(overrides, indent=2, sort_keys=True))
    else:
        print("[-] runtime_overrides.json not found")
    
    print()
    print("="*70)
    print("[OK] DEMO COMPLETE")
    print("="*70)
    print()
    print("Key takeaways:")
    print("  1. Tuning deltas are now APPLIED (not just recorded)")
    print("  2. runtime_overrides.json evolves between iterations")
    print("  3. ITER_SUMMARY_*.json shows applied=true when deltas are applied")
    print("  4. Strict bounds prevent unsafe parameter values")
    print("  5. Self-check diff shown for first 2 iterations")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

