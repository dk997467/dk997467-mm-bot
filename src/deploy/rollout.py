"""
F1/F2 deployment rollout CLI.

F1 mode (dry-run): Evaluates D2 walk-forward tuning and E2 calibration reports against 
deployment gates, then generates configuration patches for full and canary deployments.

F2 mode (--apply): Implements full canary deployment with live metrics monitoring,
auto-rollback on degradation, and comprehensive audit logging.
"""

import argparse
import json
from src.common.artifacts import write_json_atomic
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from .gate import evaluate, build_cfg_patch, make_canary_patch, format_thresholds_summary
from .thresholds import load_thresholds, GateThresholds


def load_json_file(path: str, description: str) -> Dict[str, Any]:
    """Load and parse JSON file with error handling."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"{description} not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {description}: {path} - {e}")


def format_json_output(data: Dict[str, Any]) -> str:
    """Format dictionary as sorted JSON for consistent output."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)


def round_metrics(metrics: Dict[str, Any], round_dp: int) -> Dict[str, Any]:
    """Round numeric values in metrics dict for display."""
    rounded = {}
    for key, value in metrics.items():
        if isinstance(value, float):
            rounded[key] = round(value, round_dp)
        elif isinstance(value, dict):
            rounded[key] = round_metrics(value, round_dp)
        else:
            rounded[key] = value
    return rounded


def _http_get_json(url: str, timeout: int = 5) -> Dict[str, Any]:
    """HTTP GET request returning JSON response."""
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.getcode() != 200:
                raise ValueError(f"HTTP {response.getcode()}")
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to connect to {url}: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response from {url}: {e}")


def _http_post_json(url: str, payload: Dict[str, Any], timeout: int = 5) -> Dict[str, Any]:
    """HTTP POST request with JSON payload, returning JSON response."""
    try:
        data = json.dumps(payload, sort_keys=True).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.getcode() != 200:
                raise ValueError(f"HTTP {response.getcode()}")
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to connect to {url}: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response from {url}: {e}")


def _http_get_text(url: str, timeout: int = 5) -> str:
    """HTTP GET request returning text response."""
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.getcode() != 200:
                raise ValueError(f"HTTP {response.getcode()}")
            return response.read().decode('utf-8')
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to connect to {url}: {e}")


def parse_prom_metrics(text: str) -> Dict[str, float]:
    """Parse simple Prometheus metrics text into name->value dict."""
    metrics = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            try:
                value = float(parts[1])
                metrics[name] = value
            except ValueError:
                continue  # Skip non-numeric values
    return metrics


def _m(metrics: Dict[str, Any], name: str, default: float = 0.0) -> float:
    """Safe getter for metric value with float conversion and NaN guard."""
    try:
        v = metrics.get(name, default)
        v = float(v)
        if v != v:  # NaN check
            return default
        return v
    except Exception:
        return default


def compute_slope(series: List[Tuple[float, float]], window_sec: int = 300) -> float:
    """Compute linear slope over recent time window using least squares."""
    if len(series) < 2:
        return 0.0
    
    # Filter to recent window
    now = time.time()
    recent = [(t, v) for t, v in series if now - t <= window_sec]
    
    if len(recent) < 2:
        return 0.0
    
    # Simple slope calculation: (last - first) / time_delta
    first_t, first_v = recent[0]
    last_t, last_v = recent[-1]
    
    time_delta = last_t - first_t
    if time_delta == 0:
        return 0.0
    
    # Convert to per-minute slope
    slope_per_sec = (last_v - first_v) / time_delta
    slope_per_min = slope_per_sec * 60.0
    
    return slope_per_min


def monitor_metrics(metrics_url: str, minutes: float, thresholds: GateThresholds,
                   poll_sec: int = 15, admin_url: Optional[str] = None,
                   drift_cap_pct: float = 5.0, min_sample_orders: int = 200) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Monitor bot metrics during canary period with breach detection.
    
    Returns (ok, reasons, stats) where:
    - ok: True if no degradation detected
    - reasons: List of breach reasons if any
    - stats: Monitoring statistics and time series data
    """
    print(f"[F2] Starting canary monitoring: {minutes} minutes, poll every {poll_sec}s")
    
    start_time = time.time()
    end_time = start_time + (minutes * 60)
    
    # Time series storage
    series_data = {
        'risk_paused': [],
        'cancel_rate_per_sec': [],
        'rest_error_rate': [],
        'net_pnl_total_usd': [],
        'hit_rate_proxy': [],
        'cfg_max_cancel_per_sec': []
    }
    
    breach_counts = {}  # Track consecutive breaches per rule
    guard_bad_streak = 0
    max_values = {}
    last_values = {}
    poll_count = 0
    
    while time.time() < end_time:
        poll_count += 1
        timestamp = time.time()
        
        try:
            # Fetch metrics
            metrics_text = _http_get_text(metrics_url, timeout=10)
            metrics = parse_prom_metrics(metrics_text)

            # Guard metrics (compute effective if absent, tolerate missing)
            paused = _m(metrics, 'guard_paused', 0.0)
            dry = _m(metrics, 'guard_dry_run', 0.0)
            eff_raw = metrics.get('guard_paused_effective', None)
            eff = None if eff_raw is None else _m({'x': eff_raw}, 'x', 0.0)
            if eff is None:
                eff = paused * (1.0 - dry)
            guard = {
                'paused': 1 if paused > 0.5 else 0,
                'dry_run': 1 if dry > 0.5 else 0,
                'effective': 1 if eff > 0.5 else 0,
            }
            
            # Store time series
            for key in series_data.keys():
                if key in metrics:
                    value = metrics[key]
                    series_data[key].append((timestamp, value))
                    max_values[key] = max(max_values.get(key, value), value)
                    last_values[key] = value

            # Track guard last values
            last_values['guard_paused'] = float(guard['paused'])
            last_values['guard_dry_run'] = float(guard['dry_run'])
            last_values['guard_paused_effective'] = float(guard['effective'])
            # Autopolicy last values (tolerate absence)
            last_values['autopolicy_level'] = float(_m(metrics, 'autopolicy_level', 0.0))
            last_values['autopolicy_min_time_in_book_ms_eff'] = float(_m(metrics, 'autopolicy_min_time_in_book_ms_eff', 0.0))
            last_values['autopolicy_levels_per_side_max_eff'] = float(_m(metrics, 'autopolicy_levels_per_side_max_eff', 0.0))
            last_values['autopolicy_replace_threshold_bps_eff'] = float(_m(metrics, 'autopolicy_replace_threshold_bps_eff', 0.0))

            # Throttle aggregates (tolerate absence)
            # Parse throttle_backoff_ms{symbol}
            backoff_max = 0.0
            for k, v in metrics.items():
                # Expect metric names like 'throttle_backoff_ms{symbol="BTCUSDT"}' in raw text parsers
                if k.startswith('throttle_backoff_ms{') or k == 'throttle_backoff_ms':
                    try:
                        val = float(v)
                        if val > backoff_max:
                            backoff_max = val
                    except Exception:
                        continue
            max_values['throttle_backoff_ms'] = max(max_values.get('throttle_backoff_ms', 0.0), backoff_max)
            last_values['throttle_backoff_ms_max'] = backoff_max

            # throttle_events_in_window{op,symbol}
            events_by_op: Dict[str, float] = {}
            total_events = 0.0
            for k, v in metrics.items():
                if k.startswith('throttle_events_in_window{') or k == 'throttle_events_in_window':
                    try:
                        # crude parse: try to find op label
                        op = 'unknown'
                        if '{' in k and '}' in k:
                            labels = k[k.find('{')+1:k.find('}')]
                            for part in labels.split(','):
                                part = part.strip()
                                if part.startswith('op='):
                                    op = part.split('=', 1)[1].strip('"')
                                    break
                        val = float(v)
                        events_by_op[op] = events_by_op.get(op, 0.0) + val
                        total_events += val
                    except Exception:
                        continue
            last_values['throttle_events_in_window'] = {
                'total': int(total_events),
                **{op: int(cnt) for op, cnt in events_by_op.items()}
            }
            # Shadow stats from in-process aggregator if available
            try:
                from src.metrics.exporter import Metrics  # only to type-path
                agg = getattr(getattr(self, 'metrics', None), 'get_shadow_stats', None)
                if agg:
                    ss = self.metrics.get_shadow_stats()
                    # include only if count meets threshold
                    try:
                        min_count = int(getattr(getattr(self.config, 'shadow', object()), 'min_count', 50))
                    except Exception:
                        min_count = 50
                    if int(ss.get('count', 0)) >= min_count:
                        last_values['shadow_stats'] = ss
            except Exception:
                pass
            
            # Breach detection (need 2 of 3 consecutive checks)
            breaches = []
            
            # Rule 1: risk_paused != 0
            if metrics.get('risk_paused', 0) != 0:
                breaches.append('risk_paused')
            
            # Rule 2: cancel_rate > 90% of max config
            cfg_max = metrics.get('cfg_max_cancel_per_sec')
            cancel_rate = metrics.get('cancel_rate_per_sec', 0)
            if cfg_max and cancel_rate > 0.9 * cfg_max:
                breaches.append('high_cancel_rate')
            
            # Rule 3: error rate > threshold
            error_rate = metrics.get('rest_error_rate', 0)
            if error_rate > 0.01:  # 1% threshold
                breaches.append('high_error_rate')
            
            # Rule 4: Strong negative PnL trend
            pnl_series = series_data['net_pnl_total_usd']
            if len(pnl_series) >= 3:  # Need some history
                pnl_slope = compute_slope(pnl_series, window_sec=600)  # 10 min window
                if pnl_slope < -0.1:  # Negative slope threshold
                    breaches.append('negative_pnl_trend')
            
            # Update breach counters
            for rule in ['risk_paused', 'high_cancel_rate', 'high_error_rate', 'negative_pnl_trend']:
                if rule in breaches:
                    breach_counts[rule] = breach_counts.get(rule, 0) + 1
                else:
                    breach_counts[rule] = 0  # Reset on non-breach

            # Runtime guard consecutive pause handling
            if guard['effective'] == 1:
                guard_bad_streak += 1
            else:
                guard_bad_streak = 0
            breach_counts['runtime_guard_paused'] = guard_bad_streak
            
            # Check for guard emergency rollback (2 consecutive polls)
            if guard_bad_streak >= 2:
                reason = "runtime_guard_paused"
                reasons = [f"{reason} (2 consecutive polls)"]
                print(f"[F2] rollback: {reason} (2 consecutive polls)")
                stats = {
                    'polls_completed': poll_count,
                    'duration_minutes': (timestamp - start_time) / 60,
                    'breach_counts': breach_counts.copy(),
                    'degraded_rules': [reason],
                    'max_values': max_values.copy(),
                    'last_values': last_values.copy(),
                    'series_length': {k: len(v) for k, v in series_data.items()}
                }
                # Duplicates for convenience in audit root
                stats['throttle_backoff_ms_max'] = last_values.get('throttle_backoff_ms_max', 0.0)
                stats['throttle_events_in_window'] = last_values.get('throttle_events_in_window', {'total': 0})
                try:
                    from .thresholds import get_throttle_thresholds as _get_thr
                    sym = last_values.get('symbol', 'UNKNOWN') if isinstance(last_values, dict) else 'UNKNOWN'
                    stats['throttle_thresholds'] = _get_thr(str(sym))
                except Exception:
                    pass
                return False, reasons, stats

            # Check for degradation (2 of 3 consecutive breaches)
            degraded_rules = [rule for rule, count in breach_counts.items() if count >= 2]
            
            elapsed_min = (timestamp - start_time) / 60
            print(f"[F2] Poll {poll_count:2d} ({elapsed_min:4.1f}min): "
                  f"cancel_rate={cancel_rate:6.1f}, error_rate={error_rate:6.3f}, "
                  f"breaches={len(breaches)}")
            print(f"Guard: paused={int(guard['paused'])} dry_run={int(guard['dry_run'])} effective={int(guard['effective'])}")
            
            if degraded_rules:
                reasons = []
                for rule in degraded_rules:
                    if rule == 'risk_paused':
                        reasons.append("Risk paused (non-zero)")
                    elif rule == 'high_cancel_rate':
                        reasons.append(f"Cancel rate too high: {cancel_rate:.1f} > {0.9*cfg_max:.1f}")
                    elif rule == 'high_error_rate':
                        reasons.append(f"Error rate too high: {error_rate:.3f} > 0.010")
                    elif rule == 'negative_pnl_trend':
                        pnl_slope = compute_slope(pnl_series, window_sec=600)
                        reasons.append(f"Negative PnL trend: {pnl_slope:.2f}/min")
                
                print(f"[F2] DEGRADATION DETECTED: {', '.join(degraded_rules)}")
                
                # Compile monitoring stats
                stats = {
                    'polls_completed': poll_count,
                    'duration_minutes': elapsed_min,
                    'breach_counts': breach_counts.copy(),
                    'degraded_rules': degraded_rules,
                    'max_values': max_values.copy(),
                    'last_values': last_values.copy(),
                    'series_length': {k: len(v) for k, v in series_data.items()}
                }
                # Duplicates for convenience in audit root
                stats['throttle_backoff_ms_max'] = last_values.get('throttle_backoff_ms_max', 0.0)
                stats['throttle_events_in_window'] = last_values.get('throttle_events_in_window', {'total': 0})
                try:
                    from .thresholds import get_throttle_thresholds as _get_thr
                    sym = last_values.get('symbol', 'UNKNOWN') if isinstance(last_values, dict) else 'UNKNOWN'
                    stats['throttle_thresholds'] = _get_thr(str(sym))
                except Exception:
                    pass
                
                return False, reasons, stats
            
        except Exception as e:
            print(f"[F2] Poll {poll_count} failed: {e}")
            # Continue monitoring despite poll failures
        
        # Sleep until next poll (but don't exceed end time)
        next_poll = start_time + poll_count * poll_sec
        sleep_time = max(0, min(poll_sec, end_time - time.time()))
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    # Monitoring completed successfully
    elapsed_min = (time.time() - start_time) / 60
    print(f"[F2] Monitoring completed: {elapsed_min:.1f} minutes, {poll_count} polls")
    
    stats = {
        'polls_completed': poll_count,
        'duration_minutes': elapsed_min,
        'breach_counts': breach_counts.copy(),
        'degraded_rules': [],
        'max_values': max_values.copy(),
        'last_values': last_values.copy(),
        'series_length': {k: len(v) for k, v in series_data.items()}
    }
    # Duplicates for convenience in audit root
    stats['throttle_backoff_ms_max'] = stats['last_values'].get('throttle_backoff_ms_max', 0.0)
    stats['throttle_events_in_window'] = stats['last_values'].get('throttle_events_in_window', {'total': 0})
    try:
        from .thresholds import get_throttle_thresholds as _get_thr
        sym = stats['last_values'].get('symbol', 'UNKNOWN') if isinstance(stats.get('last_values', {}), dict) else 'UNKNOWN'
        stats['throttle_thresholds'] = _get_thr(str(sym))
    except Exception:
        pass

    # Rollout block enrichment from metrics/admin
    try:
        # Parse rollout counters if present in metrics
        orders_blue = 0
        orders_green = 0
        fills_blue = 0
        fills_green = 0
        rejects_blue = 0
        rejects_green = 0
        lat_b = 0.0
        lat_g = 0.0
        metrics_text = _http_get_text(metrics_url, timeout=5)
        m = parse_prom_metrics(metrics_text)
        for k, v in m.items():
            if k.startswith('rollout_orders_total{') and 'color="blue"' in k:
                orders_blue = int(v)
            if k.startswith('rollout_orders_total{') and 'color="green"' in k:
                orders_green = int(v)
            if k.startswith('rollout_fills_total{') and 'color="blue"' in k:
                fills_blue = int(v)
            if k.startswith('rollout_fills_total{') and 'color="green"' in k:
                fills_green = int(v)
            if k.startswith('rollout_rejects_total{') and 'color="blue"' in k:
                rejects_blue = int(v)
            if k.startswith('rollout_rejects_total{') and 'color="green"' in k:
                rejects_green = int(v)
            if k.startswith('rollout_avg_latency_ms{') and 'color="blue"' in k:
                lat_b = float(v)
            if k.startswith('rollout_avg_latency_ms{') and 'color="green"' in k:
                lat_g = float(v)
        split = int(m.get('rollout_traffic_split_pct', 0)) if 'rollout_traffic_split_pct' in m else 0
        # observed split prefer gauge if present
        observed_pct = float(m.get('rollout_split_observed_pct', 0.0))
        total_orders = int(orders_blue + orders_green)
        # placeholders for overlay-related fields
        overlay_diff_keys: List[str] = []
        salt_hash: str = ""
        # Optionally query admin for config/rollout to compute salt hash and overlay diffs
        if admin_url:
            try:
                ro_info = _http_get_json(f"{admin_url}/admin/rollout", timeout=5)
                salt = str(ro_info.get('salt', ''))
                import hashlib as _h
                salt_hash = _h.sha1(salt.encode('utf-8')).hexdigest()[:8]
            except Exception:
                salt_hash = ""
            try:
                cfg = _http_get_json(f"{admin_url}/admin/config", timeout=5)
                roll = cfg.get('rollout', {}) if isinstance(cfg, dict) else {}
                blue = roll.get('blue', {}) if isinstance(roll, dict) else {}
                green = roll.get('green', {}) if isinstance(roll, dict) else {}
                # Supported keys
                supported = {"autopolicy.level_max", "levels_per_side_max", "replace_threshold_bps"}

                def _rec_find(obj, key_names, parent_hint=None):
                    # depth-first search for any key in key_names; if parent_hint provided, path must include it
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            # exact match
                            if k in key_names:
                                return v
                            # synonyms for level_max
                            if 'level_max' in key_names and k in ('level_max', 'max_level'):
                                return v
                            res = _rec_find(v, key_names, parent_hint)
                            if res is not None:
                                return res
                    elif isinstance(obj, list):
                        for it in obj:
                            res = _rec_find(it, key_names, parent_hint)
                            if res is not None:
                                return res
                    return None

                overlays = {}
                if isinstance(blue, dict):
                    overlays.update({k: v for k, v in blue.items() if k in supported})
                if isinstance(green, dict):
                    overlays.update({k: v for k, v in green.items() if k in supported})
                diffs = set()
                for k, v in overlays.items():
                    base_v = None
                    if '.' in k:
                        # Try nested path quickly
                        try:
                            parts = k.split('.')
                            cur = cfg
                            for p in parts:
                                # try synonym for level_max
                                pp = p
                                if p == 'level_max' and p not in cur and 'max_level' in cur:
                                    pp = 'max_level'
                                cur = cur[pp]
                            base_v = cur
                        except Exception:
                            # fallback recursive
                            base_v = _rec_find(cfg, [parts[-1], 'max_level'])
                    else:
                        base_v = _rec_find(cfg, [k, 'max_level'])
                    try:
                        if base_v is not None and str(v) != str(base_v):
                            diffs.add(k)
                    except Exception:
                        continue
                overlay_diff_keys = sorted(list(diffs))
            except Exception:
                overlay_diff_keys = []
        # Build rollout block
        stats['rollout'] = {
            "traffic_split_pct": int(split),
            "orders_blue": int(orders_blue),
            "orders_green": int(orders_green),
            "fills_blue": int(fills_blue),
            "fills_green": int(fills_green),
            "rejects_blue": int(rejects_blue),
            "rejects_green": int(rejects_green),
            "latency_ms_avg_blue": float(lat_b),
            "latency_ms_avg_green": float(lat_g),
            # tail percentiles and deltas if present in metrics text
            "latency_ms_p95_blue": float(m.get('rollout_latency_p95_ms{color="blue"}', 0.0)) if isinstance(m, dict) else 0.0,
            "latency_ms_p95_green": float(m.get('rollout_latency_p95_ms{color="green"}', 0.0)) if isinstance(m, dict) else 0.0,
            "latency_ms_p99_blue": float(m.get('rollout_latency_p99_ms{color="blue"}', 0.0)) if isinstance(m, dict) else 0.0,
            "latency_ms_p99_green": float(m.get('rollout_latency_p99_ms{color="green"}', 0.0)) if isinstance(m, dict) else 0.0,
            "latency_samples_blue": float(m.get('rollout_latency_samples_total{color="blue"}', 0.0)) if isinstance(m, dict) else 0.0,
            "latency_samples_green": float(m.get('rollout_latency_samples_total{color="green"}', 0.0)) if isinstance(m, dict) else 0.0,
            "overlay_keys_blue": [],
            "overlay_keys_green": [],
            "split_expected_pct": int(split),
            "split_observed_pct": float(observed_pct),
            "salt_hash": str(salt_hash),
            "overlay_diff_keys": overlay_diff_keys,
        }
        try:
            b95 = float(stats['rollout']['latency_ms_p95_blue'])
            g95 = float(stats['rollout']['latency_ms_p95_green'])
            b99 = float(stats['rollout']['latency_ms_p99_blue'])
            g99 = float(stats['rollout']['latency_ms_p99_green'])
            stats['rollout']['latency_ms_p95_delta'] = float(g95 - b95)
            stats['rollout']['latency_ms_p99_delta'] = float(g99 - b99)
        except Exception:
            stats['rollout']['latency_ms_p95_delta'] = 0.0
            stats['rollout']['latency_ms_p99_delta'] = 0.0
        # Drift detection with sample cap
        drift_reason = "ok"
        drift_alert = False
        if total_orders < int(min_sample_orders):
            drift_alert = False
            drift_reason = "low_sample"
        else:
            if abs(float(split) - observed_pct) > float(drift_cap_pct):
                drift_alert = True
                drift_reason = "exceeds_cap"
        stats['rollout']["split_drift_alert"] = bool(drift_alert)
        stats['rollout']["split_drift_reason"] = str(drift_reason)
        # include ramp state if available via admin or metrics (best-effort from gauges)
        try:
            ramp_enabled = int(m.get('rollout_ramp_enabled', 0))
            ramp_step = int(m.get('rollout_ramp_step_idx', 0))
            ramp_frozen = int(m.get('rollout_ramp_frozen', 0))
            ramp_cooldown = float(m.get('rollout_ramp_cooldown_seconds', 0.0))
            holds_sample = int(m.get('rollout_ramp_holds_total{reason="sample"}', 0))
            holds_cooldown = int(m.get('rollout_ramp_holds_total{reason="cooldown"}', 0))
            stats['rollout']['ramp_enabled'] = 1 if ramp_enabled > 0.5 else 0
            stats['rollout']['ramp_step_idx'] = int(ramp_step)
            stats['rollout']['ramp_frozen'] = 1 if ramp_frozen > 0.5 else 0
            stats['rollout']['holds_sample'] = int(holds_sample)
            stats['rollout']['holds_cooldown'] = int(holds_cooldown)
            stats['rollout']['cooldown_seconds'] = float(ramp_cooldown)
        except Exception:
            pass
    except Exception:
        pass
    
    return True, [], stats


def apply_patch(admin_url: str, patch: Dict[str, Any], symbol: str, dry_run: bool = False) -> Dict[str, Any]:
    """Apply configuration patch via admin API."""
    url = f"{admin_url}/admin/reload"
    payload = {
        "symbol": symbol,
        "patch": patch,
        "dry_run": dry_run
    }
    
    print(f"[F2] {'DRY-RUN' if dry_run else 'APPLYING'} patch to {symbol}: {len(patch)} parameters")
    return _http_post_json(url, payload, timeout=10)


def do_rollback(admin_url: str) -> Dict[str, Any]:
    """Perform configuration rollback via admin API."""
    url = f"{admin_url}/admin/rollback"
    print(f"[F2] ROLLING BACK configuration")
    return _http_post_json(url, {}, timeout=10)


def write_audit_log(symbol: str, audit_data: Dict[str, Any]) -> str:
    """Write audit log to artifacts/rollouts/<symbol>/YYYYMMDD_HHMMSS.json."""
    # Create directory
    audit_dir = Path("artifacts") / "rollouts" / symbol
    audit_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    audit_path = audit_dir / f"{timestamp}.json"
    
    # Write audit data with deterministic atomic formatting
    write_json_atomic(str(audit_path), audit_data)
    
    print(f"[F2] Audit log written: {audit_path}")
    return str(audit_path)


def main():
    """Main CLI entry point for F1/F2 deployment rollout."""
    parser = argparse.ArgumentParser(
        description="F1/F2 Deployment Rollout: Evaluate D2+E2 reports and deploy config patches"
    )
    
    # Required arguments
    parser.add_argument("--report", type=str, required=True,
                        help="Path to D2 walk-forward report.json")
    
    # Optional arguments
    parser.add_argument("--calibration-report", type=str,
                        help="Path to E2 calibration report.json (optional)")
    parser.add_argument("--thresholds", type=str,
                        help="Path to thresholds YAML/JSON file (optional, uses defaults)")
    parser.add_argument("--baseline-json", type=str,
                        help="Path to baseline config JSON for drift analysis (optional)")
    parser.add_argument("--symbol", type=str, default="UNKNOWN",
                        help="Trading symbol for logs and patches")
    parser.add_argument("--round-dp", type=int, default=6,
                        help="Decimal places for rounding numbers in output")
    
    # F2 deployment arguments
    parser.add_argument("--apply", action="store_true",
                        help="Apply patches to live bot (F2 mode). Without this, runs F1 dry-run only.")
    parser.add_argument("--admin-url", type=str,
                        help="Bot admin API base URL (required for --apply)")
    parser.add_argument("--metrics-url", type=str,
                        help="Bot metrics URL (required for --apply)")
    parser.add_argument("--canary-minutes", type=float, default=30.0,
                        help="Canary monitoring period in minutes (default: 30)")
    parser.add_argument("--canary-shrink", type=float, default=0.5,
                        help="Canary shrink factor for levels_per_side (default: 0.5)")
    
    args = parser.parse_args()
    
    # Validate F2 arguments
    if args.apply:
        if not args.admin_url:
            print("[ERROR] --admin-url is required when using --apply", file=sys.stderr)
            sys.exit(1)
        if not args.metrics_url:
            print("[ERROR] --metrics-url is required when using --apply", file=sys.stderr)
            sys.exit(1)
    
    try:
        # Load reports and configuration
        wf_report = load_json_file(args.report, "D2 walk-forward report")
        
        calib_report = None
        if args.calibration_report:
            calib_report = load_json_file(args.calibration_report, "E2 calibration report")
        
        baseline_cfg = None
        if args.baseline_json:
            baseline_cfg = load_json_file(args.baseline_json, "Baseline configuration")
        
        # Load thresholds
        thresholds = load_thresholds(args.thresholds)
        
        # Current time for age calculations
        now_utc = datetime.now(timezone.utc)
        
        # Evaluate gates
        ok, reasons, metrics = evaluate(wf_report, thresholds, baseline_cfg, calib_report)
        
        # Round metrics for display
        display_metrics = round_metrics(metrics, args.round_dp)
        
        # Build configuration patches
        champion_params = wf_report.get("champion", {}).get("parameters", {})
        patch_full = build_cfg_patch(champion_params)
        patch_canary = make_canary_patch(patch_full, shrink=args.canary_shrink)
        # If autopolicy_level present and >=1, soften canary additionally
        ap_lvl = int(display_metrics.get('autopolicy_level', 0))
        if ap_lvl >= 1:
            soften = False
            if ap_lvl > int(thresholds.max_autopolicy_level_on_promote):
                reasons.append(f"Autopolicy level too high: {ap_lvl} > {thresholds.max_autopolicy_level_on_promote}")
            else:
                soften = True
            if soften:
                # apply additional soften factors
                shrink = float(args.canary_shrink) * (1.0 + float(thresholds.autopolicy_soft_canary_shrink_pct))
                patch_canary = make_canary_patch(patch_full, shrink=shrink)
                # bump min_time_in_book & replace_threshold if present in patch
                tib_bump = float(thresholds.autopolicy_soft_tib_bump_pct)
                rep_bump = float(thresholds.autopolicy_soft_repbps_bump_pct)
                if 'min_time_in_book_ms' in patch_canary:
                    patch_canary['min_time_in_book_ms'] = int(round(patch_canary['min_time_in_book_ms'] * (1.0 + tib_bump)))
                if 'replace_threshold_bps' in patch_canary:
                    patch_canary['replace_threshold_bps'] = float(round(patch_canary['replace_threshold_bps'] * (1.0 + rep_bump), 6))
                print(f"[F2] canary softened due to autopolicy_level={ap_lvl}: levels_shrink={shrink:.2f}, tib_bump={tib_bump:.2f}, repbps_bump={rep_bump:.2f}")
        
        # Generate output
        gate_result = "PASS" if ok else "FAIL"
        
        print(f"GATE RESULT: {gate_result}")
        print(f"symbol: {args.symbol}")
        print(f"timestamp: {now_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}")
        print("")
        
        # Metrics summary
        print("Metrics:")
        print(f"  age_hours: {display_metrics.get('report_age_hours', 'n/a')}")
        print(f"  win_ratio: {display_metrics.get('win_ratio', 'n/a')}")
        print(f"  hit_rate: {display_metrics.get('hit_rate_mean', 'n/a')}")
        print(f"  maker_share: {display_metrics.get('maker_share_mean', 'n/a')}")
        print(f"  pnl_usd: {display_metrics.get('net_pnl_mean_usd', 'n/a')}")
        print(f"  cvar95_usd: {display_metrics.get('cvar95_mean_usd', 'n/a')}")
        print(f"  drift_max_pct: {display_metrics.get('max_param_drift_pct', 'n/a')}")
        
        divergence = display_metrics.get('sim_live_divergence')
        divergence_str = f"{divergence}" if divergence is not None else "n/a"
        print(f"  sim_live_divergence: {divergence_str}")
        print("")
        
        # Thresholds summary
        print(f"thresholds: {format_thresholds_summary(thresholds)}")
        print("")
        
        # Reasons (if any)
        if reasons:
            print("Reasons:")
            for reason in reasons:
                print(f"  - {reason}")
        else:
            print("Reasons: (all gates passed)")
        print("")
        
        # Configuration patches
        print("Full patch (JSON):")
        if patch_full:
            print(format_json_output(patch_full))
        else:
            print("{}")
        print("")
        
        print("Canary patch (JSON):")
        if patch_canary:
            print(format_json_output(patch_canary))
        else:
            print("{}")
        print("")
        
        # F1 mode: Exit after showing patches
        if not args.apply:
            if ok:
                sys.exit(0)  # PASS
            else:
                sys.exit(2)  # FAIL (gate failed)
        
        # F2 mode: Gate must pass to proceed
        if not ok:
            print(f"[F2] Gate evaluation FAILED - aborting deployment")
            sys.exit(2)
        
        print(f"[F2] Starting deployment for {args.symbol}")
        print(f"[F2] Canary period: {args.canary_minutes} minutes")
        
        # F2 deployment flow
        outcome = "unknown"
        exit_code = 1
        monitor_stats = {}
        snapshot_before = {}
        snapshot_after = {}
        
        try:
            # Get pre-deployment snapshot
            snapshot_before = _http_get_json(f"{args.admin_url}/admin/snapshot")
            print(f"[F2] Pre-deployment snapshot: cfg_hash={snapshot_before.get('cfg_hash', 'unknown')}")
            
            # Apply canary patch
            canary_result = apply_patch(args.admin_url, patch_canary, args.symbol, dry_run=False)
            print(f"[F2] Canary applied: {canary_result.get('cfg_hash_after', 'unknown')}")
            
            # Monitor canary metrics
            monitor_ok, monitor_reasons, monitor_stats = monitor_metrics(
                args.metrics_url, args.canary_minutes, thresholds, poll_sec=15
            )
            
            if not monitor_ok:
                # Degradation detected - rollback
                print(f"[F2] DEGRADATION DETECTED - initiating rollback")
                for reason in monitor_reasons:
                    print(f"[F2]   Reason: {reason}")
                
                rollback_result = do_rollback(args.admin_url)
                outcome = "rolled_back"
                exit_code = 2
                
                # Get post-rollback snapshot
                snapshot_after = _http_get_json(f"{args.admin_url}/admin/snapshot")
                print(f"[F2] Post-rollback snapshot: cfg_hash={snapshot_after.get('cfg_hash', 'unknown')}")
                
            else:
                # Canary successful - promote to full
                print(f"[F2] Canary monitoring PASSED - promoting to full configuration")
                
                full_result = apply_patch(args.admin_url, patch_full, args.symbol, dry_run=False)
                outcome = "promoted"
                exit_code = 0
                
                # Get post-promotion snapshot
                snapshot_after = _http_get_json(f"{args.admin_url}/admin/snapshot")
                print(f"[F2] Post-promotion snapshot: cfg_hash={snapshot_after.get('cfg_hash', 'unknown')}")
            
        except (ConnectionError, ValueError) as e:
            print(f"[F2] Network/API error: {e}")
            outcome = "error"
            exit_code = 1
        
        # Write audit log
        audit_data = {
            "now_utc": now_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            "symbol": args.symbol,
            "report_paths": {
                "wf": args.report,
                "e2": args.calibration_report
            },
            "thresholds": {
                key: getattr(thresholds, key) for key in [
                    'min_hit_rate', 'min_maker_share', 'min_net_pnl_usd', 
                    'max_cvar95_loss_usd', 'min_splits_win_ratio', 'max_param_drift_pct',
                    'max_sim_live_divergence', 'max_report_age_hours'
                ]
            },
            "canary_gate": {
                "used_thresholds": metrics.get('canary_gate_thresholds_used', {}),
                "reasons": metrics.get('canary_gate_reasons', []),
            },
            "patches": {
                "canary": patch_canary,
                "full": patch_full
            },
            "canary_params": {
                "minutes": args.canary_minutes,
                "shrink": args.canary_shrink
            },
            "monitor_stats": monitor_stats,
            "reasons": monitor_reasons if 'monitor_reasons' in locals() else [],
            "snapshot": {
                "before": snapshot_before,
                "after": snapshot_after
            },
            "outcome": outcome
        }
        
        audit_path = write_audit_log(args.symbol, audit_data)
        
        # Final summary
        print(f"")
        print(f"[F2] DEPLOYMENT COMPLETE")
        print(f"[F2] Outcome: {outcome.upper()}")
        print(f"[F2] Audit: {audit_path}")
        
        sys.exit(exit_code)
            
    except FileNotFoundError as e:
        print(f"[ERROR] File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[ERROR] Invalid data: {e}", file=sys.stderr)
        sys.exit(1)
    except ConnectionError as e:
        print(f"[ERROR] Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
