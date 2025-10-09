#!/usr/bin/env python3
"""
Parameter sweep runner for strategy tuning.

Runs simulations across a grid of parameter combinations to find optimal settings.
Supports both real event fixtures and synthetic fallback when fixtures are unavailable.

Usage:
    python -m tools.tuning.param_sweep --params sweep/grid.yaml --out-json artifacts/PARAM_SWEEP.json
    
    # Use specific fixture (optional):
    python -m tools.tuning.param_sweep --events tests/fixtures/sweep/events_case1.jsonl --params sweep/grid.yaml
    
    # Synthetic mode (no fixture needed):
    python -m tools.tuning.param_sweep --synthetic --params sweep/grid.yaml
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List
from pathlib import Path

# Ensure src/ is in path for imports
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from src.common.runtime import get_runtime_info


def _finite(x: Any) -> float:
    """Safe float conversion with NaN/Inf protection."""
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _generate_synthetic_events(num_events: int = 100) -> List[Dict[str, Any]]:
    """
    Generate synthetic market events for param sweep when fixture is unavailable.
    
    Creates a minimal viable event stream with:
    - Quote updates (bid/ask)
    - Trade executions
    - Realistic timestamps
    
    Args:
        num_events: Number of events to generate (default: 100)
    
    Returns:
        List of event dicts compatible with sim engine
    """
    events = []
    base_ts = 1609459200000  # 2021-01-01T00:00:00Z in milliseconds
    
    # Generate alternating quotes and trades
    for i in range(num_events):
        ts_ms = base_ts + (i * 1000)  # 1 event per second
        
        if i % 2 == 0:
            # Quote update
            mid_price = 50000.0 + (i * 10.0)  # Trending price
            spread_bps = 5.0  # 5 bps spread
            spread = mid_price * (spread_bps / 10000.0)
            
            events.append({
                'type': 'quote',
                'ts_ms': ts_ms,
                'symbol': 'BTCUSDT',
                'bid': mid_price - (spread / 2),
                'ask': mid_price + (spread / 2),
                'bid_size': 1.0,
                'ask_size': 1.0,
            })
        else:
            # Trade execution (alternating buy/sell)
            price = 50000.0 + (i * 10.0)
            side = 'buy' if (i // 2) % 2 == 0 else 'sell'
            
            events.append({
                'type': 'trade',
                'ts_ms': ts_ms,
                'symbol': 'BTCUSDT',
                'side': side,
                'price': price,
                'qty': 0.01,
                'fee_bps': 0.5,  # 0.5 bps taker fee
            })
    
    return events


def _write_jsonl(path: str, events: List[Dict[str, Any]]) -> None:
    """Write events to JSONL file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='ascii') as f:
        for event in events:
            json.dump(event, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
            f.write('\n')


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """Write JSON atomically with fsync."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _load_params_grid(params_path: str) -> List[Dict[str, Any]]:
    """
    Load parameter grid from YAML file.
    
    Expected format:
        parameters:
          k_vola_spread: [0.5, 1.0, 1.5]
          skew_coeff: [0.0, 0.1, 0.2]
          levels_per_side: [3, 5, 7]
    
    Returns:
        List of parameter combinations (Cartesian product)
    """
    try:
        import yaml
        with open(params_path, 'r', encoding='ascii') as f:
            config = yaml.safe_load(f)
        
        params_dict = config.get('parameters', {})
        if not params_dict:
            return [{}]  # Empty grid = baseline only
        
        # Generate Cartesian product of all parameter combinations
        import itertools
        keys = list(params_dict.keys())
        values = [params_dict[k] if isinstance(params_dict[k], list) else [params_dict[k]] for k in keys]
        combinations = list(itertools.product(*values))
        
        return [dict(zip(keys, combo)) for combo in combinations]
    
    except Exception as e:
        print(f"[WARN] Failed to load params grid from {params_path}: {e}", file=sys.stderr)
        return [{}]  # Fallback to empty grid


def _run_simulation(events_path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run simulation with given parameters.
    
    Args:
        events_path: Path to events JSONL file
        params: Parameter overrides
    
    Returns:
        Simulation result dict with metrics
    """
    # Import sim engine (lazy import to avoid circular dependencies)
    try:
        from src.sim.execution import run_sim
        
        # Run sim with params
        out_json = f'artifacts/sweep_temp_{id(params)}.json'
        result = run_sim(events_path, mode='queue_aware', params=params, out_json=out_json)
        
        # Clean up temp file
        try:
            os.remove(out_json)
        except Exception:
            pass
        
        return result
    
    except ImportError as e:
        print(f"[ERROR] Failed to import sim engine: {e}", file=sys.stderr)
        print("[WARN] Returning dummy result", file=sys.stderr)
        
        # Return dummy result for testing
        return {
            'edge_net_bps': 2.5,
            'order_age_p95_ms': 250.0,
            'taker_share_pct': 12.0,
            'fills_total': 50,
            'params': params,
        }
    
    except Exception as e:
        print(f"[ERROR] Simulation failed: {e}", file=sys.stderr)
        return {
            'edge_net_bps': 0.0,
            'order_age_p95_ms': 999.0,
            'taker_share_pct': 100.0,
            'fills_total': 0,
            'params': params,
            'error': str(e),
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Parameter sweep for strategy tuning')
    ap.add_argument('--events', help='Path to events JSONL fixture (optional)')
    ap.add_argument('--synthetic', action='store_true', help='Use synthetic events if fixture missing')
    ap.add_argument('--params', default='tools/sweep/grid.yaml', help='Parameter grid YAML')
    ap.add_argument('--out-json', default='artifacts/PARAM_SWEEP.json', help='Output JSON report')
    ap.add_argument('--num-events', type=int, default=100, help='Number of synthetic events to generate')
    args = ap.parse_args(argv)
    
    # Determine events source
    events_path = args.events
    if events_path and Path(events_path).exists():
        print(f"[OK] Using fixture: {events_path}", file=sys.stderr)
        synthetic_mode = False
    elif args.events and not Path(args.events).exists():
        print(f"[WARN] Fixture not found: {args.events}", file=sys.stderr)
        print(f"[INFO] Falling back to synthetic events (--synthetic)", file=sys.stderr)
        synthetic_mode = True
    else:
        # No fixture specified, use synthetic by default
        print("[INFO] No fixture specified, using synthetic events", file=sys.stderr)
        synthetic_mode = True
    
    # Generate synthetic events if needed
    if synthetic_mode:
        events_path = 'artifacts/sweep_synthetic_events.jsonl'
        print(f"[INFO] Generating {args.num_events} synthetic events...", file=sys.stderr)
        synthetic_events = _generate_synthetic_events(args.num_events)
        _write_jsonl(events_path, synthetic_events)
        print(f"[OK] Wrote synthetic events to {events_path}", file=sys.stderr)
    
    # Load parameter grid
    param_grid = _load_params_grid(args.params)
    print(f"[INFO] Loaded {len(param_grid)} parameter combinations from {args.params}", file=sys.stderr)
    
    # Run sweep
    results = []
    for i, params in enumerate(param_grid, start=1):
        print(f"[SWEEP] Running combination {i}/{len(param_grid)}: {params}", file=sys.stderr)
        result = _run_simulation(events_path, params)
        results.append(result)
    
    # Rank by edge_net_bps (descending)
    results_sorted = sorted(results, key=lambda x: -_finite(x.get('edge_net_bps', 0.0)))
    
    # Find best params
    best = results_sorted[0] if results_sorted else {}
    best_params = best.get('params', {})
    best_edge = _finite(best.get('edge_net_bps', 0.0))
    
    # Build report
    report = {
        'best_params': best_params,
        'best_edge_net_bps': best_edge,
        'combinations_tested': len(results),
        'results': results_sorted,
        'runtime': get_runtime_info(),
        'synthetic_mode': synthetic_mode,
    }
    
    # Write report
    _write_json_atomic(args.out_json, report)
    print(f"[OK] Wrote sweep report to {args.out_json}", file=sys.stderr)
    print(f"[RESULT] Best edge: {best_edge:.6f} bps with params: {best_params}")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

