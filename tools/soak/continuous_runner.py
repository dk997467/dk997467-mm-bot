#!/usr/bin/env python3
"""
Continuous Soak Mode Runner

Непрерывный цикл анализа soak результатов:
- Анализ windows (analyze_post_soak)
- Экспорт summary + violations в Redis
- Алерты при CRIT/WARN

Usage:
    python -m tools.soak.continuous_runner \
      --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
      --min-windows 24 \
      --interval-min 60 \
      --env dev --exchange bybit \
      --redis-url redis://localhost:6379/0
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Conditional Redis import
try:
    import redis
    from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    RedisConnectionError = Exception
    RedisTimeoutError = Exception
    REDIS_AVAILABLE = False
    logger.warning("Redis library not available, some features will be disabled")


class FileLock:
    """Simple file-based lock with PID tracking."""
    
    def __init__(self, lock_file: Path, stale_hours: int = 6):
        self.lock_file = lock_file
        self.stale_seconds = stale_hours * 3600
        self.pid = os.getpid()
    
    def acquire(self) -> bool:
        """
        Acquire lock. Returns True if successful, False if already locked.
        Auto-cleans stale locks (>6h old).
        """
        if self.lock_file.exists():
            # Check if stale
            age = time.time() - self.lock_file.stat().st_mtime
            if age > self.stale_seconds:
                logger.warning(f"Removing stale lock (age={age:.0f}s)")
                self.lock_file.unlink()
            else:
                # Read PID
                try:
                    pid = int(self.lock_file.read_text())
                    logger.error(f"Lock already held by PID {pid}")
                except Exception:
                    logger.error("Lock file exists but invalid")
                return False
        
        # Create lock
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(str(self.pid))
        logger.info(f"Lock acquired (PID={self.pid})")
        return True
    
    def release(self):
        """Release lock."""
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
                logger.info("Lock released")
            except Exception as e:
                logger.warning(f"Failed to release lock: {e}")


def load_env_file(env_file: Path = Path(".env")):
    """Load .env file if exists."""
    if not env_file.exists():
        return
    
    logger.info(f"Loading {env_file}")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file."""
    if not file_path.exists():
        return ""
    sha = hashlib.sha256()
    sha.update(file_path.read_bytes())
    return sha.hexdigest()


def get_redis_client(redis_url: str) -> Optional[Any]:
    """Get Redis client with graceful fallback."""
    if not REDIS_AVAILABLE:
        return None
    
    try:
        client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"Redis unavailable: {e}")
        return None


def verdict_to_level(verdict: str) -> int:
    """Map verdict to numeric level for comparison."""
    levels = {"OK": 0, "WARN": 1, "CRIT": 2}
    return levels.get(verdict.upper(), 0)


def parse_alert_policy(policy_str: str) -> Dict[str, str]:
    """
    Parse alert policy string.
    
    Example: "dev=WARN,staging=WARN,prod=CRIT" -> {"dev": "WARN", "staging": "WARN", "prod": "CRIT"}
    
    Returns:
        Dict mapping env to min severity
    """
    policy = {}
    if not policy_str:
        return policy
    
    for pair in policy_str.split(','):
        pair = pair.strip()
        if '=' not in pair:
            continue
        env, severity = pair.split('=', 1)
        policy[env.strip()] = severity.strip().upper()
    
    return policy


def get_effective_min_severity(
    env: str,
    alert_policy: Dict[str, str],
    fallback_severity: str
) -> tuple[str, str]:
    """
    Get effective min severity for given env.
    
    Returns:
        (severity, source) where source is "alert-policy" or "alert-min-severity"
    """
    if alert_policy and env in alert_policy:
        return alert_policy[env], "alert-policy"
    return fallback_severity, "alert-min-severity"


def should_send_alert(
    verdict: str,
    min_severity: str,
    redis_client: Optional[Any],
    alert_key: str,
    debounce_min: int,
    dry_run: bool
) -> bool:
    """
    Check if alert should be sent based on severity and debounce.
    
    Returns:
        True if should send, False to skip
    """
    current_level = verdict_to_level(verdict)
    min_level = verdict_to_level(min_severity)
    
    # Check minimum severity
    if current_level < min_level:
        logger.info(f"Alert skipped: {verdict} below min severity {min_severity}")
        return False
    
    # Debounce disabled or Redis unavailable
    if debounce_min <= 0 or not redis_client:
        return True
    
    try:
        # Check last alert state
        last_alert_json = redis_client.get(alert_key)
        if not last_alert_json:
            # First alert
            return True
        
        last_alert = json.loads(last_alert_json)
        last_level = verdict_to_level(last_alert.get("last_level", "OK"))
        last_sent_str = last_alert.get("last_sent_utc", "")
        
        if not last_sent_str:
            return True
        
        last_sent = datetime.fromisoformat(last_sent_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        elapsed_min = (now - last_sent).total_seconds() / 60
        
        # Severity increased - bypass debounce
        if current_level > last_level:
            logger.info(
                f"ALERT_BYPASS_DEBOUNCE prev={last_alert.get('last_level')} "
                f"new={verdict} reason=severity_increase"
            )
            return True
        
        # Same or lower severity - check debounce
        if elapsed_min < debounce_min:
            remaining_min = max(0, int(debounce_min - elapsed_min))
            logger.info(
                f"ALERT_DEBOUNCED level={verdict} last_sent=\"{last_sent_str}\" "
                f"debounce_min={debounce_min} remaining_min={remaining_min} verdict={verdict}"
            )
            return False
        
        return True
    except Exception as e:
        logger.warning(f"Debounce check failed: {e}")
        return True  # Fail open


def record_alert_sent(
    verdict: str,
    redis_client: Optional[Any],
    alert_key: str,
    debounce_min: int,
    dry_run: bool
):
    """Record that an alert was sent (for debounce)."""
    if dry_run or not redis_client:
        logger.info(f"[DRY-RUN] Would record alert: {verdict}")
        return
    
    try:
        now = datetime.now(timezone.utc)
        alert_data = {
            "last_level": verdict,
            "last_sent_utc": now.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        redis_client.setex(alert_key, debounce_min * 60, json.dumps(alert_data))
        logger.info(f"Recorded alert: {verdict} at {alert_data['last_sent_utc']}")
    except Exception as e:
        logger.warning(f"Failed to record alert: {e}")


def write_heartbeat(
    redis_client: Optional[Any],
    heartbeat_key: str,
    interval_min: int
):
    """Write heartbeat to Redis with TTL."""
    if not redis_client:
        logger.warning("Heartbeat skipped: Redis unavailable")
        return
    
    try:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ttl = max(interval_min * 2 * 60, 3600)  # At least 1 hour
        redis_client.setex(heartbeat_key, ttl, now)
        logger.info(f"Heartbeat written: {heartbeat_key} = {now} (TTL={ttl}s)")
    except Exception as e:
        logger.warning(f"Heartbeat write failed: {e}")


def write_export_status(status: Dict[str, Any], state_dir: Path):
    """Write export status marker (atomic)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    status_file = state_dir / "last_export_status.json"
    tmp_file = state_dir / f"last_export_status.json.tmp.{os.getpid()}"
    
    try:
        tmp_file.write_text(json.dumps(status, indent=2))
        tmp_file.replace(status_file)
        logger.info(f"Export status written: {status}")
    except Exception as e:
        logger.warning(f"Failed to write export status: {e}")
        if tmp_file.exists():
            tmp_file.unlink()


def run_analyzer(
    iter_glob: str,
    min_windows: int,
    out_dir: Path,
    exit_on_crit: bool,
    verbose: bool
) -> int:
    """Run analyze_post_soak."""
    logger.info("Running analyzer...")
    
    cmd = [
        sys.executable, "-m", "tools.soak.analyze_post_soak",
        "--iter-glob", iter_glob,
        "--min-windows", str(min_windows),
        "--out-dir", str(out_dir)
    ]
    
    if exit_on_crit:
        cmd.append("--exit-on-crit")
    
    if verbose:
        cmd.append("--verbose")
    
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Analyzer returned {result.returncode}")
            logger.warning(f"stderr: {result.stderr[:500]}")
        else:
            logger.info("Analyzer completed successfully")
        return result.returncode
    except Exception as e:
        logger.error(f"Analyzer failed: {e}")
        return 1


def export_summary_to_redis(
    summary_path: Path,
    env: str,
    exchange: str,
    redis_url: str,
    ttl: int,
    dry_run: bool
) -> bool:
    """Export SOAK_SUMMARY.json to Redis with graceful fallback."""
    if dry_run:
        logger.info("[DRY-RUN] Would export summary to Redis")
        return True
    
    logger.info("Exporting summary to Redis...")
    
    try:
        from tools.soak.export_summary_to_redis import export_summary
        return export_summary(summary_path, env, exchange, redis_url, ttl)
    except Exception as e:
        logger.warning(f"Summary export failed: {e}")
        return False


def export_violations_to_redis(
    summary_path: Path,
    violations_path: Path,
    env: str,
    exchange: str,
    redis_url: str,
    ttl: int,
    stream: bool,
    stream_maxlen: int,
    dry_run: bool
) -> bool:
    """Export violations to Redis."""
    if dry_run:
        logger.info("[DRY-RUN] Would export violations to Redis")
        return True
    
    logger.info("Exporting violations to Redis...")
    
    cmd = [
        sys.executable, "-m", "tools.soak.export_violations_to_redis",
        "--summary", str(summary_path),
        "--violations", str(violations_path),
        "--env", env,
        "--exchange", exchange,
        "--redis-url", redis_url,
        "--ttl", str(ttl)
    ]
    
    if stream:
        cmd.extend(["--stream", "--stream-maxlen", str(stream_maxlen)])
    
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Export violations returned {result.returncode}")
            logger.warning(f"stderr: {result.stderr[:500]}")
            return False
        logger.info("Violations exported successfully")
        return True
    except Exception as e:
        logger.error(f"Export violations failed: {e}")
        return False


def send_telegram_message(token: str, chat_id: str, text: str, dry_run: bool) -> bool:
    """Send Telegram message."""
    if dry_run:
        logger.info(f"[DRY-RUN] Telegram message:\n{text}")
        return True
    
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram alert sent")
            return True
        else:
            logger.warning(f"Telegram failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Telegram error: {e}")
        return False


def send_slack_webhook(webhook_url: str, text: str, dry_run: bool) -> bool:
    """Send Slack webhook message."""
    if dry_run:
        logger.info(f"[DRY-RUN] Slack message:\n{text}")
        return True
    
    try:
        import requests
        payload = {"text": text}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Slack alert sent")
            return True
        else:
            logger.warning(f"Slack failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"Slack error: {e}")
        return False


def build_alert_text(
    summary: Dict[str, Any],
    violations: List[Dict[str, Any]],
    env: str,
    exchange: str
) -> str:
    """Build alert message text."""
    verdict = summary.get("overall", {}).get("verdict", "N/A")
    
    # Emoji badge
    badge = "✅" if verdict == "OK" else ("🟡" if verdict == "WARN" else "🔴")
    
    windows = summary.get("windows", 0)
    symbols_count = len(summary.get("symbols", {}))
    crit_count = summary.get("overall", {}).get("crit_count", 0)
    warn_count = summary.get("overall", {}).get("warn_count", 0)
    
    text = f"[{badge} {verdict}] Soak summary (env={env}, exch={exchange})\n"
    text += f"windows={windows} symbols={symbols_count} crit={crit_count} warn={warn_count}\n"
    
    # Top 3 violations
    if violations:
        text += "\nTop violations:\n"
        for v in violations[:3]:
            symbol = v.get("symbol", "?")
            metric = v.get("metric", "?")
            level = v.get("level", "?")
            value = v.get("value", "?")
            threshold = v.get("threshold", "?")
            window_index = v.get("window_index", "?")
            
            if metric == "edge_bps":
                text += f"- {symbol}: edge_bps < {threshold} at window #{window_index} ({value})\n"
            elif metric == "maker_taker_ratio":
                text += f"- {symbol}: maker/taker < {threshold} at window #{window_index} ({value})\n"
            elif metric == "p95_latency_ms":
                text += f"- {symbol}: p95_latency >= {threshold}ms at window #{window_index} ({value})\n"
            elif metric == "risk_ratio":
                text += f"- {symbol}: risk_ratio >= {threshold} at window #{window_index} ({value})\n"
    
    text += "\nАртефакты: POST_SOAK_ANALYSIS.md, RECOMMENDATIONS.md"
    return text


def send_alerts(
    summary: Dict[str, Any],
    violations: List[Dict[str, Any]],
    env: str,
    exchange: str,
    alert_channels: List[str],
    redis_client: Optional[Any],
    alert_min_severity: str,
    alert_debounce_min: int,
    alert_key: str,
    dry_run: bool
) -> bool:
    """
    Send alerts to configured channels with debounce.
    
    Returns:
        True if alert was sent, False if skipped
    """
    verdict = summary.get("overall", {}).get("verdict", "OK")
    
    # Check if should send (min severity + debounce)
    if not should_send_alert(
        verdict,
        alert_min_severity,
        redis_client,
        alert_key,
        alert_debounce_min,
        dry_run
    ):
        return False
    
    text = build_alert_text(summary, violations, env, exchange)
    
    for channel in alert_channels:
        if channel == "telegram":
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                send_telegram_message(token, chat_id, text, dry_run)
            else:
                logger.warning("Telegram config missing (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
        
        elif channel == "slack":
            webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
            if webhook_url:
                send_slack_webhook(webhook_url, text, dry_run)
            else:
                logger.warning("Slack config missing (SLACK_WEBHOOK_URL)")
    
    # Record that alert was sent
    record_alert_sent(verdict, redis_client, alert_key, alert_debounce_min, dry_run)
    return True


def run_single_cycle(args) -> Dict[str, Any]:
    """Run one analysis cycle."""
    start_time = time.time()
    
    out_dir = Path(args.out_dir)
    summary_path = out_dir / "SOAK_SUMMARY.json"
    violations_path = out_dir / "VIOLATIONS.json"
    state_dir = Path("artifacts/state")
    
    # Get Redis client (for debounce + heartbeat)
    redis_client = get_redis_client(args.redis_url) if not args.dry_run else None
    
    # Parse alert policy and determine effective min severity
    alert_policy = parse_alert_policy(getattr(args, 'alert_policy', ''))
    effective_min_severity, severity_source = get_effective_min_severity(
        args.env,
        alert_policy,
        args.alert_min_severity
    )
    
    # Log alert policy on start
    if args.alert:
        logger.info(
            f"ALERT_POLICY env={args.env} min_severity={effective_min_severity} "
            f"source={severity_source}"
        )
    
    # Check if summary changed (idempotency)
    prev_hash = compute_file_hash(summary_path)
    
    # Step 1: Run analyzer
    exit_code = run_analyzer(
        args.iter_glob,
        args.min_windows,
        out_dir,
        args.exit_on_crit,
        args.verbose
    )
    
    if exit_code != 0 and args.exit_on_crit:
        logger.error("Analyzer failed with critical violations")
        return {"verdict": "FAIL", "duration_ms": (time.time() - start_time) * 1000}
    
    # Check if summary changed
    new_hash = compute_file_hash(summary_path)
    if prev_hash and new_hash == prev_hash:
        logger.info("Summary unchanged, skip export")
        return {
            "verdict": "UNCHANGED",
            "duration_ms": (time.time() - start_time) * 1000
        }
    
    # Load summary & violations
    if not summary_path.exists():
        logger.error("SOAK_SUMMARY.json not found")
        return {"verdict": "FAIL", "duration_ms": (time.time() - start_time) * 1000}
    
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    violations = []
    if violations_path.exists():
        violations = json.loads(violations_path.read_text(encoding="utf-8"))
    
    verdict = summary.get("overall", {}).get("verdict", "N/A")
    windows = summary.get("windows", 0)
    symbols_count = len(summary.get("symbols", {}))
    crit_count = summary.get("overall", {}).get("crit_count", 0)
    warn_count = summary.get("overall", {}).get("warn_count", 0)
    ok_count = summary.get("overall", {}).get("ok_count", 0)
    
    # Track export status
    export_status = {
        "ts": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "summary": "SKIP",
        "violations": "SKIP",
        "reason": ""
    }
    
    # Step 2: Export summary to Redis
    summary_ok = export_summary_to_redis(
        summary_path,
        args.env,
        args.exchange,
        args.redis_url,
        args.ttl,
        args.dry_run
    )
    export_status["summary"] = "OK" if summary_ok else "SKIP"
    if not summary_ok:
        export_status["reason"] = "redis_unavailable"
    
    # Step 3: Export violations to Redis
    violations_ok = export_violations_to_redis(
        summary_path,
        violations_path,
        args.env,
        args.exchange,
        args.redis_url,
        args.ttl,
        args.stream,
        args.stream_maxlen,
        args.dry_run
    )
    export_status["violations"] = "OK" if violations_ok else "SKIP"
    if not violations_ok and not export_status["reason"]:
        export_status["reason"] = "redis_unavailable"
    
    # Log export status
    logger.info(
        f"EXPORT_STATUS summary={export_status['summary']} "
        f"violations={export_status['violations']} reason={export_status['reason']}"
    )
    
    # Write export status marker
    write_export_status(export_status, state_dir)
    
    # Step 4: Send alerts with debounce
    if args.alert:
        alert_key = f"{args.env}:{args.exchange}:{args.alert_key}"
        send_alerts(
            summary,
            violations,
            args.env,
            args.exchange,
            args.alert,
            redis_client,
            effective_min_severity,  # Use policy-based severity
            args.alert_debounce_min,
            alert_key,
            args.dry_run
        )
    
    # Step 5: Write heartbeat
    if hasattr(args, 'heartbeat_key') and args.heartbeat_key:
        heartbeat_key = f"{args.env}:{args.exchange}:{args.heartbeat_key}"
        write_heartbeat(redis_client, heartbeat_key, args.interval_min)
    
    duration_ms = (time.time() - start_time) * 1000
    
    # Log metrics
    logger.info(
        f"CONTINUOUS_METRICS verdict={verdict} windows={windows} symbols={symbols_count} "
        f"crit={crit_count} warn={warn_count} ok={ok_count} duration_ms={duration_ms:.0f}"
    )
    
    return {
        "verdict": verdict,
        "windows": windows,
        "symbols": symbols_count,
        "crit": crit_count,
        "warn": warn_count,
        "ok": ok_count,
        "duration_ms": duration_ms
    }


def main():
    parser = argparse.ArgumentParser(description="Continuous Soak Mode Runner")
    
    parser.add_argument("--iter-glob", required=True, help="Glob pattern for ITER_SUMMARY files")
    parser.add_argument("--min-windows", type=int, default=24, help="Minimum windows (default: 24)")
    parser.add_argument("--out-dir", default="reports/analysis", help="Output directory")
    parser.add_argument("--interval-min", type=int, default=60, help="Interval between cycles (minutes)")
    parser.add_argument("--max-iterations", type=int, default=0, help="Max iterations (0=infinite)")
    parser.add_argument("--exit-on-crit", action="store_true", help="Exit on critical violations")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--exchange", default="bybit", help="Exchange")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0", help="Redis URL")
    parser.add_argument("--ttl", type=int, default=3600, help="TTL for Redis keys (seconds)")
    parser.add_argument("--stream", action="store_true", help="Export violations stream")
    parser.add_argument("--stream-maxlen", type=int, default=5000, help="Stream max length")
    
    parser.add_argument("--lock-file", default="/tmp/soak_continuous.lock", help="Lock file path")
    parser.add_argument("--alert", action="append", choices=["telegram", "slack"], help="Alert channels")
    parser.add_argument("--alert-policy", default="", help="Alert policy per environment (e.g., 'dev=WARN,staging=WARN,prod=CRIT')")
    parser.add_argument("--alert-min-severity", default="CRIT", choices=["OK", "WARN", "CRIT"], help="Minimum severity for alerts (default: CRIT, overridden by --alert-policy if specified)")
    parser.add_argument("--alert-debounce-min", type=int, default=180, help="Alert debounce window in minutes (default: 180, 0=disabled)")
    parser.add_argument("--alert-key", default="soak:alerts:debounce", help="Redis key for alert debounce state")
    parser.add_argument("--heartbeat-key", default="", help="Redis key for runner heartbeat (empty=disabled)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no Redis/alerts)")
    
    args = parser.parse_args()
    
    # Load .env
    load_env_file()
    
    # Acquire lock
    lock = FileLock(Path(args.lock_file))
    if not lock.acquire():
        logger.error("Failed to acquire lock, exiting")
        return 1
    
    try:
        iteration = 0
        
        while True:
            iteration += 1
            logger.info(f"=== Cycle {iteration} ===")
            
            metrics = run_single_cycle(args)
            
            # Check if should stop
            if args.max_iterations > 0 and iteration >= args.max_iterations:
                logger.info(f"Reached max iterations ({args.max_iterations}), exiting")
                break
            
            # Sleep
            if args.max_iterations == 0 or iteration < args.max_iterations:
                sleep_sec = args.interval_min * 60
                logger.info(f"Sleeping {sleep_sec}s...")
                time.sleep(sleep_sec)
    
    finally:
        lock.release()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

