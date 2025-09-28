#!/usr/bin/env python3
"""Create test data for E2 Part 1 Polish."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

def main():
    symbol = 'E2POLISH'
    base_dir = Path('data/test_summaries') / symbol
    base_dir.mkdir(parents=True, exist_ok=True)
    
    base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    
    for i in range(5):
        hour = base_time + timedelta(hours=i)
        filename = f'{symbol}_{hour.strftime("%Y-%m-%d_%H")}.json'
        file_path = base_dir / filename
        
        summary = {
            'schema_version': 'e1.1',
            'symbol': symbol,
            'hour_utc': hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            'window_utc': {
                'hour_start': hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'hour_end': (hour + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
            },
            'bins_max_bps': 20,  # Different from CLI to test priority
            'percentiles_used': [0.1, 0.5, 0.9],  # Different from CLI 
            'counts': {
                'orders': 40 + i * 8,
                'quotes': 80 + i * 15,
                'fills': 20 + i * 4
            },
            'hit_rate_by_bin': {
                '0': {'count': 25 + i * 4, 'fills': 6 + i},
                '5': {'count': 25 + i * 5, 'fills': 7 + i},
                '10': {'count': 30 + i * 6, 'fills': 7 + i}
            },
            'queue_wait_cdf_ms': [
                {'p': 0.1, 'v': 80.0 + i * 8},
                {'p': 0.5, 'v': 160.0 + i * 16},
                {'p': 0.9, 'v': 280.0 + i * 28}
            ],
            'metadata': {
                'git_sha': f'polish_sha_{i}',
                'cfg_hash': f'polish_cfg_{i}'
            }
        }
        
        with open(file_path, 'w') as f:
            json.dump(summary, f, indent=2, sort_keys=True)
    
    print(f'Created 5 test summary files in {base_dir}')

if __name__ == '__main__':
    main()
