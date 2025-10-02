#!/usr/bin/env python3
"""
Resource monitoring for long-running soak tests (24-72h).

Collects and logs system resource metrics:
- CPU usage (%, per-core breakdown)
- Memory usage (total, available, percent)
- Disk usage (size, free space)
- Network I/O (bytes sent/received)
- Process-specific metrics (Python process)

Critical for detecting:
- Memory leaks (gradual RAM increase)
- CPU spikes (performance degradation)
- Disk bloat (log accumulation)
- Network anomalies (connection issues)

Usage:
    # Run standalone (collect every 60s, save to artifacts/soak/resources.jsonl)
    python tools/soak/resource_monitor.py --interval 60 --output artifacts/soak/resources.jsonl
    
    # Run in background during soak test
    python tools/soak/resource_monitor.py --interval 60 --output artifacts/soak/resources.jsonl &
"""
import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any


@dataclass
class ResourceSnapshot:
    """Single snapshot of system resources at a point in time."""
    timestamp_utc: str
    timestamp_unix: float
    
    # CPU metrics
    cpu_percent: float
    cpu_count: int
    cpu_freq_mhz: Optional[float]
    
    # Memory metrics (MB)
    memory_total_mb: float
    memory_available_mb: float
    memory_used_mb: float
    memory_percent: float
    
    # Disk metrics (GB)
    disk_total_gb: float
    disk_used_gb: float
    disk_free_gb: float
    disk_percent: float
    
    # Network metrics (bytes)
    network_bytes_sent: int
    network_bytes_recv: int
    
    # Process-specific (Python process running the monitor)
    process_cpu_percent: float
    process_memory_mb: float
    process_memory_percent: float
    process_threads: int
    
    # System info (static, but useful for correlation)
    hostname: str
    platform: str
    python_version: str


class ResourceMonitor:
    """
    Lightweight resource monitor for soak tests.
    
    Design principles:
    - Minimal overhead (<1% CPU)
    - Graceful degradation (if psutil unavailable, use fallback)
    - JSONL output for easy parsing
    - No external dependencies beyond stdlib (psutil optional)
    """
    
    def __init__(self, output_path: Path, interval_seconds: int = 60):
        """
        Initialize resource monitor.
        
        Args:
            output_path: Path to output JSONL file
            interval_seconds: Sampling interval (default: 60s)
        """
        self.output_path = output_path
        self.interval_seconds = interval_seconds
        
        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Try to import psutil (optional but recommended)
        self.psutil = None
        try:
            import psutil
            self.psutil = psutil
            print(f"[MONITOR] Using psutil {psutil.__version__} for accurate metrics")
        except ImportError:
            print("[MONITOR] psutil not available, using fallback metrics")
        
        # Cache for calculating deltas (network I/O)
        self._last_network_counters: Optional[Dict[str, int]] = None
        
        # Process handle (for process-specific metrics)
        self._process = None
        if self.psutil:
            try:
                self._process = self.psutil.Process()
            except Exception:
                pass
    
    def collect_snapshot(self) -> ResourceSnapshot:
        """
        Collect current resource snapshot.
        
        Returns:
            ResourceSnapshot with current metrics
        """
        now = datetime.now(timezone.utc)
        
        # CPU metrics
        cpu_percent = 0.0
        cpu_count = os.cpu_count() or 1
        cpu_freq_mhz = None
        
        if self.psutil:
            try:
                cpu_percent = self.psutil.cpu_percent(interval=0.1)
                cpu_freq = self.psutil.cpu_freq()
                if cpu_freq:
                    cpu_freq_mhz = cpu_freq.current
            except Exception:
                pass
        
        # Memory metrics
        memory_total_mb = 0.0
        memory_available_mb = 0.0
        memory_used_mb = 0.0
        memory_percent = 0.0
        
        if self.psutil:
            try:
                mem = self.psutil.virtual_memory()
                memory_total_mb = mem.total / (1024 * 1024)
                memory_available_mb = mem.available / (1024 * 1024)
                memory_used_mb = mem.used / (1024 * 1024)
                memory_percent = mem.percent
            except Exception:
                pass
        
        # Disk metrics
        disk_total_gb = 0.0
        disk_used_gb = 0.0
        disk_free_gb = 0.0
        disk_percent = 0.0
        
        if self.psutil:
            try:
                # Monitor disk where output file is located
                disk = self.psutil.disk_usage(str(self.output_path.parent))
                disk_total_gb = disk.total / (1024 * 1024 * 1024)
                disk_used_gb = disk.used / (1024 * 1024 * 1024)
                disk_free_gb = disk.free / (1024 * 1024 * 1024)
                disk_percent = disk.percent
            except Exception:
                pass
        
        # Network metrics
        network_bytes_sent = 0
        network_bytes_recv = 0
        
        if self.psutil:
            try:
                net_io = self.psutil.net_io_counters()
                network_bytes_sent = net_io.bytes_sent
                network_bytes_recv = net_io.bytes_recv
            except Exception:
                pass
        
        # Process-specific metrics
        process_cpu_percent = 0.0
        process_memory_mb = 0.0
        process_memory_percent = 0.0
        process_threads = 0
        
        if self._process:
            try:
                process_cpu_percent = self._process.cpu_percent(interval=0.1)
                process_mem = self._process.memory_info()
                process_memory_mb = process_mem.rss / (1024 * 1024)
                process_memory_percent = self._process.memory_percent()
                process_threads = self._process.num_threads()
            except Exception:
                pass
        
        return ResourceSnapshot(
            timestamp_utc=now.isoformat(),
            timestamp_unix=now.timestamp(),
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            cpu_freq_mhz=cpu_freq_mhz,
            memory_total_mb=memory_total_mb,
            memory_available_mb=memory_available_mb,
            memory_used_mb=memory_used_mb,
            memory_percent=memory_percent,
            disk_total_gb=disk_total_gb,
            disk_used_gb=disk_used_gb,
            disk_free_gb=disk_free_gb,
            disk_percent=disk_percent,
            network_bytes_sent=network_bytes_sent,
            network_bytes_recv=network_bytes_recv,
            process_cpu_percent=process_cpu_percent,
            process_memory_mb=process_memory_mb,
            process_memory_percent=process_memory_percent,
            process_threads=process_threads,
            hostname=platform.node(),
            platform=platform.platform(),
            python_version=sys.version.split()[0],
        )
    
    def write_snapshot(self, snapshot: ResourceSnapshot) -> None:
        """
        Write snapshot to JSONL file (append mode).
        
        Args:
            snapshot: ResourceSnapshot to write
        """
        try:
            with open(self.output_path, 'a', encoding='utf-8') as f:
                json.dump(asdict(snapshot), f, separators=(',', ':'))
                f.write('\n')
        except Exception as e:
            print(f"[MONITOR] Error writing snapshot: {e}", file=sys.stderr)
    
    def log_summary(self, snapshot: ResourceSnapshot) -> None:
        """
        Log human-readable summary to stdout.
        
        Args:
            snapshot: ResourceSnapshot to summarize
        """
        print(
            f"[MONITOR] {snapshot.timestamp_utc} | "
            f"CPU: {snapshot.cpu_percent:.1f}% | "
            f"MEM: {snapshot.memory_used_mb:.0f}/{snapshot.memory_total_mb:.0f} MB ({snapshot.memory_percent:.1f}%) | "
            f"DISK: {snapshot.disk_used_gb:.1f}/{snapshot.disk_total_gb:.1f} GB ({snapshot.disk_percent:.1f}%) | "
            f"PROC: CPU={snapshot.process_cpu_percent:.1f}% MEM={snapshot.process_memory_mb:.0f} MB"
        )
    
    def run(self, duration_seconds: Optional[int] = None) -> None:
        """
        Run monitoring loop.
        
        Args:
            duration_seconds: Total duration to monitor (None = infinite)
        """
        start_time = time.time()
        iteration = 0
        
        print(f"[MONITOR] Starting resource monitoring (interval: {self.interval_seconds}s, output: {self.output_path})")
        
        try:
            while True:
                iteration += 1
                
                # Collect and save snapshot
                snapshot = self.collect_snapshot()
                self.write_snapshot(snapshot)
                self.log_summary(snapshot)
                
                # Check if duration exceeded
                if duration_seconds and (time.time() - start_time) >= duration_seconds:
                    print(f"[MONITOR] Duration limit reached ({duration_seconds}s), stopping...")
                    break
                
                # Sleep until next interval
                time.sleep(self.interval_seconds)
        
        except KeyboardInterrupt:
            print("\n[MONITOR] Interrupted by user, stopping...")
        
        except Exception as e:
            print(f"[MONITOR] Fatal error: {e}", file=sys.stderr)
            raise
        
        finally:
            print(f"[MONITOR] Collected {iteration} snapshots, saved to {self.output_path}")


def analyze_resources(input_path: Path) -> Dict[str, Any]:
    """
    Analyze collected resource data and detect anomalies.
    
    Args:
        input_path: Path to JSONL file with snapshots
    
    Returns:
        Dict with analysis results (memory leak detection, CPU spikes, etc.)
    """
    snapshots = []
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    snapshots.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return {"error": "File not found"}
    
    if not snapshots:
        return {"error": "No valid snapshots"}
    
    # Extract time series
    timestamps = [s['timestamp_unix'] for s in snapshots]
    memory_used = [s['memory_used_mb'] for s in snapshots]
    cpu_percent = [s['cpu_percent'] for s in snapshots]
    disk_used = [s['disk_used_gb'] for s in snapshots]
    
    # Memory leak detection (linear regression slope)
    n = len(memory_used)
    if n >= 2:
        # Simple linear regression: slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
        x = list(range(n))
        sum_x = sum(x)
        sum_y = sum(memory_used)
        sum_xy = sum(xi * yi for xi, yi in zip(x, memory_used))
        sum_x2 = sum(xi * xi for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x) if (n * sum_x2 - sum_x * sum_x) != 0 else 0
        
        memory_leak_mb_per_hour = slope * (3600 / (timestamps[-1] - timestamps[0]) * n) if n > 1 else 0
    else:
        memory_leak_mb_per_hour = 0
    
    analysis = {
        "snapshot_count": n,
        "duration_hours": (timestamps[-1] - timestamps[0]) / 3600 if n > 1 else 0,
        
        "memory": {
            "min_mb": min(memory_used) if memory_used else 0,
            "max_mb": max(memory_used) if memory_used else 0,
            "avg_mb": sum(memory_used) / len(memory_used) if memory_used else 0,
            "leak_mb_per_hour": memory_leak_mb_per_hour,
            "leak_detected": abs(memory_leak_mb_per_hour) > 10,  # >10 MB/h is suspicious
        },
        
        "cpu": {
            "min_percent": min(cpu_percent) if cpu_percent else 0,
            "max_percent": max(cpu_percent) if cpu_percent else 0,
            "avg_percent": sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0,
        },
        
        "disk": {
            "min_gb": min(disk_used) if disk_used else 0,
            "max_gb": max(disk_used) if disk_used else 0,
            "growth_gb": disk_used[-1] - disk_used[0] if len(disk_used) >= 2 else 0,
        }
    }
    
    return analysis


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor system resources during soak tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Sampling interval in seconds (default: 60)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('artifacts/soak/resources.jsonl'),
        help='Output JSONL file path (default: artifacts/soak/resources.jsonl)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        help='Total duration in seconds (default: infinite)'
    )
    parser.add_argument(
        '--analyze',
        type=Path,
        default=None,
        help='Analyze existing JSONL file instead of monitoring'
    )
    
    args = parser.parse_args()
    
    if args.analyze:
        # Analysis mode
        print(f"[MONITOR] Analyzing {args.analyze}...")
        analysis = analyze_resources(args.analyze)
        print(json.dumps(analysis, indent=2))
        
        # Write analysis to separate file
        analysis_output = args.analyze.with_suffix('.analysis.json')
        with open(analysis_output, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2)
        print(f"[MONITOR] Analysis saved to {analysis_output}")
    
    else:
        # Monitoring mode
        monitor = ResourceMonitor(args.output, args.interval)
        monitor.run(args.duration)


if __name__ == '__main__':
    main()

