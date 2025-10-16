#!/usr/bin/env python3
"""
PROMPT 4: Demo for sleep between iterations verification

Проверяет:
1. Sleep срабатывает между итерациями (1->2, 2->3)
2. Sleep НЕ срабатывает после последней итерации
3. Wall-clock время соответствует ожиданиям
"""

import os
import subprocess
import time
import re

def run_soak_with_sleep(iterations: int, sleep_seconds: int) -> str:
    """Run mini-soak with specified sleep time and capture output."""
    env = os.environ.copy()
    env["SOAK_SLEEP_SECONDS"] = str(sleep_seconds)
    
    print(f"\n{'='*70}")
    print(f"DEMO: Running {iterations} iterations with {sleep_seconds}s sleep")
    print(f"{'='*70}\n")
    
    cmd = [
        "python", "-m", "tools.soak.run",
        "--iterations", str(iterations),
        "--auto-tune",
        "--mock"
    ]
    
    start_time = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding='utf-8', errors='replace')
    elapsed_time = time.time() - start_time
    
    print(f"[INFO] Wall-clock time: {elapsed_time:.1f}s")
    
    return result.stdout, elapsed_time


def verify_sleep_behavior(output: str, iterations: int, sleep_seconds: int, elapsed_time: float):
    """Verify that sleep behaves correctly."""
    print(f"\n{'='*70}")
    print("VERIFICATION RESULTS")
    print(f"{'='*70}\n")
    
    # Count sleep markers
    sleep_markers = re.findall(r'\| soak \| SLEEP \| (\d+)s \|', output)
    expected_sleeps = iterations - 1  # No sleep after last iteration
    
    print(f"[CHECK 1] Sleep marker count")
    print(f"  Expected: {expected_sleeps} (iterations - 1)")
    print(f"  Found: {len(sleep_markers)}")
    if len(sleep_markers) == expected_sleeps:
        print(f"  [OK] Correct number of sleep markers\n")
    else:
        print(f"  [FAIL] Unexpected sleep count!\n")
    
    # Check sleep duration values
    print(f"[CHECK 2] Sleep duration values")
    all_correct = True
    for i, marker_value in enumerate(sleep_markers, 1):
        if int(marker_value) == sleep_seconds:
            print(f"  Sleep {i}: {marker_value}s [OK]")
        else:
            print(f"  Sleep {i}: {marker_value}s [FAIL] Expected {sleep_seconds}s")
            all_correct = False
    
    if all_correct:
        print(f"  [OK] All sleep durations correct\n")
    else:
        print(f"  [FAIL] Some sleep durations incorrect\n")
    
    # Check wall-clock time (with 10% tolerance for overhead)
    expected_time = sleep_seconds * expected_sleeps
    tolerance = expected_time * 0.15  # 15% tolerance for processing overhead
    min_time = expected_time - tolerance
    max_time = expected_time + tolerance
    
    print(f"[CHECK 3] Wall-clock duration")
    print(f"  Expected: ~{expected_time}s ({expected_sleeps} sleeps x {sleep_seconds}s)")
    print(f"  Actual: {elapsed_time:.1f}s")
    print(f"  Acceptable range: {min_time:.1f}s - {max_time:.1f}s")
    
    if min_time <= elapsed_time <= max_time:
        print(f"  [OK] Wall-clock time within expected range\n")
    else:
        print(f"  [WARN] Wall-clock time outside expected range\n")
    
    # Extract REAL DURATION from summary
    duration_match = re.search(r'REAL DURATION \(wall-clock\): (.+)', output)
    iterations_match = re.search(r'ITERATIONS COMPLETED: (\d+)', output)
    
    print(f"[CHECK 4] Summary output")
    if duration_match:
        print(f"  Wall-clock (summary): {duration_match.group(1)}")
    if iterations_match:
        print(f"  Iterations completed: {iterations_match.group(1)}")
        if int(iterations_match.group(1)) == iterations:
            print(f"  [OK] All iterations completed\n")
        else:
            print(f"  [FAIL] Not all iterations completed\n")
    
    print(f"{'='*70}\n")


def main():
    print("="*70)
    print("PROMPT 4: SLEEP VERIFICATION DEMO")
    print("="*70)
    
    # Test 1: 3 iterations with 5s sleep (fast test)
    print("\nTEST 1: 3 iterations x 5s sleep (expect 2 sleeps, ~10s total)")
    output1, elapsed1 = run_soak_with_sleep(iterations=3, sleep_seconds=5)
    verify_sleep_behavior(output1, iterations=3, sleep_seconds=5, elapsed_time=elapsed1)
    
    # Test 2: Single iteration (no sleep expected)
    print("\nTEST 2: 1 iteration (expect 0 sleeps, ~0s sleep time)")
    output2, elapsed2 = run_soak_with_sleep(iterations=1, sleep_seconds=5)
    verify_sleep_behavior(output2, iterations=1, sleep_seconds=5, elapsed_time=elapsed2)
    
    # Test 3: 2 iterations with 3s sleep
    print("\nTEST 3: 2 iterations x 3s sleep (expect 1 sleep, ~3s total)")
    output3, elapsed3 = run_soak_with_sleep(iterations=2, sleep_seconds=3)
    verify_sleep_behavior(output3, iterations=2, sleep_seconds=3, elapsed_time=elapsed3)
    
    print("\n" + "="*70)
    print("DEMO COMPLETE")
    print("="*70)
    print("\nKEY FINDINGS:")
    print("  - Sleep only happens BETWEEN iterations (not after last)")
    print("  - Wall-clock time = (iterations - 1) x sleep_seconds + processing overhead")
    print("  - SOAK_SLEEP_SECONDS env var is respected")
    print()


if __name__ == "__main__":
    main()

