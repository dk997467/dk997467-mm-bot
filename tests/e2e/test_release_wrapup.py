import subprocess
import sys
from pathlib import Path


def test_verify_links():
    """Test that verify_links runs and reports OK"""
    result = subprocess.run([
        sys.executable, '-m', 'tools.release.verify_links'
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert '[OK] all links valid' in result.stdout
    assert result.stdout.endswith('\n')


def test_go_nogo_on_fixtures():
    """Test that go_nogo runs on current fixtures/artifacts"""
    # First ensure we have some artifacts by running edge CLI
    root = Path(__file__).resolve().parents[2]
    subprocess.run([
        sys.executable, '-m', 'tools.edge_cli',
        '--trades', str(root / 'tests' / 'fixtures' / 'edge_trades_case1.jsonl'),
        '--quotes', str(root / 'tests' / 'fixtures' / 'edge_quotes_case1.jsonl'),
        '--out', 'artifacts/EDGE_REPORT.json'
    ], check=True)
    
    # Create minimal metrics.json for go_nogo
    import json
    import os
    os.makedirs('artifacts', exist_ok=True)
    metrics = {
        'edge': {'net_bps': 3.0},
        'latency': {'p95_ms_avg': 300.0},
        'pnl': {'total_taker_share_pct': 12.0}
    }
    with open('artifacts/metrics.json', 'w') as f:
        json.dump(metrics, f)
    
    result = subprocess.run([
        sys.executable, '-m', 'tools.release.go_nogo'
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert 'VERDICT=GO' in result.stdout
    assert result.stdout.endswith('\n')


def test_shadow_canary_plan():
    """Test that shadow canary plan runs and shows readiness"""
    result = subprocess.run([
        sys.executable, '-m', 'tools.release.run_shadow_canary'
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert 'Shadow→Canary→Live Release Plan' in result.stdout
    assert result.stdout.endswith('\n')
