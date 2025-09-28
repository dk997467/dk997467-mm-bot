"""
F1 deployment gate evaluation logic.

Evaluates D2 walk-forward tuning champion metrics and E2 calibration divergence
against production deployment thresholds.
"""

import copy
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any

from .thresholds import GateThresholds, get_throttle_thresholds, get_canary_gate_thresholds
from src.metrics import exporter as metrics_export


# Parameter whitelist for cfg patches and drift analysis
PARAM_WHITELIST = [
    "k_vola_spread",
    "skew_coeff", 
    "levels_per_side",
    "level_spacing_coeff",
    "min_time_in_book_ms",
    "replace_threshold_bps",
    "imbalance_cutoff"
]


def parse_utc_timestamp(timestamp_str: str) -> datetime:
    """Parse UTC timestamp from various ISO formats."""
    # Handle both with and without 'Z' suffix
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + '+00:00'
    return datetime.fromisoformat(timestamp_str).astimezone(timezone.utc)


def evaluate(wf_report: Dict[str, Any], 
             thresholds: GateThresholds,
             baseline_cfg: Optional[Dict[str, Any]] = None,
             calib_report: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Evaluate D2 + E2 reports against deployment gates.
    
    Args:
        wf_report: D2 walk-forward tuning report.json
        thresholds: Gate thresholds configuration
        baseline_cfg: Optional baseline config for drift analysis
        calib_report: Optional E2 calibration report.json
        
    Returns:
        (ok, reasons, metrics) tuple where:
        - ok: True if all gates pass
        - reasons: List of failure reasons with specific numbers
        - metrics: Dict of all evaluated metrics
    """
    reasons = []
    metrics = {}
    
    # Extract champion aggregates from D2 report
    champion = wf_report.get("champion", {})
    aggregates = champion.get("aggregates", {})
    
    # Core champion metrics
    hit_rate_mean = aggregates.get("hit_rate_mean", 0.0)
    maker_share_mean = aggregates.get("maker_share_mean", 0.0)
    net_pnl_mean_usd = aggregates.get("net_pnl_mean_usd", 0.0)
    cvar95_mean_usd = aggregates.get("cvar95_mean_usd", 0.0)  # Already negative for losses
    win_ratio = aggregates.get("win_ratio", 0.0)
    
    # Store all metrics
    metrics.update({
        "hit_rate_mean": hit_rate_mean,
        "maker_share_mean": maker_share_mean,
        "net_pnl_mean_usd": net_pnl_mean_usd,
        "cvar95_mean_usd": cvar95_mean_usd,
        "win_ratio": win_ratio
    })
    
    # Report age calculation
    now_utc = datetime.now(timezone.utc)
    report_timestamp = None
    
    # Try different timestamp fields
    for field in ["created_at_utc", "generated_at_utc", "report_utc"]:
        if field in wf_report.get("metadata", {}):
            try:
                report_timestamp = parse_utc_timestamp(wf_report["metadata"][field])
                break
            except Exception:
                continue
    
    if report_timestamp:
        report_age_hours = (now_utc - report_timestamp).total_seconds() / 3600
    else:
        report_age_hours = float('inf')  # Force failure if no timestamp
        reasons.append("No valid timestamp found in report metadata")
    
    metrics["report_age_hours"] = report_age_hours
    
    # Parameter drift analysis
    baseline_drift_pct = wf_report.get("baseline_drift_pct", {})
    if baseline_drift_pct:
        # Extract whitelisted parameters only
        whitelisted_drifts = {
            key: abs(drift_pct) 
            for key, drift_pct in baseline_drift_pct.items() 
            if key in PARAM_WHITELIST
        }
        max_drift = max(whitelisted_drifts.values()) if whitelisted_drifts else 0.0
    else:
        max_drift = 0.0
        whitelisted_drifts = {}
    
    metrics["max_param_drift_pct"] = max_drift
    metrics["param_drifts"] = whitelisted_drifts
    
    # E2 calibration divergence (optional)
    sim_live_divergence = None
    if calib_report and "go_no_go" in calib_report:
        divergence_raw = calib_report["go_no_go"].get("sim_live_divergence")
        if divergence_raw is not None:
            # Clamp to [0, 1] range
            sim_live_divergence = max(0.0, min(1.0, float(divergence_raw)))
    
    metrics["sim_live_divergence"] = sim_live_divergence
    
    # Gate evaluations
    if hit_rate_mean < thresholds.min_hit_rate:
        reasons.append(f"Hit rate too low: {hit_rate_mean:.4f} < {thresholds.min_hit_rate:.4f}")
    
    if maker_share_mean < thresholds.min_maker_share:
        reasons.append(f"Maker share too low: {maker_share_mean:.4f} < {thresholds.min_maker_share:.4f}")
    
    if net_pnl_mean_usd < thresholds.min_net_pnl_usd:
        reasons.append(f"Net PnL too low: {net_pnl_mean_usd:.2f} < {thresholds.min_net_pnl_usd:.2f} USD")
    
    # CVaR95 is expected to be negative for losses, so we check absolute value
    if abs(cvar95_mean_usd) > thresholds.max_cvar95_loss_usd:
        reasons.append(f"CVaR95 loss too high: {abs(cvar95_mean_usd):.2f} > {thresholds.max_cvar95_loss_usd:.2f} USD")
    
    if win_ratio < thresholds.min_splits_win_ratio:
        reasons.append(f"Win ratio too low: {win_ratio:.4f} < {thresholds.min_splits_win_ratio:.4f}")
    
    if max_drift > thresholds.max_param_drift_pct:
        reasons.append(f"Parameter drift too high: {max_drift:.1f}% > {thresholds.max_param_drift_pct:.1f}%")
    
    if report_age_hours > thresholds.max_report_age_hours:
        reasons.append(f"Report too old: {report_age_hours:.1f}h > {thresholds.max_report_age_hours:.1f}h")
    
    if sim_live_divergence is not None and sim_live_divergence > thresholds.max_sim_live_divergence:
        reasons.append(f"Sim-live divergence too high: {sim_live_divergence:.3f} > {thresholds.max_sim_live_divergence:.3f}")
    
    # F2 gate — Throttle (use audit-like stats if present in wf_report)
    try:
        audit = wf_report.get('audit', {}) if isinstance(wf_report, dict) else {}
        backoff_max = 0.0
        events_total = 0
        autopolicy_level = 0
        if isinstance(audit, dict):
            backoff_max = float(audit.get('throttle_backoff_ms_max', 0.0))
            ev = audit.get('throttle_events_in_window', {}) or {}
            events_total = int(ev.get('total', 0))
            ap_lv_raw = audit.get('autopolicy_level', None)
            if ap_lv_raw is None:
                # check nested monitor_stats.last_values if present
                try:
                    ap_lv_raw = audit.get('monitor_stats', {}).get('last_values', {}).get('autopolicy_level', 0)
                except Exception:
                    ap_lv_raw = 0
            autopolicy_level = int(ap_lv_raw or 0)
        # Per-symbol throttle thresholds
        symbol = wf_report.get('symbol', 'UNKNOWN') if isinstance(wf_report, dict) else 'UNKNOWN'
        thr = get_throttle_thresholds(str(symbol))
        # Apply gates using per-symbol thresholds
        fail_backoff = False
        fail_events = False
        if backoff_max > float(thr.get('max_throttle_backoff_ms', thresholds.max_throttle_backoff_ms)):
            reasons.append(
                f"Throttle backoff too high: {backoff_max:.0f} > {float(thr.get('max_throttle_backoff_ms', thresholds.max_throttle_backoff_ms)):.0f}"
            )
            fail_backoff = True
        if events_total > int(thr.get('max_throttle_events_in_window_total', thresholds.max_throttle_events_in_window_total)):
            reasons.append(
                f"Throttle events in window too high: {events_total} > {int(thr.get('max_throttle_events_in_window_total', thresholds.max_throttle_events_in_window_total))}"
            )
            fail_events = True
        if autopolicy_level > int(thresholds.max_autopolicy_level_on_promote):
            reasons.append(f"Autopolicy level too high: {autopolicy_level} > {thresholds.max_autopolicy_level_on_promote}")
        metrics['throttle_backoff_ms_max'] = backoff_max
        metrics['throttle_events_in_window_total'] = events_total
        metrics['autopolicy_level'] = autopolicy_level
        metrics['throttle_thresholds_used'] = thr
    except ValueError as ve:
        # Surface invalid per-symbol overrides explicitly
        raise ve
    except Exception:
        # Ignore parsing errors, treat as 0
        metrics['throttle_backoff_ms_max'] = 0.0
        metrics['throttle_events_in_window_total'] = 0

    # Overall result
    # F2 gate — Canary signals
    try:
        canary = wf_report.get('canary', {}) if isinstance(wf_report, dict) else {}
        # snapshot structure expectation:
        # canary: { "killswitch_fired": bool, "drift_alert": bool,
        #           "fills_blue":int, "fills_green":int, "rejects_blue":int, "rejects_green":int,
        #           "latency_ms_avg_blue":float, "latency_ms_avg_green":float }
        thr_cg = get_canary_gate_thresholds(wf_report.get('symbol', 'UNKNOWN') if isinstance(wf_report, dict) else 'UNKNOWN')
        used = {
            "max_reject_delta": float(thr_cg.get('max_reject_delta', 0.02)),
            "max_latency_delta_ms": int(thr_cg.get('max_latency_delta_ms', 50)),
            "min_sample_fills": int(thr_cg.get('min_sample_fills', 500)),
            "drift_cap_pct": float(thr_cg.get('drift_cap_pct', 5.0)),
            "tail_min_sample": int(thr_cg.get('tail_min_sample', 200)),
            "tail_p95_cap_ms": int(thr_cg.get('tail_p95_cap_ms', 50)),
            "tail_p99_cap_ms": int(thr_cg.get('tail_p99_cap_ms', 100)),
            "slo_tail_min_sample": int(thr_cg.get('slo_tail_min_sample', 200)),
            "slo_tail_p95_cap_ms": int(thr_cg.get('slo_tail_p95_cap_ms', 50)),
            "slo_tail_p99_cap_ms": int(thr_cg.get('slo_tail_p99_cap_ms', 100)),
            # M1.1 — Markout gate thresholds
            "markout_min_sample": int(thr_cg.get('markout_min_sample', 50)),
            "markout_cap_bps_200": float(thr_cg.get('markout_cap_bps_200', 0.5)),
            "markout_cap_bps_500": float(thr_cg.get('markout_cap_bps_500', 0.5)),
        }
        metrics['canary_gate_thresholds_used'] = used
        fills_b = int(canary.get('fills_blue', 0))
        fills_g = int(canary.get('fills_green', 0))
        rej_b = int(canary.get('rejects_blue', 0))
        rej_g = int(canary.get('rejects_green', 0))
        lat_b = float(canary.get('latency_ms_avg_blue', 0.0))
        lat_g = float(canary.get('latency_ms_avg_green', 0.0))
        total_fills = fills_b + fills_g
        if total_fills < used['min_sample_fills']:
            # pass due to low sample
            metrics['canary_gate_reasons'] = ["low_sample"]
        else:
            cg_reasons: List[str] = []
            if bool(canary.get('killswitch_fired', False)):
                cg_reasons.append('killswitch_fired')
            if bool(canary.get('drift_alert', False)):
                cg_reasons.append('rollout_drift')
            # compute deltas
            rr_b = rej_b / max(1.0, (rej_b + fills_b))
            rr_g = rej_g / max(1.0, (rej_g + fills_g))
            if (rr_g - rr_b) > used['max_reject_delta']:
                cg_reasons.append('reject_delta_exceeds')
            if (lat_g - lat_b) > used['max_latency_delta_ms']:
                cg_reasons.append('latency_delta_exceeds')
            # Tail-aware reasons with min sample guard
            try:
                s_b = int(canary.get('latency_samples_blue', 0))
                s_g = int(canary.get('latency_samples_green', 0))
                if s_b >= used['tail_min_sample'] and s_g >= used['tail_min_sample']:
                    p95_b = float(canary.get('latency_ms_p95_blue', 0.0))
                    p95_g = float(canary.get('latency_ms_p95_green', 0.0))
                    p99_b = float(canary.get('latency_ms_p99_blue', 0.0))
                    p99_g = float(canary.get('latency_ms_p99_green', 0.0))
                    if (p95_g - p95_b) > used['tail_p95_cap_ms']:
                        cg_reasons.append('latency_tail_p95_exceeds')
                    if (p99_g - p99_b) > used['tail_p99_cap_ms']:
                        cg_reasons.append('latency_tail_p99_exceeds')
            except Exception:
                pass
            # M1.1 — Markout gate evaluation (after reject/latency deltas, before tail)
            try:
                markout_min_sample = int(used.get('markout_min_sample', 50))
                markout_cap_200 = float(used.get('markout_cap_bps_200', 0.5))
                markout_cap_500 = float(used.get('markout_cap_bps_500', 0.5))
                
                # Get markout samples and averages
                markout_200_b = float(canary.get('markout_samples_200_blue', 0))
                markout_200_g = float(canary.get('markout_samples_200_green', 0))
                markout_500_b = float(canary.get('markout_samples_500_blue', 0))
                markout_500_g = float(canary.get('markout_samples_500_green', 0))
                
                # Check if we have enough samples for both horizons
                if (markout_200_b >= markout_min_sample and markout_200_g >= markout_min_sample and
                    markout_500_b >= markout_min_sample and markout_500_g >= markout_min_sample):
                    
                    # Get markout averages
                    markout_200_avg_b = float(canary.get('markout_200_blue_avg_bps', 0.0))
                    markout_200_avg_g = float(canary.get('markout_200_green_avg_bps', 0.0))
                    markout_500_avg_b = float(canary.get('markout_500_blue_avg_bps', 0.0))
                    markout_500_avg_g = float(canary.get('markout_500_green_avg_bps', 0.0))
                    
                    # Calculate deltas (green - blue)
                    delta_200 = markout_200_avg_g - markout_200_avg_b
                    delta_500 = markout_500_avg_g - markout_500_avg_b
                    
                    # Check if markout delta exceeds cap (negative means green is worse)
                    if delta_200 < -markout_cap_200 or delta_500 < -markout_cap_500:
                        cg_reasons.append('markout_delta_exceeds')
            except Exception:
                pass
            
            # SLO tail breaches at the end of ordering (after tail deltas)
            try:
                slo_min = int(used.get('slo_tail_min_sample', 200))
                # Check if latency samples were defined
                if 's_b' in locals() and 's_g' in locals() and s_b >= slo_min and s_g >= slo_min:
                    p95_b = float(canary.get('latency_ms_p95_blue', 0.0))
                    p95_g = float(canary.get('latency_ms_p95_green', 0.0))
                    p99_b = float(canary.get('latency_ms_p99_blue', 0.0))
                    p99_g = float(canary.get('latency_ms_p99_green', 0.0))
                    if p95_g > float(used.get('slo_tail_p95_cap_ms', 50)):
                        cg_reasons.append('slo_tail_p95_breach')
                    if p99_g > float(used.get('slo_tail_p99_cap_ms', 100)):
                        cg_reasons.append('slo_tail_p99_breach')
            except Exception:
                pass
            if cg_reasons:
                reasons.extend([f"canary:{r}" for r in cg_reasons])
            metrics['canary_gate_reasons'] = cg_reasons
    except Exception:
        pass

    ok = len(reasons) == 0
    # Increment F2 gate outcome metrics (stdlib-only counters)
    try:
        symbol_for_metrics = wf_report.get('symbol', 'UNKNOWN') if isinstance(wf_report, dict) else 'UNKNOWN'
        if ok:
            metrics_export.inc_f2_gate_pass(symbol_for_metrics)
        else:
            if 'fail_backoff' in locals() and fail_backoff:
                metrics_export.inc_f2_gate_fail(symbol_for_metrics, 'backoff')
            if 'fail_events' in locals() and fail_events:
                metrics_export.inc_f2_gate_fail(symbol_for_metrics, 'events')
    except Exception:
        pass
    
    return ok, reasons, metrics


def build_cfg_patch(champion_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build configuration patch from champion parameters.
    
    Only includes whitelisted parameters for safe deployment.
    
    Args:
        champion_params: Champion parameters from D2 report
        
    Returns:
        Filtered parameter dictionary ready for deployment
    """
    patch = {}
    
    for key in PARAM_WHITELIST:
        if key in champion_params:
            patch[key] = champion_params[key]
    
    return patch


def make_canary_patch(patch: Dict[str, Any], shrink: float = 0.5, min_levels: int = 1) -> Dict[str, Any]:
    """
    Create conservative canary patch with safety modifications.
    
    Args:
        patch: Full configuration patch
        shrink: Factor to reduce levels_per_side (default 0.5)
        min_levels: Minimum levels to maintain (default 1)
        
    Returns:
        Conservative configuration patch for canary deployment
    """
    canary = copy.deepcopy(patch)
    
    # Reduce market exposure by cutting levels
    if "levels_per_side" in canary:
        original_levels = canary["levels_per_side"]
        canary_levels = max(min_levels, int(original_levels * shrink))
        canary["levels_per_side"] = canary_levels
    
    # Conservative adjustments for safety
    if "level_spacing_coeff" in canary:
        # Increase spacing slightly for wider spreads
        canary["level_spacing_coeff"] = round(canary["level_spacing_coeff"] * 1.1, 6)
    
    if "min_time_in_book_ms" in canary:
        # Increase minimum time for more conservative replacements
        canary["min_time_in_book_ms"] = int(canary["min_time_in_book_ms"] * 1.1)
    
    return canary


def format_thresholds_summary(thresholds: GateThresholds) -> str:
    """Format thresholds for display."""
    return (f"min_hit={thresholds.min_hit_rate:.3f}, "
            f"min_maker={thresholds.min_maker_share:.3f}, "
            f"min_pnl={thresholds.min_net_pnl_usd:.1f}, "
            f"max_cvar95={thresholds.max_cvar95_loss_usd:.1f}, "
            f"min_win={thresholds.min_splits_win_ratio:.3f}, "
            f"max_drift={thresholds.max_param_drift_pct:.1f}%, "
            f"max_age={thresholds.max_report_age_hours:.0f}h, "
            f"max_div={thresholds.max_sim_live_divergence:.3f}")
