#!/usr/bin/env python3
"""
Redis Export Smoke Check

Validates Redis export functionality with load testing, TTL checks,
and cross-verification between hash and flat modes.

Usage:
    python -m tools.shadow.redis_smoke_check --src artifacts/soak/latest --redis-url redis://localhost:6379/0
    python -m tools.shadow.redis_smoke_check --do-flat-backfill --sample-keys 10
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import warnings


def get_redis_client(redis_url: str) -> Optional[Any]:
    """
    Get Redis client with TLS support.
    
    Args:
        redis_url: Redis connection URL (redis:// or rediss://)
        
    Returns:
        Redis client or None if unavailable
    """
    try:
        import redis
        
        # Parse URL and create client
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
        
        # Test connection
        client.ping()
        return client
        
    except ImportError:
        print("[WARN] redis library not installed (pip install redis)")
        return None
    except Exception as e:
        print(f"[WARN] Could not connect to Redis: {e}")
        return None


def run_export(
    src_dir: Path,
    redis_client: Any,
    env: str,
    exchange: str,
    batch_size: int,
    hash_mode: bool = True
) -> Tuple[int, float, Dict]:
    """
    Run Redis export and collect metrics.
    
    Args:
        src_dir: Source directory with ITER_SUMMARY files
        redis_client: Redis client
        env: Environment namespace
        exchange: Exchange namespace
        batch_size: Pipeline batch size
        hash_mode: Use hash mode (True) or flat mode (False)
        
    Returns:
        Tuple of (exported_count, wall_time_ms, metrics)
    """
    from tools.shadow.export_to_redis import (
        load_iter_summaries,
        aggregate_kpis,
        export_to_redis,
        METRICS,
        reset_metrics
    )
    
    # Reset metrics
    reset_metrics()
    
    # Load and aggregate
    print(f"[SMOKE] Loading summaries from {src_dir}...")
    summaries = load_iter_summaries(src_dir)
    
    if not summaries:
        print("[ERROR] No summaries found")
        return 0, 0.0, {}
    
    kpis = aggregate_kpis(summaries)
    print(f"[SMOKE] Aggregated {len(kpis)} symbols")
    
    # Export with timing
    mode_str = "hash" if hash_mode else "flat"
    print(f"[SMOKE] Running export (mode={mode_str}, batch_size={batch_size})...")
    
    start_time = time.time()
    exported_count = export_to_redis(
        kpis,
        redis_client,
        env=env,
        exchange=exchange,
        ttl=3600,
        dry_run=False,
        hash_mode=hash_mode,
        batch_size=batch_size
    )
    wall_time_ms = (time.time() - start_time) * 1000
    
    print(f"[SMOKE] Export completed in {wall_time_ms:.2f}ms")
    
    return exported_count, wall_time_ms, dict(METRICS)


def scan_keys(
    redis_client: Any,
    pattern: str,
    limit: int = 1000
) -> List[str]:
    """
    Scan Redis keys matching pattern.
    
    Args:
        redis_client: Redis client
        pattern: Key pattern (e.g., "dev:bybit:shadow:latest:*")
        limit: Maximum keys to return
        
    Returns:
        List of matching keys
    """
    keys = []
    cursor = 0
    
    while True:
        cursor, batch = redis_client.scan(cursor, match=pattern, count=100)
        keys.extend(batch)
        
        if cursor == 0 or len(keys) >= limit:
            break
    
    return keys[:limit]


def verify_hash_keys(
    redis_client: Any,
    keys: List[str],
    sample_size: int = 10
) -> Dict[str, Any]:
    """
    Verify hash keys have correct TTL and fields.
    
    Args:
        redis_client: Redis client
        keys: List of hash keys to verify
        sample_size: Number of keys to sample
        
    Returns:
        Verification results dict
    """
    if not keys:
        return {"status": "FAIL", "reason": "No keys found"}
    
    # Sample random keys
    sample_keys = random.sample(keys, min(sample_size, len(keys)))
    
    results = {
        "total_keys": len(keys),
        "sampled": len(sample_keys),
        "passed": 0,
        "failed": 0,
        "issues": [],
        "sample_details": []
    }
    
    expected_fields = {"edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"}
    
    for key in sample_keys:
        # Check TTL
        ttl = redis_client.ttl(key)
        
        # Get all hash fields
        hash_data = redis_client.hgetall(key)
        fields = set(hash_data.keys())
        
        # Verify
        issues = []
        
        if ttl <= 0:
            issues.append(f"TTL={ttl} (expected > 0)")
        
        missing_fields = expected_fields - fields
        if missing_fields:
            issues.append(f"Missing fields: {missing_fields}")
        
        detail = {
            "key": key,
            "ttl": ttl,
            "fields": list(fields),
            "values": hash_data,
            "issues": issues
        }
        
        results["sample_details"].append(detail)
        
        if issues:
            results["failed"] += 1
            results["issues"].extend(issues)
        else:
            results["passed"] += 1
    
    results["status"] = "PASS" if results["failed"] == 0 else "FAIL"
    
    return results


def verify_flat_backfill(
    redis_client: Any,
    env: str,
    exchange: str,
    hash_keys: List[str],
    flat_prefix: str,
    sample_size: int = 5
) -> Dict[str, Any]:
    """
    Cross-verify hash mode values with flat mode backfill.
    
    Args:
        redis_client: Redis client
        env: Environment namespace
        exchange: Exchange namespace
        hash_keys: List of hash keys
        flat_prefix: Flat key prefix
        sample_size: Number of symbols to verify
        
    Returns:
        Verification results dict
    """
    # Extract symbols from hash keys
    # Key format: {env}:{exchange}:shadow:latest:{symbol}
    symbols = []
    for key in hash_keys:
        parts = key.split(":")
        if len(parts) >= 5:
            symbol = parts[4]
            symbols.append(symbol)
    
    if not symbols:
        return {"status": "FAIL", "reason": "No symbols found in hash keys"}
    
    # Sample random symbols
    sample_symbols = random.sample(symbols, min(sample_size, len(symbols)))
    
    results = {
        "symbols_checked": len(sample_symbols),
        "matches": 0,
        "mismatches": 0,
        "missing_flat": 0,
        "details": []
    }
    
    for symbol in sample_symbols:
        # Get hash values
        hash_key = f"{env}:{exchange}:shadow:latest:{symbol}"
        hash_data = redis_client.hgetall(hash_key)
        
        # Get flat values
        flat_values = {}
        for kpi in ["edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"]:
            flat_key = f"{flat_prefix}:{symbol}:{kpi}"
            value = redis_client.get(flat_key)
            if value is not None:
                flat_values[kpi] = value
        
        # Compare
        detail = {
            "symbol": symbol,
            "hash_data": hash_data,
            "flat_data": flat_values,
            "status": "UNKNOWN"
        }
        
        if not flat_values:
            results["missing_flat"] += 1
            detail["status"] = "MISSING_FLAT"
        elif hash_data == flat_values:
            results["matches"] += 1
            detail["status"] = "MATCH"
        else:
            results["mismatches"] += 1
            detail["status"] = "MISMATCH"
        
        results["details"].append(detail)
    
    results["status"] = "PASS" if results["mismatches"] == 0 and results["missing_flat"] == 0 else "WARN"
    
    return results


def generate_report(
    output_path: Path,
    export_results: Dict,
    hash_verification: Dict,
    flat_verification: Optional[Dict] = None
) -> str:
    """
    Generate markdown smoke test report.
    
    Args:
        output_path: Output file path
        export_results: Export metrics and timing
        hash_verification: Hash key verification results
        flat_verification: Optional flat mode verification results
        
    Returns:
        Verdict (PASS/WARN/FAIL)
    """
    # Determine verdict
    verdict = "PASS"
    reasons = []
    
    if export_results.get("exported_count", 0) == 0:
        verdict = "FAIL"
        reasons.append("No keys exported")
    
    if hash_verification.get("status") == "FAIL":
        verdict = "FAIL"
        reasons.append(f"Hash verification failed: {hash_verification.get('failed', 0)} keys with issues")
    
    if flat_verification and flat_verification.get("status") == "FAIL":
        verdict = "FAIL"
        reasons.append("Flat backfill verification failed")
    elif flat_verification and flat_verification.get("status") == "WARN":
        if verdict == "PASS":
            verdict = "WARN"
        reasons.append(f"Flat backfill issues: {flat_verification.get('mismatches', 0)} mismatches")
    
    # Generate report
    lines = [
        "# Redis Export Smoke Test Report",
        "",
        f"**Verdict:** {verdict}",
        ""
    ]
    
    if reasons:
        lines.append("**Reasons:**")
        for reason in reasons:
            lines.append(f"- {reason}")
        lines.append("")
    
    lines.extend([
        "## Export Performance",
        "",
        f"- **Exported Count:** {export_results.get('exported_count', 0)}",
        f"- **Wall Time:** {export_results.get('wall_time_ms', 0):.2f}ms",
        f"- **Batch Size:** {export_results.get('batch_size', 0)}",
        f"- **Mode:** {export_results.get('mode', 'unknown')}",
        "",
        "### Prometheus Metrics",
        "",
        f"- `redis_export_success_total`: {export_results.get('metrics', {}).get('redis_export_success_total', 0)}",
        f"- `redis_export_fail_total`: {export_results.get('metrics', {}).get('redis_export_fail_total', 0)}",
        f"- `redis_export_batches_total`: {export_results.get('metrics', {}).get('redis_export_batches_total', 0)}",
        f"- `redis_export_keys_written_total`: {export_results.get('metrics', {}).get('redis_export_keys_written_total', 0)}",
        f"- `redis_export_batch_duration_ms`: {export_results.get('metrics', {}).get('redis_export_batch_duration_ms', 0):.2f}",
        "",
        "## Hash Key Verification",
        "",
        f"- **Total Keys Found:** {hash_verification.get('total_keys', 0)}",
        f"- **Sampled:** {hash_verification.get('sampled', 0)}",
        f"- **Passed:** {hash_verification.get('passed', 0)}",
        f"- **Failed:** {hash_verification.get('failed', 0)}",
        ""
    ])
    
    if hash_verification.get("sample_details"):
        lines.append("### Sample Key Details (first 5)")
        lines.append("")
        lines.append("| Key | TTL | Fields | Issues |")
        lines.append("|-----|-----|--------|--------|")
        
        for detail in hash_verification["sample_details"][:5]:
            key_short = detail["key"].split(":")[-1]  # Just symbol
            ttl = detail["ttl"]
            fields = len(detail["fields"])
            issues = ", ".join(detail["issues"]) if detail["issues"] else "None"
            lines.append(f"| {key_short} | {ttl}s | {fields} fields | {issues} |")
        
        lines.append("")
    
    if flat_verification:
        lines.extend([
            "## Flat Mode Cross-Verification",
            "",
            f"- **Symbols Checked:** {flat_verification.get('symbols_checked', 0)}",
            f"- **Matches:** {flat_verification.get('matches', 0)}",
            f"- **Mismatches:** {flat_verification.get('mismatches', 0)}",
            f"- **Missing Flat Keys:** {flat_verification.get('missing_flat', 0)}",
            ""
        ])
        
        if flat_verification.get("details"):
            lines.append("### Cross-Check Details (first 3)")
            lines.append("")
            
            for detail in flat_verification["details"][:3]:
                lines.append(f"**Symbol: {detail['symbol']}**")
                lines.append(f"- Status: {detail['status']}")
                lines.append(f"- Hash data: {detail['hash_data']}")
                lines.append(f"- Flat data: {detail['flat_data']}")
                lines.append("")
    
    lines.extend([
        "## Summary",
        "",
        f"✅ **Verdict: {verdict}**",
        ""
    ])
    
    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    
    print(f"[SMOKE] Report written to: {output_path}")
    
    return verdict


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Redis export smoke check with load testing"
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("artifacts/soak/latest"),
        help="Source directory with ITER_SUMMARY files"
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379/0",
        help="Redis connection URL"
    )
    parser.add_argument(
        "--env",
        type=str,
        default="dev",
        choices=["dev", "staging", "prod"],
        help="Environment namespace"
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="bybit",
        help="Exchange namespace"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Pipeline batch size"
    )
    parser.add_argument(
        "--sample-keys",
        type=int,
        default=10,
        help="Number of keys to sample for verification"
    )
    parser.add_argument(
        "--do-flat-backfill",
        action="store_true",
        help="Run flat mode backfill and cross-verify"
    )
    parser.add_argument(
        "--flat-prefix",
        type=str,
        default=None,
        help="Flat key prefix (default: {env}:{exchange}:shadow:latest:flat)"
    )
    
    args = parser.parse_args()
    
    # Set flat prefix
    if args.flat_prefix is None:
        args.flat_prefix = f"{args.env}:{args.exchange}:shadow:latest:flat"
    
    # Validate source directory
    if not args.src.exists():
        print(f"[ERROR] Source directory not found: {args.src}")
        return 1
    
    # Get Redis client
    print(f"[SMOKE] Connecting to Redis: {args.redis_url}")
    redis_client = get_redis_client(args.redis_url)
    
    if redis_client is None:
        print("[ERROR] Redis unavailable")
        return 1
    
    print("[SMOKE] Redis connected")
    
    # Step 1: Run export (hash mode)
    print("\n" + "=" * 80)
    print("STEP 1: Export (hash mode)")
    print("=" * 80)
    
    exported_count, wall_time_ms, metrics = run_export(
        args.src,
        redis_client,
        args.env,
        args.exchange,
        args.batch_size,
        hash_mode=True
    )
    
    export_results = {
        "exported_count": exported_count,
        "wall_time_ms": wall_time_ms,
        "batch_size": args.batch_size,
        "mode": "hash",
        "metrics": metrics
    }
    
    # Step 2: Scan and verify hash keys
    print("\n" + "=" * 80)
    print("STEP 2: Verify Hash Keys")
    print("=" * 80)
    
    pattern = f"{args.env}:{args.exchange}:shadow:latest:*"
    print(f"[SMOKE] Scanning keys: {pattern}")
    
    hash_keys = scan_keys(redis_client, pattern, limit=1000)
    print(f"[SMOKE] Found {len(hash_keys)} keys")
    
    if hash_keys:
        hash_verification = verify_hash_keys(redis_client, hash_keys, args.sample_keys)
        print(f"[SMOKE] Verification: {hash_verification['status']}")
        print(f"[SMOKE] Passed: {hash_verification['passed']}/{hash_verification['sampled']}")
    else:
        hash_verification = {"status": "FAIL", "reason": "No keys found"}
        print("[ERROR] No keys found for verification")
    
    # Step 3: Optional flat backfill verification
    flat_verification = None
    
    if args.do_flat_backfill:
        print("\n" + "=" * 80)
        print("STEP 3: Flat Backfill Cross-Verification")
        print("=" * 80)
        
        # Run flat export
        print(f"[SMOKE] Running flat backfill to: {args.flat_prefix}")
        flat_count, flat_time_ms, flat_metrics = run_export(
            args.src,
            redis_client,
            args.env,
            args.exchange,
            args.batch_size,
            hash_mode=False
        )
        
        print(f"[SMOKE] Flat exported {flat_count} keys in {flat_time_ms:.2f}ms")
        
        # Cross-verify
        flat_verification = verify_flat_backfill(
            redis_client,
            args.env,
            args.exchange,
            hash_keys,
            args.flat_prefix,
            sample_size=5
        )
        
        print(f"[SMOKE] Cross-verification: {flat_verification['status']}")
        print(f"[SMOKE] Matches: {flat_verification['matches']}/{flat_verification['symbols_checked']}")
    
    # Step 4: Generate report
    print("\n" + "=" * 80)
    print("STEP 4: Generate Report")
    print("=" * 80)
    
    report_path = Path("artifacts/reports/analysis/REDIS_SMOKE_REPORT.md")
    verdict = generate_report(
        report_path,
        export_results,
        hash_verification,
        flat_verification
    )
    
    print(f"\n{'=' * 80}")
    print(f"VERDICT: {verdict}")
    print(f"{'=' * 80}")
    
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

