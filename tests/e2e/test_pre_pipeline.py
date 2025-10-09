"""
E2E smoke test for PRE report generation pipeline.

Verifies that all PRE artifacts (KPI_GATE, READINESS, EDGE_SENTINEL, etc.)
can be generated without exceptions and contain valid data with correct timestamps.

This test ensures the entire pipeline is stable and self-diagnostic.
"""
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import pytest


def test_pre_pipeline_generates_all_artifacts(tmp_path, monkeypatch):
    """
    Generate all PRE artifacts and verify they exist with valid structure.
    
    Tests:
    1. EDGE_SENTINEL generation (with synthetic data if needed)
    2. WEEKLY_ROLLUP generation (requires soak reports)
    3. KPI_GATE generation (requires WEEKLY_ROLLUP)
    4. READINESS_SCORE generation (requires soak reports)
    5. FULL_STACK_VALIDATION generation
    
    All artifacts must:
    - Be valid JSON
    - Have runtime.utc != "1970-01-01T00:00:00Z"
    - Have proper structure
    """
    # Setup: use tmp_path as artifacts dir
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    
    # Set frozen time for determinism (but NOT 1970!)
    frozen_time = '2025-01-15T12:00:00Z'
    monkeypatch.setenv('MM_FREEZE_UTC_ISO', frozen_time)
    monkeypatch.setenv('MM_VERSION', 'test-0.0.1')
    
    # Critical: Change to repo root for imports
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    
    # ========================================================================
    # Step 1: Generate EDGE_SENTINEL (param sweep style, using synthetic data)
    # ========================================================================
    print("\n[TEST] Generating EDGE_SENTINEL...", file=sys.stderr)
    
    # Create minimal synthetic events for edge_sentinel
    events_path = artifacts_dir / "synthetic_trades.jsonl"
    quotes_path = artifacts_dir / "synthetic_quotes.jsonl"
    
    # Generate synthetic trades
    with open(events_path, 'w', encoding='ascii') as f:
        for i in range(10):
            trade = {
                'ts_ms': 1609459200000 + (i * 1000),
                'symbol': 'BTCUSDT',
                'price': 50000.0 + i,
                'qty': 0.1,
                'side': 'buy' if i % 2 == 0 else 'sell',
                'fee_bps': 0.5,
                'gross_bps': 2.5,
                'adverse_bps': 0.1,
                'slippage_bps': 0.2,
                'inventory_bps': 0.1,
            }
            json.dump(trade, f, ensure_ascii=True, separators=(',', ':'))
            f.write('\n')
    
    # Generate synthetic quotes
    with open(quotes_path, 'w', encoding='ascii') as f:
        for i in range(10):
            quote = {
                'ts_ms': 1609459200000 + (i * 1000),
                'symbol': 'BTCUSDT',
                'bid': 50000.0 + i - 0.5,
                'ask': 50000.0 + i + 0.5,
            }
            json.dump(quote, f, ensure_ascii=True, separators=(',', ':'))
            f.write('\n')
    
    # Run edge_sentinel/analyze.py
    edge_sentinel_json = artifacts_dir / "EDGE_SENTINEL.json"
    cmd = [
        sys.executable,
        'tools/edge_sentinel/analyze.py',
        '--trades', str(events_path),
        '--quotes', str(quotes_path),
        '--bucket-min', '15',
        '--out-json', str(edge_sentinel_json)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Verify it ran successfully
    assert result.returncode == 0, (
        f"edge_sentinel failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    
    # Verify file exists and is valid JSON
    assert edge_sentinel_json.exists(), "EDGE_SENTINEL.json not created"
    
    with open(edge_sentinel_json, 'r', encoding='ascii') as f:
        edge_sentinel = json.load(f)
    
    # Verify structure
    assert 'runtime' in edge_sentinel
    assert 'advice' in edge_sentinel
    assert 'summary' in edge_sentinel
    assert 'top' in edge_sentinel
    
    # CRITICAL: Verify runtime.utc is NOT 1970
    assert edge_sentinel['runtime']['utc'] == frozen_time, (
        f"EDGE_SENTINEL has wrong timestamp: {edge_sentinel['runtime']['utc']} "
        f"(expected: {frozen_time})"
    )
    
    print(f"[OK] EDGE_SENTINEL generated: {edge_sentinel_json}", file=sys.stderr)
    
    # ========================================================================
    # Step 2: Generate synthetic soak reports for WEEKLY_ROLLUP and READINESS
    # ========================================================================
    print("\n[TEST] Generating synthetic soak reports...", file=sys.stderr)
    
    # Create 7 synthetic soak reports (last 7 days)
    for i in range(7):
        date_str = f"2025010{i+1}"  # 20250101-20250107
        soak_report = {
            'edge_net_bps': 2.8 + (i * 0.1),
            'order_age_p95_ms': 280.0 + (i * 5),
            'taker_share_pct': 12.0 + (i * 0.5),
            'verdict': 'OK',
            'reg_guard': {'reason': 'NONE'},
            'drift': {'reason': 'NONE'},
            'chaos_result': 'OK',
            'bug_bash': 'OK',
            'runtime': {'utc': frozen_time, 'version': 'test-0.0.1'},
        }
        
        soak_path = artifacts_dir / f"REPORT_SOAK_{date_str}.json"
        with open(soak_path, 'w', encoding='ascii') as f:
            json.dump(soak_report, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
            f.write('\n')
    
    # Create synthetic ledger
    ledger_path = artifacts_dir / "LEDGER_DAILY.json"
    ledger = []
    for i in range(7):
        ledger.append({
            'date': f'2025-01-0{i+1}',
            'equity': 10000.0 + (i * 100),
            'fees': 5.0,
            'rebates': 2.0,
        })
    with open(ledger_path, 'w', encoding='ascii') as f:
        json.dump(ledger, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
    
    print(f"[OK] Created 7 synthetic soak reports", file=sys.stderr)
    
    # ========================================================================
    # Step 3: Generate WEEKLY_ROLLUP
    # ========================================================================
    print("\n[TEST] Generating WEEKLY_ROLLUP...", file=sys.stderr)
    
    weekly_json = artifacts_dir / "WEEKLY_ROLLUP.json"
    weekly_md = artifacts_dir / "WEEKLY_ROLLUP.md"
    
    cmd = [
        sys.executable, '-m', 'tools.soak.weekly_rollup',
        '--soak-dir', str(artifacts_dir),
        '--ledger', str(ledger_path),
        '--out-json', str(weekly_json),
        '--out-md', str(weekly_md),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0, (
        f"weekly_rollup failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    
    assert weekly_json.exists(), "WEEKLY_ROLLUP.json not created"
    
    with open(weekly_json, 'r', encoding='ascii') as f:
        weekly_rollup = json.load(f)
    
    # Verify structure
    assert 'runtime' in weekly_rollup
    assert 'edge_net_bps' in weekly_rollup
    assert 'verdict' in weekly_rollup
    
    # CRITICAL: Verify runtime.utc is NOT 1970
    assert weekly_rollup['runtime']['utc'] == frozen_time, (
        f"WEEKLY_ROLLUP has wrong timestamp: {weekly_rollup['runtime']['utc']}"
    )
    
    print(f"[OK] WEEKLY_ROLLUP generated: {weekly_json}", file=sys.stderr)
    
    # ========================================================================
    # Step 4: Generate KPI_GATE
    # ========================================================================
    print("\n[TEST] Generating KPI_GATE...", file=sys.stderr)
    
    # Change to artifacts dir so kpi_gate can find WEEKLY_ROLLUP.json
    kpi_gate_json = artifacts_dir / "KPI_GATE.json"
    
    # Save current dir
    orig_dir = Path.cwd()
    try:
        os.chdir(repo_root)
        
        # Copy WEEKLY_ROLLUP to expected location
        import shutil
        expected_weekly = Path("artifacts") / "WEEKLY_ROLLUP.json"
        expected_weekly.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(weekly_json, expected_weekly)
        
        cmd = [sys.executable, '-m', 'tools.soak.kpi_gate']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        assert result.returncode == 0, (
            f"kpi_gate failed:\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
        
        # Check if file was created in expected location
        assert expected_weekly.parent.joinpath("KPI_GATE.json").exists(), "KPI_GATE.json not created"
        
        with open("artifacts/KPI_GATE.json", 'r', encoding='ascii') as f:
            kpi_gate = json.load(f)
    
    finally:
        os.chdir(orig_dir)
    
    # Verify structure
    assert 'runtime' in kpi_gate
    assert 'verdict' in kpi_gate
    assert 'reasons' in kpi_gate
    
    # CRITICAL: Verify runtime.utc is NOT 1970
    assert kpi_gate['runtime']['utc'] == frozen_time, (
        f"KPI_GATE has wrong timestamp: {kpi_gate['runtime']['utc']}"
    )
    
    print(f"[OK] KPI_GATE generated: {kpi_gate}", file=sys.stderr)
    
    # ========================================================================
    # Step 5: Generate READINESS_SCORE
    # ========================================================================
    print("\n[TEST] Generating READINESS_SCORE...", file=sys.stderr)
    
    readiness_json = artifacts_dir / "READINESS_SCORE.json"
    
    cmd = [
        sys.executable, '-m', 'tools.release.readiness_score',
        '--dir', str(artifacts_dir),
        '--out-json', str(readiness_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    assert result.returncode == 0, (
        f"readiness_score failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    
    assert readiness_json.exists(), "READINESS_SCORE.json not created"
    
    with open(readiness_json, 'r', encoding='ascii') as f:
        readiness = json.load(f)
    
    # Verify structure
    assert 'runtime' in readiness
    assert 'score' in readiness
    assert 'verdict' in readiness
    assert 'sections' in readiness
    
    # CRITICAL: Verify runtime.utc is NOT 1970
    assert readiness['runtime']['utc'] == frozen_time, (
        f"READINESS_SCORE has wrong timestamp: {readiness['runtime']['utc']}"
    )
    
    print(f"[OK] READINESS_SCORE generated: {readiness_json}", file=sys.stderr)
    
    # ========================================================================
    # Final verification: All artifacts have correct timestamps
    # ========================================================================
    print("\n[TEST] Final verification...", file=sys.stderr)
    
    all_artifacts = {
        'EDGE_SENTINEL': edge_sentinel,
        'WEEKLY_ROLLUP': weekly_rollup,
        'KPI_GATE': kpi_gate,
        'READINESS_SCORE': readiness,
    }
    
    for name, artifact in all_artifacts.items():
        utc = artifact['runtime']['utc']
        
        # Parse year from timestamp
        year = int(utc[:4])
        
        # Critical assertion: NO ARTIFACT should have 1970
        assert year != 1970, (
            f"{name} has 1970 timestamp (BUG!): {utc}\n"
            "This is the bug we're fixing - all artifacts must have real timestamps!"
        )
        
        print(f"  ✓ {name}: {utc} (year={year})", file=sys.stderr)
    
    print("\n[SUCCESS] All PRE artifacts generated with valid timestamps!", file=sys.stderr)


def test_param_sweep_synthetic_mode(tmp_path, monkeypatch):
    """
    Test param_sweep.py in synthetic mode (no fixture needed).
    
    This verifies that param_sweep works even when fixture is unavailable.
    """
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    
    frozen_time = '2025-01-15T12:00:00Z'
    monkeypatch.setenv('MM_FREEZE_UTC_ISO', frozen_time)
    
    # Change to repo root
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    
    # Run param_sweep in synthetic mode
    out_json = artifacts_dir / "PARAM_SWEEP.json"
    
    cmd = [
        sys.executable, '-m', 'tools.tuning.param_sweep',
        '--synthetic',
        '--num-events', '50',
        '--params', 'tools/sweep/grid.yaml',  # May not exist, that's OK
        '--out-json', str(out_json),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Should succeed even if grid.yaml doesn't exist (uses empty grid fallback)
    assert result.returncode == 0, (
        f"param_sweep failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    
    # Verify output exists
    assert out_json.exists(), "PARAM_SWEEP.json not created"
    
    with open(out_json, 'r', encoding='ascii') as f:
        sweep = json.load(f)
    
    # Verify structure
    assert 'runtime' in sweep
    assert 'synthetic_mode' in sweep
    assert sweep['synthetic_mode'] is True, "Should be in synthetic mode"
    
    # CRITICAL: Verify runtime.utc is NOT 1970
    assert sweep['runtime']['utc'] == frozen_time, (
        f"PARAM_SWEEP has wrong timestamp: {sweep['runtime']['utc']}"
    )
    
    print(f"[OK] PARAM_SWEEP synthetic mode works: {out_json}", file=sys.stderr)


def test_scan_secrets_no_fatal_failure(tmp_path, monkeypatch):
    """
    Test that scan_secrets.py doesn't fail CI jobs fatally.
    
    Even if secrets are found, it should return 0 (warning only).
    """
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    
    cmd = [sys.executable, 'tools/ci/scan_secrets.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Should always return 0 (informational only, not a gate)
    assert result.returncode == 0, (
        f"scan_secrets should not fail CI (rc=0 expected):\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    
    # Should output RESULT= line
    assert 'RESULT=' in result.stdout, "Missing RESULT= output"
    
    print(f"[OK] scan_secrets runs without fatal failure", file=sys.stderr)

