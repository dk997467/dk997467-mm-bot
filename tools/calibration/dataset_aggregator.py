#!/usr/bin/env python3
"""
Step 4: Dataset Aggregator for Offline Calibration

Aggregates fill and pipeline tick data from soak test into calibration dataset.

Usage:
    python tools/calibration/dataset_aggregator.py --from 2025-01-01T00:00:00Z --to 2025-01-02T00:00:00Z --interval-min 5
"""

import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import statistics


class DatasetAggregator:
    """Aggregates soak test data into calibration dataset."""
    
    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path.cwd()
        self.feeds_dir = self.project_root / "artifacts/edge/feeds"
        self.datasets_dir = self.project_root / "artifacts/edge/datasets"
        self.reports_dir = self.project_root / "artifacts/edge/reports"
        
        # Ensure directories exist
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def parse_iso_timestamp(self, ts_str: str) -> datetime:
        """Parse ISO 8601 timestamp."""
        # Handle both 'Z' and '+00:00' suffixes
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        return datetime.fromisoformat(ts_str)
    
    def find_jsonl_files(self, prefix: str, from_dt: datetime, to_dt: datetime) -> List[Path]:
        """Find relevant JSONL files in date range."""
        files = []
        
        # Generate list of expected daily files
        current = from_dt.date()
        end = to_dt.date()
        
        while current <= end:
            date_str = current.strftime("%Y%m%d")
            pattern = f"{prefix}_{date_str}.jsonl"
            file_path = self.feeds_dir / pattern
            
            if file_path.exists():
                files.append(file_path)
                self.log(f"Found: {file_path.name}")
            else:
                self.log(f"Missing: {pattern} (expected but not found)")
            
            current += timedelta(days=1)
        
        return files
    
    def load_jsonl_lines(self, file_path: Path, from_dt: datetime, to_dt: datetime) -> List[Dict]:
        """Load and filter JSONL lines by timestamp."""
        lines = []
        
        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    obj = json.loads(line)
                    
                    # Extract timestamp (different fields for different log types)
                    ts_str = obj.get('timestamp') or obj.get('ts') or obj.get('time')
                    if not ts_str:
                        continue
                    
                    ts = self.parse_iso_timestamp(ts_str)
                    
                    # Filter by date range
                    if from_dt <= ts < to_dt:
                        lines.append(obj)
                
                except json.JSONDecodeError as e:
                    self.log(f"[WARN] Line {line_num} invalid JSON: {e}")
                    continue
                except Exception as e:
                    self.log(f"[WARN] Line {line_num} error: {e}")
                    continue
        
        return lines
    
    def aggregate_intervals(self, data: List[Dict], interval_min: int) -> List[Dict]:
        """Aggregate data into intervals."""
        if not data:
            return []
        
        # Sort by timestamp
        data_sorted = sorted(data, key=lambda x: self.parse_iso_timestamp(x.get('timestamp') or x.get('ts') or x.get('time')))
        
        first_ts = self.parse_iso_timestamp(data_sorted[0].get('timestamp') or data_sorted[0].get('ts') or data_sorted[0].get('time'))
        
        # Round down to interval boundary
        start = first_ts.replace(second=0, microsecond=0)
        start = start.replace(minute=(start.minute // interval_min) * interval_min)
        
        intervals = []
        current_interval = []
        current_start = start
        interval_delta = timedelta(minutes=interval_min)
        
        for item in data_sorted:
            ts = self.parse_iso_timestamp(item.get('timestamp') or item.get('ts') or item.get('time'))
            
            # Check if we need to start a new interval
            while ts >= current_start + interval_delta:
                # Finalize current interval
                if current_interval:
                    intervals.append(self.compute_interval_stats(current_interval, current_start))
                
                # Start new interval
                current_start += interval_delta
                current_interval = []
            
            current_interval.append(item)
        
        # Finalize last interval
        if current_interval:
            intervals.append(self.compute_interval_stats(current_interval, current_start))
        
        return intervals
    
    def compute_interval_stats(self, items: List[Dict], interval_start: datetime) -> Dict:
        """Compute statistics for an interval."""
        stats = {
            'interval_start': interval_start.isoformat(),
            'interval_end': (interval_start + timedelta(minutes=5)).isoformat(),
            'count': len(items),
            'metrics': {}
        }
        
        # Extract numeric metrics
        latencies = []
        hit_ratios = []
        
        for item in items:
            # Try to extract latency
            if 'latency_ms' in item:
                latencies.append(item['latency_ms'])
            elif 'duration_ms' in item:
                latencies.append(item['duration_ms'])
            
            # Try to extract hit ratio
            if 'cache_hit' in item:
                hit_ratios.append(1 if item['cache_hit'] else 0)
        
        if latencies:
            stats['metrics']['latency_p50_ms'] = statistics.median(latencies)
            stats['metrics']['latency_p95_ms'] = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
            stats['metrics']['latency_p99_ms'] = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
        
        if hit_ratios:
            stats['metrics']['cache_hit_ratio'] = sum(hit_ratios) / len(hit_ratios)
        
        return stats
    
    def apply_sanity_filters(self, intervals: List[Dict]) -> List[Dict]:
        """Apply sanity filters to remove bad intervals."""
        filtered = []
        
        for interval in intervals:
            # Skip intervals with NaN/inf
            if any(
                isinstance(v, float) and (v != v or v == float('inf') or v == float('-inf'))
                for v in interval.get('metrics', {}).values()
            ):
                self.log(f"[FILTER] Skipping interval {interval['interval_start']}: NaN/inf detected")
                continue
            
            # Skip intervals with extreme latency spikes (> 1000ms)
            if interval.get('metrics', {}).get('latency_p95_ms', 0) > 1000:
                self.log(f"[FILTER] Skipping interval {interval['interval_start']}: latency spike")
                continue
            
            # Skip intervals with very low cache hit ratio (< 0.3)
            if interval.get('metrics', {}).get('cache_hit_ratio', 1.0) < 0.3:
                self.log(f"[FILTER] Skipping interval {interval['interval_start']}: low cache hit")
                continue
            
            filtered.append(interval)
        
        return filtered
    
    def generate_summary(self, dataset: Dict) -> str:
        """Generate summary markdown."""
        intervals = dataset.get('intervals', [])
        
        summary = f"""# Calibration Dataset Summary

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Dataset Info

- **Period:** {dataset['from']} to {dataset['to']}
- **Interval:** {dataset['interval_min']} minutes
- **Total Intervals:** {len(intervals)}
- **Duration:** {dataset.get('duration_hours', 0):.1f} hours

## Data Quality

- **Valid Intervals:** {len([i for i in intervals if i['count'] > 0])}
- **Filtered Out:** {dataset.get('filtered_count', 0)} intervals

## Sample Metrics (if available)

"""
        
        if intervals:
            # Compute overall statistics
            all_latencies = [i['metrics'].get('latency_p50_ms', 0) for i in intervals if 'latency_p50_ms' in i.get('metrics', {})]
            all_hit_ratios = [i['metrics'].get('cache_hit_ratio', 0) for i in intervals if 'cache_hit_ratio' in i.get('metrics', {})]
            
            if all_latencies:
                summary += f"**Latency (p50):** {statistics.median(all_latencies):.1f}ms (median across intervals)\n"
                summary += f"**Latency (p95):** {max(all_latencies):.1f}ms (max across intervals)\n"
            
            if all_hit_ratios:
                summary += f"**Cache Hit Ratio:** {statistics.mean(all_hit_ratios):.2%} (average)\n"
        
        summary += "\n## Next Steps\n\n"
        summary += "1. Review dataset quality\n"
        summary += "2. Run calibration: `python tools/calibration/auto_calibrate.py --dataset <file>`\n"
        summary += "3. Validate spread weights and queue-ETA parameters\n"
        
        return summary
    
    def aggregate(self, from_str: str, to_str: str, interval_min: int = 5) -> Dict:
        """Main aggregation logic."""
        self.log("=" * 60)
        self.log("DATASET AGGREGATION")
        self.log("=" * 60)
        
        from_dt = self.parse_iso_timestamp(from_str)
        to_dt = self.parse_iso_timestamp(to_str)
        
        self.log(f"Period: {from_dt} to {to_dt}")
        self.log(f"Interval: {interval_min} minutes")
        
        # Find relevant files
        self.log("\nSearching for data files...")
        files = self.find_jsonl_files("pipeline_ticks", from_dt, to_dt)
        
        if not files:
            self.log("[ERROR] No data files found in range")
            return {}
        
        # Load and filter data
        self.log("\nLoading data...")
        all_data = []
        for file_path in files:
            data = self.load_jsonl_lines(file_path, from_dt, to_dt)
            all_data.extend(data)
            self.log(f"  Loaded {len(data)} lines from {file_path.name}")
        
        self.log(f"\nTotal lines: {len(all_data)}")
        
        if not all_data:
            self.log("[ERROR] No data in range")
            return {}
        
        # Aggregate into intervals
        self.log("\nAggregating intervals...")
        intervals = self.aggregate_intervals(all_data, interval_min)
        self.log(f"  Created {len(intervals)} intervals")
        
        # Apply sanity filters
        self.log("\nApplying sanity filters...")
        intervals_before = len(intervals)
        intervals = self.apply_sanity_filters(intervals)
        intervals_after = len(intervals)
        filtered_count = intervals_before - intervals_after
        self.log(f"  Filtered {filtered_count} intervals")
        self.log(f"  Remaining: {intervals_after}")
        
        # Create dataset
        duration_hours = (to_dt - from_dt).total_seconds() / 3600
        dataset = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'from': from_str,
            'to': to_str,
            'interval_min': interval_min,
            'duration_hours': duration_hours,
            'filtered_count': filtered_count,
            'intervals': intervals
        }
        
        # Save dataset
        dataset_filename = f"calib_{from_dt.strftime('%Y%m%d')}_{to_dt.strftime('%Y%m%d')}.json"
        dataset_path = self.datasets_dir / dataset_filename
        
        with open(dataset_path, 'w') as f:
            json.dump(dataset, f, indent=2)
        
        self.log(f"\n[OK] Dataset saved: {dataset_path}")
        
        # Generate summary
        summary = self.generate_summary(dataset)
        summary_path = self.reports_dir / f"calib_summary_{from_dt.strftime('%Y%m%d')}_{to_dt.strftime('%Y%m%d')}.md"
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        self.log(f"[OK] Summary saved: {summary_path}")
        
        # Validate acceptance criteria
        self.log("\n" + "=" * 60)
        self.log("ACCEPTANCE VALIDATION")
        self.log("=" * 60)
        
        acceptance_pass = True
        
        if duration_hours < 12:
            self.log(f"[FAIL] Duration {duration_hours:.1f}h < 12h minimum")
            acceptance_pass = False
        else:
            self.log(f"[PASS] Duration {duration_hours:.1f}h >= 12h")
        
        if intervals_after == 0:
            self.log("[FAIL] No valid intervals")
            acceptance_pass = False
        else:
            self.log(f"[PASS] {intervals_after} valid intervals")
        
        if acceptance_pass:
            self.log("\n[OK] DATASET READY FOR CALIBRATION")
        else:
            self.log("\n[FAIL] DATASET DOES NOT MEET ACCEPTANCE CRITERIA")
        
        return dataset


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Aggregate soak test data into calibration dataset")
    parser.add_argument("--from", dest="from_ts", required=True, help="Start timestamp (ISO 8601)")
    parser.add_argument("--to", dest="to_ts", required=True, help="End timestamp (ISO 8601)")
    parser.add_argument("--interval-min", type=int, default=5, help="Interval in minutes (default: 5)")
    
    args = parser.parse_args()
    
    aggregator = DatasetAggregator()
    dataset = aggregator.aggregate(args.from_ts, args.to_ts, args.interval_min)
    
    if not dataset:
        sys.exit(1)


if __name__ == "__main__":
    main()
