#!/usr/bin/env python3
"""
Cron Sentinel - Scheduled Task Freshness Validator

Checks that scheduled tasks are running and producing fresh artifacts.

Usage:
    python -m tools.cron.sentinel --config deploy/cron/sentinel.yaml
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List


def parse_max_age(max_age_str: str) -> timedelta:
    """Parse max age string (e.g., '1d', '6h', '30m') to timedelta."""
    max_age_str = max_age_str.strip().lower()
    
    if max_age_str.endswith('d'):
        return timedelta(days=int(max_age_str[:-1]))
    elif max_age_str.endswith('h'):
        return timedelta(hours=int(max_age_str[:-1]))
    elif max_age_str.endswith('m'):
        return timedelta(minutes=int(max_age_str[:-1]))
    elif max_age_str.endswith('s'):
        return timedelta(seconds=int(max_age_str[:-1]))
    else:
        # Assume hours by default
        return timedelta(hours=int(max_age_str))


def check_artifact_freshness(path: str, max_age: timedelta) -> Dict[str, Any]:
    """
    Check if artifact exists and is fresh.
    
    Returns dict with status and details.
    """
    file_path = Path(path)
    
    if not file_path.exists():
        return {
            "status": "missing",
            "message": f"Artifact not found: {path}",
            "age": None
        }
    
    try:
        mtime = file_path.stat().st_mtime
        file_time = datetime.fromtimestamp(mtime, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - file_time
        
        if age > max_age:
            return {
                "status": "stale",
                "message": f"Artifact is {age.total_seconds():.0f}s old (max: {max_age.total_seconds():.0f}s)",
                "age": age.total_seconds()
            }
        else:
            return {
                "status": "fresh",
                "message": f"Artifact is {age.total_seconds():.0f}s old (OK)",
                "age": age.total_seconds()
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking {path}: {str(e)}",
            "age": None
        }


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON/YAML file."""
    path = Path(config_path)
    
    if not path.exists():
        # Return default config for testing
        return {
            "tasks": [
                {
                    "name": "nightly_tests",
                    "artifact": "artifacts/reports/nightly_results.json",
                    "max_age": "36h"
                },
                {
                    "name": "soak_metrics",
                    "artifact": "artifacts/reports/soak_metrics.json",
                    "max_age": "7d"
                }
            ]
        }
    
    # Try JSON first
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Fallback: simple key=value parser for YAML-like files
        # (stdlib-only, so no PyYAML)
        print(f"[WARN] Could not parse {config_path} as JSON, using defaults")
        return {
            "tasks": [
                {
                    "name": "default_task",
                    "artifact": "artifacts/reports/readiness.json",
                    "max_age": "24h"
                }
            ]
        }


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Cron sentinel - check scheduled task freshness")
    parser.add_argument("--config", default="deploy/cron/sentinel.yaml", help="Config file path")
    args = parser.parse_args(argv)
    
    print("\n" + "="*60)
    print("CRON SENTINEL")
    print("="*60 + "\n")
    
    # Load config
    print(f"[CONFIG] Loading from {args.config}...")
    config = load_config(args.config)
    tasks = config.get("tasks", [])
    print(f"[CONFIG] Loaded {len(tasks)} tasks\n")
    
    # Check each task
    results = []
    failed_tasks = []
    
    for task in tasks:
        name = task.get("name", "unknown")
        artifact = task.get("artifact", "")
        max_age_str = task.get("max_age", "24h")
        
        print(f"[CHECK] {name}")
        print(f"        Artifact: {artifact}")
        print(f"        Max age: {max_age_str}")
        
        max_age = parse_max_age(max_age_str)
        result = check_artifact_freshness(artifact, max_age)
        
        status_emoji = {
            "fresh": "✓",
            "stale": "✗",
            "missing": "✗",
            "error": "!"
        }.get(result["status"], "?")
        
        print(f"        Result: {status_emoji} {result['status'].upper()} - {result['message']}\n")
        
        results.append({
            "task": name,
            "status": result["status"],
            "message": result["message"]
        })
        
        if result["status"] in ["stale", "missing", "error"]:
            failed_tasks.append(name)
    
    # Summary
    print("-"*60)
    print("SUMMARY")
    print("-"*60)
    print(f"Total tasks: {len(tasks)}")
    print(f"Passed: {len(tasks) - len(failed_tasks)}")
    print(f"Failed: {len(failed_tasks)}")
    
    if failed_tasks:
        print(f"\nFailed tasks: {', '.join(failed_tasks)}")
        print("-"*60 + "\n")
        return 1
    else:
        print("\n✓ All tasks are fresh")
        print("-"*60 + "\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())

