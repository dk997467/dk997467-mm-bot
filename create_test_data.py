#!/usr/bin/env python3
"""Create test data for E2 Part 1 calibration."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

def main():
    symbol = 'E2TEST'
    base_dir = Path('data/test_summaries') / symbol
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # Create 5 test summary files
    base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    
    for i in range(5):
        hour = base_time + timedelta(hours=i)
        filename = f'{symbol}_{hour.strftime("%Y-%m-%d_%H")}.json'
        file_path = base_dir / filename
        
        summary = {
            'schema_version': 'e1.1',
            'symbol': symbol,
            'hour_utc': hour.isoformat() + 'Z',
            'generated_at_utc': datetime.now(timezone.utc).isoformat() + 'Z',
                    'window_utc': {
            'hour_start': hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'hour_end': (hour + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        },
            'bins_max_bps': 25,
            'percentiles_used': [0.25, 0.5, 0.75, 0.9],
            'counts': {
                'orders': 30 + i * 5,
                'quotes': 60 + i * 10,
                'fills': 15 + i * 3
            },
            'hit_rate_by_bin': {
                '0': {'count': 20 + i * 2, 'fills': 5 + i},
                '5': {'count': 18 + i * 3, 'fills': 4 + i},
                '10': {'count': 22 + i * 5, 'fills': 6 + i}
            },
            'queue_wait_cdf_ms': [
                {'p': 0.25, 'v': 100.0 + i * 10},
                {'p': 0.5, 'v': 150.0 + i * 15},
                {'p': 0.75, 'v': 200.0 + i * 20},
                {'p': 0.9, 'v': 250.0 + i * 25}
            ],
            'metadata': {
                'git_sha': f'test_sha_{i}',
                'cfg_hash': f'test_cfg_{i}'
            }
        }
        
        with open(file_path, 'w') as f:
            json.dump(summary, f, indent=2, sort_keys=True)
    
    print(f'Created 5 test summary files in {base_dir}')

if __name__ == '__main__':
    main()
