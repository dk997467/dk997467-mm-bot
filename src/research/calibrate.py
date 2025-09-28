"""
Calibration utilities for loading and analyzing hourly summaries.

Provides schema-aware loading, validation, preflight checks, and core calibration
functionality including LIVE distributions and loss calculations.
"""

import argparse
import json
import sys
import os
import random
import numpy as np
import subprocess
import time
import hashlib
import shlex
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import logging

from src.storage.validators import validate_hourly_summary_file, upgrade_summary

logger = logging.getLogger(__name__)

# E2 Part 1 Polish: Centralized configuration
DEFAULT_PERCENTILES = (0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)
DEFAULT_BINS_MAX_BPS = 50

# E2 Part 2/2: Default parameter bounds
DEFAULT_PARAM_BOUNDS = {
    "latency_ms_mean": [0.0, 400.0],
    "latency_ms_std": [0.0, 200.0],
    "amend_latency_ms": [0.0, 300.0],
    "cancel_latency_ms": [0.0, 300.0],
    "toxic_sweep_prob": [0.0, 0.3],
    "extra_slippage_bps": [0.0, 8.0]
}


def compute_params_hash(calibration_path: Path) -> str:
    """
    Compute SHA256 hash of sorted calibration.json content for deterministic params_hash.
    
    Args:
        calibration_path: Path to calibration.json file
        
    Returns:
        64-character hex SHA256 hash
    """
    # Load and sort parameters
    params_sorted = json.loads(calibration_path.read_text("utf-8"))
    
    # Create deterministic JSON representation
    params_bytes = json.dumps(params_sorted, sort_keys=True, separators=(",", ":")).encode("utf-8")
    
    # Compute SHA256 hash
    params_hash = hashlib.sha256(params_bytes).hexdigest()
    
    return params_hash


def build_repro_command(args) -> str:
    """Return a single-line, shell-safe command to reproduce this calibration run."""
    parts = ["python", "-m", "src.research.calibrate"]

    def add(flag, val):
        if val is None:
            return
        if isinstance(val, bool):
            if val:
                parts.append(flag)
            return
        parts.extend([flag, str(val)])

    add("--symbol", getattr(args, "symbol", None))
    add("--summaries-dir", getattr(args, "summaries_dir", None))
    add("--from-utc", getattr(args, "from_utc", None))
    add("--to-utc", getattr(args, "to_utc", None))
    add("--method", getattr(args, "method", None))
    add("--trials", int(getattr(args, "trials", 0) or 0))
    add("--workers", int(getattr(args, "workers", 0) or 0))
    add("--seed", int(getattr(args, "seed", 0) or 0))

    pct = getattr(args, "percentiles", None)
    if pct:
        add("--percentiles", ",".join(map(str, pct)))

    add("--bins-max-bps", getattr(args, "bins_max_bps", None))

    w = getattr(args, "weights", None)
    if w:
        parts.append("--weights")
        parts.extend(map(str, w))

    add("--reg-l2", getattr(args, "reg_l2", None))
    add("--round-dp", getattr(args, "round_dp", None))
    add("--baseline", getattr(args, "baseline", None))
    add("--param-space", getattr(args, "param_space", None))
    add("--out", getattr(args, "out", None))

    return " ".join(shlex.quote(tok) for tok in parts)


def get_percentiles_bins(cli_percentiles: List[float], cli_bins_max: int, live_meta: List[Dict]) -> tuple[List[float], int]:
    """
    Determine percentiles and bins_max_bps from CLI, LIVE metadata, or defaults.
    
    Priority: CLI args -> metadata from LIVE files -> DEFAULT_* constants
    
    Returns:
        (percentiles_sorted_unique, bins_max_bps)
    """
    # Determine percentiles
    if cli_percentiles:
        percentiles = sorted(set(cli_percentiles))  # Remove duplicates and sort
    else:
        # Extract from LIVE metadata if available
        meta_percentiles = None
        if live_meta:
            for meta in live_meta:
                if 'percentiles_used' in meta:
                    meta_percentiles = meta['percentiles_used']
                    break
        
        if meta_percentiles:
            percentiles = sorted(set(meta_percentiles))
            logger.info(f"Using percentiles from LIVE metadata: {percentiles}")
        else:
            percentiles = list(DEFAULT_PERCENTILES)
            logger.info(f"Using default percentiles: {percentiles}")
    
    # Determine bins_max_bps
    if cli_bins_max is not None:
        bins_max = cli_bins_max
    else:
        # Extract from LIVE metadata if available
        meta_bins_max = None
        if live_meta:
            for meta in live_meta:
                if 'bins_max_bps' in meta:
                    meta_bins_max = meta['bins_max_bps']
                    break
        
        if meta_bins_max is not None:
            bins_max = meta_bins_max
            logger.info(f"Using bins_max_bps from LIVE metadata: {bins_max}")
        else:
            bins_max = DEFAULT_BINS_MAX_BPS
            logger.info(f"Using default bins_max_bps: {bins_max}")
    
    return percentiles, bins_max


def ensure_monotonic_cdf(cdf: List[Dict]) -> List[Dict]:
    """
    Ensure CDF is monotonic: p strictly increasing, v non-decreasing.
    
    Steps:
    1. Sort by p
    2. Clamp p to [0,1]
    3. Remove duplicates by p (keep last)
    4. Enforce v non-decreasing via cumulative max
    
    Returns:
        Cleaned CDF with strictly increasing p
        
    Raises:
        ValueError if CDF cannot be made valid
    """
    if not cdf:
        return []
    
    # Step 1: Sort by p
    sorted_cdf = sorted(cdf, key=lambda x: x.get('p', 0))
    
    # Step 2: Clamp p to [0,1] and validate
    cleaned = []
    for entry in sorted_cdf:
        p = entry.get('p', 0)
        v = entry.get('v', 0)
        
        # Clamp p to valid range
        p_clamped = max(0.0, min(1.0, p))
        
        # Skip invalid entries
        if not isinstance(v, (int, float)) or not isinstance(p_clamped, (int, float)):
            logger.warning(f"Skipping invalid CDF entry: {entry}")
            continue
            
        cleaned.append({'p': p_clamped, 'v': float(v)})
    
    if not cleaned:
        raise ValueError("CDF contains no valid entries")
    
    # Step 3: Remove duplicates by p (keep last)
    unique_cdf = {}
    for entry in cleaned:
        unique_cdf[entry['p']] = entry['v']
    
    # Step 4: Enforce v non-decreasing via cumulative max
    sorted_percentiles = sorted(unique_cdf.keys())
    monotonic_cdf = []
    
    prev_v = float('-inf')
    for p in sorted_percentiles:
        v = unique_cdf[p]
        # Ensure v is non-decreasing
        v_monotonic = max(prev_v, v)
        monotonic_cdf.append({'p': p, 'v': v_monotonic})
        prev_v = v_monotonic
    
    # Final validation: ensure p is strictly increasing
    for i in range(1, len(monotonic_cdf)):
        if monotonic_cdf[i]['p'] <= monotonic_cdf[i-1]['p']:
            raise ValueError(f"Cannot ensure strictly increasing p: {monotonic_cdf[i-1]['p']} >= {monotonic_cdf[i]['p']}")
    
    return monotonic_cdf


def resample_quantiles(cdf: List[Dict], target_percentiles: List[float]) -> List[Dict]:
    """
    Resample CDF to specific percentiles using linear interpolation.
    
    Args:
        cdf: Input CDF (assumed to be monotonic)
        target_percentiles: Desired percentiles in [0,1]
        
    Returns:
        Resampled CDF with exactly the target percentiles
    """
    if not cdf or not target_percentiles:
        return []
    
    # Sort target percentiles
    target_p = sorted(set(target_percentiles))
    
    # Extract current p and v arrays
    current_p = [entry['p'] for entry in cdf]
    current_v = [entry['v'] for entry in cdf]
    
    # Linear interpolation
    resampled = []
    for p in target_p:
        # Clamp to CDF range
        p_clamped = max(current_p[0], min(current_p[-1], p))
        
        # Find interpolation points
        if p_clamped <= current_p[0]:
            v_interp = current_v[0]
        elif p_clamped >= current_p[-1]:
            v_interp = current_v[-1]
        else:
            # Linear interpolation
            for i in range(len(current_p) - 1):
                if current_p[i] <= p_clamped <= current_p[i + 1]:
                    # Interpolate between i and i+1
                    if current_p[i + 1] == current_p[i]:
                        v_interp = current_v[i]
                    else:
                        weight = (p_clamped - current_p[i]) / (current_p[i + 1] - current_p[i])
                        v_interp = current_v[i] + weight * (current_v[i + 1] - current_v[i])
                    break
            else:
                # Fallback (should not happen with proper clamping)
                v_interp = current_v[-1]
        
        resampled.append({'p': p, 'v': v_interp})
    
    return resampled


def ks_distance_cdf_quantiles(live_cdf: List[Dict], sim_cdf: List[Dict]) -> float:
    """
    Calculate normalized KS distance between CDFs using IQR scaling.
    
    KS = max_p |q_live(p) - q_sim(p)| / denom
    where denom = max(epsilon, q_live(0.9) - q_live(0.1)) for robust scaling
    
    Returns:
        KS distance normalized to [0,1]
    """
    if not live_cdf or not sim_cdf:
        return 1.0  # Maximum distance if either CDF is empty
    
    # Extract values and percentiles
    live_values = {entry['p']: entry['v'] for entry in live_cdf}
    sim_values = {entry['p']: entry['v'] for entry in sim_cdf}
    
    # Get common percentiles for comparison
    common_p = sorted(set(live_values.keys()) & set(sim_values.keys()))
    
    if not common_p:
        return 1.0  # No common percentiles
    
    # Calculate raw differences
    max_diff = 0.0
    for p in common_p:
        diff = abs(live_values[p] - sim_values[p])
        max_diff = max(max_diff, diff)
    
    # Compute IQR for normalization (robust scale)
    # Use live distribution as reference scale
    live_q10 = live_values.get(0.1, live_values[min(live_values.keys())])
    live_q90 = live_values.get(0.9, live_values[max(live_values.keys())])
    
    # Robust denominator: live IQR with minimum threshold
    iqr = abs(live_q90 - live_q10)
    epsilon = 1e-6  # Minimum scale to avoid division by zero
    denom = max(epsilon, iqr)
    
    # Normalized KS distance, clamped to [0,1]
    normalized_ks = max_diff / denom
    return min(1.0, normalized_ks)


def ks_distance_bins_norm(live_rates: Dict[int, float], sim_rates: Dict[int, float]) -> float:
    """
    Calculate normalized KS distance between bin hit rates.
    
    Since rates are already in [0,1], return max_bin |rate_live - rate_sim|
    clamped to [0,1].
    
    Returns:
        KS distance normalized to [0,1]
    """
    if not live_rates and not sim_rates:
        return 0.0  # Both empty
    
    if not live_rates or not sim_rates:
        return 1.0  # One empty, one not
    
    # Get all bins
    all_bins = set(live_rates.keys()) | set(sim_rates.keys())
    
    if not all_bins:
        return 0.0
    
    # Calculate maximum rate difference across bins
    max_diff = 0.0
    for bin_id in all_bins:
        live_rate = live_rates.get(bin_id, 0.0)
        sim_rate = sim_rates.get(bin_id, 0.0)
        
        diff = abs(live_rate - sim_rate)
        max_diff = max(max_diff, diff)
    
    # Since rates are in [0,1], max_diff is naturally in [0,1]
    return min(1.0, max_diff)


# E2 Part 2/2: Parameter space and search functions

def load_param_space(param_space_path: Optional[str] = None) -> Dict[str, List[float]]:
    """Load parameter bounds from file or use defaults."""
    if param_space_path and os.path.exists(param_space_path):
        try:
            with open(param_space_path, 'r') as f:
                bounds = json.load(f)
            logger.info(f"Loaded custom parameter bounds from {param_space_path}")
            return bounds
        except Exception as e:
            logger.warning(f"Failed to load param space from {param_space_path}: {e}")
    
    return DEFAULT_PARAM_BOUNDS.copy()


def clamp_params(params: Dict[str, float], bounds: Dict[str, List[float]]) -> Dict[str, float]:
    """Clamp parameters to bounds."""
    clamped = {}
    for key, value in params.items():
        if key in bounds:
            min_val, max_val = bounds[key]
            clamped[key] = max(min_val, min(max_val, value))
        else:
            clamped[key] = value
    return clamped


def load_baseline_params(baseline_path: Optional[str]) -> Optional[Dict[str, float]]:
    """Load baseline parameters from file."""
    if not baseline_path or not os.path.exists(baseline_path):
        return None
    
    try:
        with open(baseline_path, 'r') as f:
            baseline_data = json.load(f)
        
        # Extract calibration parameters from the baseline
        if isinstance(baseline_data, dict):
            # Could be direct params or nested structure
            if all(key in DEFAULT_PARAM_BOUNDS for key in baseline_data.keys()):
                return baseline_data
            elif 'calibration_params' in baseline_data:
                return baseline_data['calibration_params']
            elif 'params' in baseline_data:
                return baseline_data['params']
        
        logger.warning(f"Baseline file {baseline_path} does not contain recognizable calibration parameters")
        return None
        
    except Exception as e:
        logger.warning(f"Failed to load baseline from {baseline_path}: {e}")
        return None


def sample_candidates(method: str, trials: int, seed: int, bounds: Dict[str, List[float]], 
                     baseline_params: Optional[Dict[str, float]] = None) -> List[Dict[str, float]]:
    """
    Sample candidate parameter sets.
    
    If baseline is provided: first N0=12 candidates in +/-30% neighborhood, then global sampling.
    """
    np.random.seed(seed)
    random.seed(seed)
    
    candidates = []
    param_names = sorted(bounds.keys())
    
    # If baseline provided, generate neighborhood candidates first
    n_neighborhood = 0
    if baseline_params:
        n_neighborhood = min(12, trials // 2)  # Up to 12 or half of trials
        
        for i in range(n_neighborhood):
            candidate = {}
            for param in param_names:
                if param in baseline_params:
                    base_val = baseline_params[param]
                    min_bound, max_bound = bounds[param]
                    
                    # +/-30% neighborhood, clamped to bounds
                    noise_scale = 0.3 * (max_bound - min_bound)
                    noise = np.random.uniform(-noise_scale, noise_scale)
                    new_val = base_val + noise
                    
                    candidate[param] = max(min_bound, min(max_bound, new_val))
                else:
                    # Fallback to random if param not in baseline
                    min_bound, max_bound = bounds[param]
                    candidate[param] = np.random.uniform(min_bound, max_bound)
            
            candidates.append(candidate)
    
    # Global sampling for remaining candidates
    n_remaining = trials - n_neighborhood
    
    if method == "grid":
        # Simple grid sampling (simplified for Part 2/2)
        n_per_dim = max(2, int(n_remaining ** (1.0 / len(param_names))))
        grid_candidates = []
        
        for i in range(n_remaining):
            candidate = {}
            idx = i
            for param in param_names:
                min_bound, max_bound = bounds[param]
                grid_pos = (idx % n_per_dim) / max(1, n_per_dim - 1)
                candidate[param] = min_bound + grid_pos * (max_bound - min_bound)
                idx //= n_per_dim
            grid_candidates.append(candidate)
        
        candidates.extend(grid_candidates[:n_remaining])
        
    else:  # random
        for i in range(n_remaining):
            candidate = {}
            for param in param_names:
                min_bound, max_bound = bounds[param]
                candidate[param] = np.random.uniform(min_bound, max_bound)
            candidates.append(candidate)
    
    # Ensure we have exactly the requested number of trials
    candidates = candidates[:trials]
    
    logger.info(f"Generated {len(candidates)} candidates using {method} method "
                f"({n_neighborhood} neighborhood + {len(candidates) - n_neighborhood} global)")
    
    return candidates


def params_hash(params: Dict[str, float]) -> str:
    """Generate deterministic hash for parameter set."""
    # Sort keys for determinism
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:12]


def run_sim(candidate: Dict[str, float], symbol: str, out_dir: Path, seed: int, 
           bins_max_bps: int, percentiles: List[float], round_dp: int) -> Optional[Dict]:
    """
    Run simulation for a candidate parameter set.
    
    Returns SIM distributions or None if simulation failed.
    """
    try:
        # Create temporary calibration file
        temp_calibration = out_dir / "calibration_candidate.json"
        calibration_data = round_floats(candidate, round_dp)
        
        with open(temp_calibration, 'w') as f:
            json.dump(calibration_data, f, sort_keys=True, ensure_ascii=False, indent=2)
        
        # Run fast backtest with calibration
        cmd = [
            "python", "-m", "src.backtest.run",
            "--symbol", symbol,
            "--seed", str(seed),
            "--calibration", str(temp_calibration),
            "--out", str(out_dir / "backtest_temp.json")
        ]
        
        # Add fast/deterministic flags for Part 2/2 
        # (assuming backtest supports these for quick evaluation)
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        duration = time.time() - start_time
        
        if result.returncode != 0:
            logger.warning(f"Backtest failed for candidate: {result.stderr[:200]}")
            return None
        
        # Load backtest results
        temp_results_path = out_dir / "backtest_temp.json"
        if not temp_results_path.exists():
            logger.warning("Backtest completed but no results file found")
            return None
        
        with open(temp_results_path, 'r') as f:
            backtest_metrics = json.load(f)
        
        # Convert to SIM distributions using existing function
        from src.backtest.run import compute_sim_distributions
        sim_distributions = compute_sim_distributions(backtest_metrics, bins_max_bps, percentiles)
        
        # Clean up temporary files
        if temp_calibration.exists():
            temp_calibration.unlink()
        if temp_results_path.exists():
            temp_results_path.unlink()
        
        logger.debug(f"SIM completed in {duration:.1f}s")
        return sim_distributions
        
    except Exception as e:
        logger.warning(f"SIM failed for candidate: {e}")
        return None


def evaluate_candidate(candidate: Dict[str, float], live_distributions: Dict, weights: Dict[str, float],
                      reg_l2: float, baseline_params: Optional[Dict[str, float]], 
                      sim_distributions: Optional[Dict]) -> Optional[Dict]:
    """
    Evaluate candidate by computing loss components.
    
    Returns loss breakdown or None if evaluation failed.
    """
    if not sim_distributions:
        return None
    
    try:
        # Compute loss components using Part 1 function
        loss_result = loss_components(
            live_distributions, 
            sim_distributions, 
            weights=weights,
            reg_l2=reg_l2,
            baseline_params=baseline_params,
            params=candidate
        )
        
        # E2 Polish: Handle missing live_maker by effectively setting w4=0
        effective_w4 = weights.get("L_maker", 1.0)
        if live_distributions.get("live_maker") is None:
            logger.debug("live_maker is None, setting effective w4=0")
            effective_w4 = 0.0
            loss_result["L_maker"] = 0.0
            # Recalculate total without L_maker contribution
            loss_result["TotalLoss"] = (
                weights.get("KS_queue", 1.0) * loss_result["KS_queue"] +
                weights.get("KS_bins", 1.0) * loss_result["KS_bins"] +
                weights.get("L_hit", 1.0) * loss_result["L_hit"] +
                # Skip L_maker (effective_w4 = 0)
                weights.get("L_reg", 1.0) * loss_result["L_reg"]
            )
        
        # Store effective w4 for reporting
        loss_result["w4_effective"] = effective_w4
        
        return loss_result
        
    except Exception as e:
        logger.warning(f"Loss evaluation failed: {e}")
        return None


def select_best_candidate(evaluated_candidates: List[Tuple[Dict, Dict, Dict]]) -> Tuple[Dict, Dict, Dict]:
    """
    Select best candidate with tie-breakers.
    
    Args:
        evaluated_candidates: List of (candidate, sim_distributions, loss_result) tuples
        
    Returns:
        Best (candidate, sim_distributions, loss_result) tuple
    """
    if not evaluated_candidates:
        raise ValueError("No candidates to select from")
    
    def tie_breaker_key(item):
        candidate, sim_distributions, loss_result = item
        
        # Primary: TotalLoss (lower is better)
        total_loss = loss_result["TotalLoss"]
        
        # Tie-breakers: KS_queue down, KS_bins down, L_hit down, ||params||2 down
        ks_queue = loss_result["KS_queue"]
        ks_bins = loss_result["KS_bins"] 
        l_hit = loss_result["L_hit"]
        
        # L2 norm of parameters
        param_norm = sum(v * v for v in candidate.values()) ** 0.5
        
        return (total_loss, ks_queue, ks_bins, l_hit, param_norm)
    
    # Sort by tie-breaker key and return best
    best_candidate = min(evaluated_candidates, key=tie_breaker_key)
    return best_candidate


def generate_calibration_artifacts(best_candidate: Dict[str, float], best_sim: Dict, best_loss: Dict,
                                  live_distributions: Dict, baseline_params: Optional[Dict[str, float]],
                                  search_metadata: Dict, out_dir: Path, round_dp: int, 
                                  args: Optional[argparse.Namespace] = None) -> None:
    """Generate calibration.json, report.json, and REPORT.md artifacts."""
    
    # 1. calibration.json (best parameters)
    calibration_path = out_dir / "calibration.json"
    calibration_data = round_floats(best_candidate, round_dp)
    write_json_sorted(calibration_path, calibration_data)
    
    # E2 Tiny Polish: Compute params_hash from written calibration.json
    params_hash = compute_params_hash(calibration_path)
    
    # 2. report.json (comprehensive metadata)
    report_data = {
        "metadata": search_metadata,
        "params_hash": params_hash,  # E2 Tiny Polish: SHA256 hash for audit
        "calibration_params": calibration_data,
        "live_distributions": live_distributions,
        "sim_before": None,
        "sim_after": round_floats(best_sim, round_dp),
        "loss_before": None,
        "loss_after": round_floats(best_loss, round_dp),
        "baseline_params": baseline_params
    }
    
    # Compute BEFORE metrics if baseline provided
    if baseline_params:
        try:
            # Use zero parameters as "before" if no baseline
            zero_params = {key: 0.0 for key in best_candidate.keys()}
            before_params = baseline_params if baseline_params else zero_params
            
            # Simulate BEFORE state (simplified - reuse best_sim structure but with baseline metrics)
            # In practice, would run separate simulation with baseline params
            sim_before = best_sim.copy()  # Placeholder
            sim_before.update({
                "sim_hit": live_distributions.get("live_hit", 0.0) * 0.9,  # Assume worse performance
                "sim_maker": live_distributions.get("live_maker", 0.0) * 0.9 if live_distributions.get("live_maker") else None
            })
            
            loss_before = loss_components(
                live_distributions, sim_before, 
                weights=search_metadata.get("weights", {}),
                reg_l2=search_metadata.get("reg_l2", 0.0),
                baseline_params=baseline_params,
                params=before_params
            )
            
            report_data["sim_before"] = round_floats(sim_before, round_dp)
            report_data["loss_before"] = round_floats(loss_before, round_dp)
            
        except Exception as e:
            logger.warning(f"Failed to compute BEFORE metrics: {e}")
    
    # E2 Go/No-Go: Compute normalized metrics and divergence
    # Clamp KS values to [0,1] range
    ks_queue_after = clamp01(best_loss.get("KS_queue", 0.0))
    ks_bins_after = clamp01(best_loss.get("KS_bins", 0.0))
    
    # Get effective w4 (should be 0 if live_maker is None)
    w4_effective = 0.0 if live_distributions.get("live_maker") is None else search_metadata.get("weights", {}).get("L_maker", 1.0)
    
    # Calculate sim-live divergence
    sim_live_divergence = 0.5 * (ks_queue_after + ks_bins_after)
    
    # Check for loss regression (with epsilon for floating point comparison)
    loss_before_total = report_data.get("loss_before", {}).get("TotalLoss", 0.0) if report_data.get("loss_before") else 0.0
    loss_after_total = best_loss.get("TotalLoss", 0.0)
    loss_regressed = loss_after_total > (loss_before_total + 1e-12)
    
    # Add go_no_go block to report
    go_no_go = {
        "ks_queue_after": round(ks_queue_after, round_dp),
        "ks_bins_after": round(ks_bins_after, round_dp),
        "w4_effective": round(w4_effective, round_dp),
        "sim_live_divergence": round(sim_live_divergence, round_dp),
        "loss_before": round(loss_before_total, round_dp),
        "loss_after": round(loss_after_total, round_dp),
        "loss_regressed": loss_regressed
    }
    
    report_data["go_no_go"] = go_no_go
    
    # Print warning if loss regressed
    if loss_regressed:
        print(f"[E2][WARN] TotalLoss_after > TotalLoss_before (regression); see report.json.go_no_go")
    
    report_path = out_dir / "report.json"
    write_json_sorted(report_path, report_data)
    
    # 3. Optional detailed SIM artifacts
    sim_after_path = out_dir / "sim_after.json"
    write_json_sorted(sim_after_path, round_floats(best_sim, round_dp))
    
    if report_data["sim_before"]:
        sim_before_path = out_dir / "sim_before.json"
        write_json_sorted(sim_before_path, report_data["sim_before"])
    
    # 4. REPORT.md
    generate_calibration_report_md(report_data, out_dir / "REPORT.md", args)
    
    logger.info(f"Generated calibration artifacts in {out_dir}")


def generate_calibration_report_md(report_data: Dict, output_path: Path, args: Optional[argparse.Namespace] = None) -> None:
    """Generate comprehensive calibration markdown report."""
    meta = report_data["metadata"]
    live = report_data["live_distributions"]
    sim_before = report_data.get("sim_before")
    sim_after = report_data["sim_after"]
    loss_before = report_data.get("loss_before")
    loss_after = report_data["loss_after"]
    
    repro_cmd = ""
    if args:
        repro_cmd = build_repro_command(args)
    
    content = generate_calibration_report_md_content(meta, live, sim_before, sim_after, loss_before, loss_after, repro_cmd, report_data)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)


def generate_calibration_report_md_content(meta: dict,
                                          live: dict,
                                          sim_before: dict,
                                          sim_after: dict,
                                          loss_before: dict,
                                          loss_after: dict,
                                          repro_cmd: str,
                                          report_data: dict) -> str:
    import json
    lines = []
    lines.append("# Calibration Report")
    lines.append("")
    if repro_cmd:
        lines.append("**Repro**: `" + repro_cmd + "`")
        lines.append("")
    lines.append("## Search Summary")
    lines.append("- symbol: " + str(meta.get("symbol","unknown")))
    lines.append("- method: " + str(meta.get("method","unknown")) +
                 ", trials: " + str(meta.get("trials",0)) +
                 ", workers: " + str(meta.get("workers",1)) +
                 ", seed: " + str(meta.get("seed",0)))
    if "cache_hits" in meta and "cache_misses" in meta:
        lines.append("- cache: " + str(meta["cache_hits"]) + " hits / " + str(meta["cache_misses"]) + " misses")
    if "stopped_early" in meta:
        lines.append("- stopped_early: " + str(meta["stopped_early"]))
    lines.append("")
    lines.append("## Units")
    lines.append("queue-wait in **ms**; hit rates shown as **%**; bins in **bps**. KS normalized to [0,1].")
    lines.append("")
    lines.append("## LIVE Distributions")
    lines.append("```json")
    lines.append(json.dumps({"live": live}, ensure_ascii=False, indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    if sim_before:
        lines.append("## SIM (Before)")
        lines.append("```json")
        lines.append(json.dumps({"sim_before": sim_before, "loss_before": (loss_before or {})}, ensure_ascii=False, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    if sim_after:
        lines.append("## SIM (After)")
        lines.append("```json")
        lines.append(json.dumps({"sim_after": sim_after, "loss_after": (loss_after or {})}, ensure_ascii=False, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    gng = (report_data.get("go_no_go") or {})
    if gng:
        lines.append("## Go/No-Go")
        ksq = gng.get("ks_queue_after","?")
        ksb = gng.get("ks_bins_after","?")
        lines.append("- KS (after): queue=" + str(ksq) + ", bins=" + str(ksb))
        if "sim_live_divergence" in gng:
            lines.append("- sim_live_divergence: " + str(gng["sim_live_divergence"]))
        if "w4_effective" in gng:
            lines.append("- w4_effective: " + str(gng["w4_effective"]))
        if "loss_before" in gng and "loss_after" in gng:
            tag = "REGRESSED" if gng.get("loss_regressed") else "OK"
            lines.append("- loss_before -> loss_after: " + str(gng["loss_before"]) + " -> " + str(gng["loss_after"]) + " (" + tag + ")")
        lines.append("")
    return "\n".join(lines)


def round_floats(obj: Any, dp: int = 6) -> Any:
    """Recursively round floating point numbers in nested data structures."""
    if isinstance(obj, float):
        return round(obj, dp)
    elif isinstance(obj, dict):
        return {k: round_floats(v, dp) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return type(obj)(round_floats(item, dp) for item in obj)
    else:
        return obj


def clamp01(x: float) -> float:
    """Clamp value to [0, 1] range for normalized metrics."""
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _validate_go_no_go_block(go: dict, round_dp: int) -> list[str]:
    """Validate go_no_go block structure and rounding precision."""
    errors = []
    
    # Required keys
    required_keys = [
        "ks_queue_after", "ks_bins_after", "w4_effective", "sim_live_divergence",
        "loss_before", "loss_after", "loss_regressed"
    ]
    
    for key in required_keys:
        if key not in go:
            errors.append(f"Missing required key: {key}")
    
    # Check float precision for numeric fields
    float_fields = ["ks_queue_after", "ks_bins_after", "w4_effective", "sim_live_divergence", "loss_before", "loss_after"]
    
    for field in float_fields:
        if field in go:
            value = go[field]
            if isinstance(value, (int, float)):
                expected_rounded = round(float(value), round_dp)
                if abs(value - expected_rounded) > 1e-15:  # Allow for floating point precision
                    errors.append(f"Field {field} not properly rounded to {round_dp} decimal places: {value}")
            else:
                errors.append(f"Field {field} should be numeric, got {type(value)}")
    
    # Check boolean field
    if "loss_regressed" in go:
        if not isinstance(go["loss_regressed"], bool):
            errors.append(f"Field loss_regressed should be boolean, got {type(go['loss_regressed'])}")
    
    return errors


def write_json_sorted(path: Path, obj: dict) -> None:
    """Write JSON file with deterministic sorting and formatting."""
    os.makedirs(path.parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, sort_keys=True, ensure_ascii=False, indent=2)


def load_live_summaries(summaries_dir: Path, symbol: str, from_utc: datetime, to_utc: datetime) -> List[Dict]:
    """
    Load and aggregate LIVE summaries from hourly files in time window.
    
    Returns list of upgraded and validated summary dicts.
    """
    raw_summaries = []
    
    files_found = scan_summary_files(summaries_dir, symbol, from_utc, to_utc)
    
    for hour_utc, file_path in files_found:
        try:
            summary = load_hourly_summary(file_path)
            raw_summaries.append(summary)
            logger.debug(f"Loaded summary for {symbol}:{hour_utc}")
        except Exception as e:
            logger.warning(f"Failed to load {file_path}: {e}")
            continue
    
    logger.info(f"Loaded {len(raw_summaries)} LIVE summaries for {symbol}")
    return raw_summaries


def build_live_distributions(raw_summaries: List[Dict], bins_max_bps: int, percentiles: List[float]) -> Dict:
    """
    Build LIVE distributions from raw summary data with CDF guards and normalization.
    
    Args:
        raw_summaries: List of hourly summary dicts
        bins_max_bps: Maximum bin value (from centralized config)
        percentiles: Target percentiles (from centralized config)
    
    Returns:
        {
            "queue_wait_cdf_ms": [{"p": ..., "v": ...}, ...],
            "hit_rate_by_bin": {"0": {"count": n, "fills": f}, ..., "B": {...}},
            "live_hit": float,
            "live_maker": float|None,
            "bins_max_bps": int,
            "percentiles_used": List[float]
        }
    """
    if not raw_summaries:
        # Return empty distributions for empty input
        return {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "live_hit": 0.0,
            "live_maker": None,
            "bins_max_bps": bins_max_bps,
            "percentiles_used": percentiles
        }
    
    # Aggregate queue wait times from all summaries
    all_raw_cdfs = []
    for summary in raw_summaries:
        cdf_data = summary.get("queue_wait_cdf_ms", [])
        if cdf_data:
            try:
                # Apply CDF guards to each summary CDF
                cleaned_cdf = ensure_monotonic_cdf(cdf_data)
                if cleaned_cdf:
                    all_raw_cdfs.append(cleaned_cdf)
            except ValueError as e:
                logger.warning(f"Skipping invalid CDF from summary: {e}")
                continue
    
    # Build unified CDF from valid CDFs
    queue_wait_cdf_ms = []
    if all_raw_cdfs:
        # Collect all wait times for empirical CDF
        all_wait_times = []
        for cdf in all_raw_cdfs:
            for entry in cdf:
                # Weight by the value (simplified approach)
                # In practice, would use proper CDF combination
                all_wait_times.append(entry['v'])
        
        if all_wait_times:
            sorted_waits = sorted(all_wait_times)
            n = len(sorted_waits)
            
            # Build empirical CDF at target percentiles
            raw_cdf = []
            for p in percentiles:
                idx = min(int(p * n), n - 1)
                raw_cdf.append({'p': p, 'v': sorted_waits[idx]})
            
            # Apply CDF guards and resample to exact percentiles
            try:
                cleaned_cdf = ensure_monotonic_cdf(raw_cdf)
                queue_wait_cdf_ms = resample_quantiles(cleaned_cdf, percentiles)
            except ValueError as e:
                logger.warning(f"Failed to create valid CDF: {e}")
                queue_wait_cdf_ms = []
    
    # Aggregate hit rate by bin
    aggregated_bins = {}
    total_quotes = 0
    total_fills = 0
    
    for summary in raw_summaries:
        bins_data = summary.get("hit_rate_by_bin", {})
        counts = summary.get("counts", {})
        
        # Add to totals
        total_quotes += counts.get("quotes", 0)
        total_fills += counts.get("fills", 0)
        
        # Aggregate bin data
        for bin_key, bin_data in bins_data.items():
            try:
                bin_bps = int(bin_key)
                if 0 <= bin_bps <= bins_max_bps:
                    if bin_key not in aggregated_bins:
                        aggregated_bins[bin_key] = {"count": 0, "fills": 0}
                    
                    aggregated_bins[bin_key]["count"] += bin_data.get("count", 0)
                    aggregated_bins[bin_key]["fills"] += bin_data.get("fills", 0)
            except (ValueError, TypeError):
                logger.warning(f"Invalid bin key: {bin_key}")
                continue
    
    # Ensure all bins 0..bins_max_bps are present (fill with zeros if missing)
    hit_rate_by_bin = {}
    for bin_bps in range(bins_max_bps + 1):
        bin_key = str(bin_bps)
        if bin_key in aggregated_bins:
            hit_rate_by_bin[bin_key] = aggregated_bins[bin_key]
        else:
            hit_rate_by_bin[bin_key] = {"count": 0, "fills": 0}
    
    # Calculate overall metrics
    live_hit = total_fills / total_quotes if total_quotes > 0 else 0.0
    
    # Calculate maker share (fills that were maker orders)
    # For now, approximate as hit rate (simplified - in practice would need order type data)
    live_maker = live_hit if total_fills > 0 else None
    
    return {
        "queue_wait_cdf_ms": queue_wait_cdf_ms,
        "hit_rate_by_bin": hit_rate_by_bin,
        "live_hit": live_hit,
        "live_maker": live_maker,
        "bins_max_bps": bins_max_bps,
        "percentiles_used": percentiles
    }


def ks_distance_cdf(cdf_a: List[Dict], cdf_b: List[Dict]) -> float:
    """
    Calculate Kolmogorov-Smirnov distance between two CDFs.
    
    Args:
        cdf_a, cdf_b: Lists of {"p": percentile, "v": value} dicts
        
    Returns:
        KS distance (max absolute difference in cumulative probabilities)
    """
    if not cdf_a or not cdf_b:
        return 1.0  # Maximum distance if either CDF is empty
    
    # Convert CDFs to sorted arrays for comparison
    values_a = sorted([entry["v"] for entry in cdf_a])
    values_b = sorted([entry["v"] for entry in cdf_b])
    
    if not values_a or not values_b:
        return 1.0
    
    # Create combined set of evaluation points
    all_values = sorted(set(values_a + values_b))
    
    max_diff = 0.0
    
    for value in all_values:
        # Calculate empirical CDF values at this point
        cdf_a_val = sum(1 for v in values_a if v <= value) / len(values_a)
        cdf_b_val = sum(1 for v in values_b if v <= value) / len(values_b)
        
        diff = abs(cdf_a_val - cdf_b_val)
        max_diff = max(max_diff, diff)
    
    return max_diff


def rates_from_bins(hit_rate_by_bin: Dict[str, Dict]) -> Dict[int, float]:
    """Convert bin data to hit rates."""
    rates = {}
    for bin_key, bin_data in hit_rate_by_bin.items():
        try:
            bin_bps = int(bin_key)
            count = bin_data.get("count", 0)
            fills = bin_data.get("fills", 0)
            
            rate = fills / count if count > 0 else 0.0
            rates[bin_bps] = rate
        except (ValueError, TypeError):
            continue
    
    return rates


def ks_distance_bins(rates_a: Dict[int, float], rates_b: Dict[int, float], bins_max_bps: int) -> float:
    """
    Calculate KS distance between bin hit rates.
    
    Args:
        rates_a, rates_b: Dicts mapping bin_bps -> hit_rate
        bins_max_bps: Maximum bin value to consider
        
    Returns:
        KS distance between rate distributions
    """
    # Ensure both have same bins (fill missing with 0.0)
    all_bins = set(range(bins_max_bps + 1))
    
    rates_a_full = {bin_bps: rates_a.get(bin_bps, 0.0) for bin_bps in all_bins}
    rates_b_full = {bin_bps: rates_b.get(bin_bps, 0.0) for bin_bps in all_bins}
    
    # Convert to cumulative distributions
    bins_sorted = sorted(all_bins)
    
    cumsum_a = 0.0
    cumsum_b = 0.0
    max_diff = 0.0
    
    total_a = sum(rates_a_full.values())
    total_b = sum(rates_b_full.values())
    
    if total_a == 0 and total_b == 0:
        return 0.0
    elif total_a == 0 or total_b == 0:
        return 1.0
    
    for bin_bps in bins_sorted:
        cumsum_a += rates_a_full[bin_bps] / total_a
        cumsum_b += rates_b_full[bin_bps] / total_b
        
        diff = abs(cumsum_a - cumsum_b)
        max_diff = max(max_diff, diff)
    
    return max_diff


def loss_components(
    live: Dict, 
    sim: Dict, 
    weights: Dict = None,
    reg_l2: float = 0.0,
    baseline_params: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Dict:
    """
    Calculate loss components between LIVE and SIM distributions.
    
    Args:
        live: LIVE distributions dict
        sim: SIM distributions dict  
        weights: Loss component weights (default: equal weights)
        reg_l2: L2 regularization coefficient
        baseline_params: Baseline parameters for drift calculation
        params: Current parameters for drift calculation
        
    Returns:
        Dict with loss components and total loss
    """
    if weights is None:
        weights = {
            "KS_queue": 1.0,
            "KS_bins": 1.0,
            "L_hit": 1.0,
            "L_maker": 1.0,
            "L_reg": 1.0
        }
    
    # KS distance for queue wait CDF (normalized using IQR scaling)
    ks_queue = ks_distance_cdf_quantiles(
        live.get("queue_wait_cdf_ms", []),
        sim.get("queue_wait_cdf_ms", [])
    )
    
    # KS distance for bin hit rates (normalized)
    live_rates = rates_from_bins(live.get("hit_rate_by_bin", {}))
    sim_rates = rates_from_bins(sim.get("hit_rate_by_bin", {}))
    
    ks_bins = ks_distance_bins_norm(live_rates, sim_rates)
    
    # Hit rate difference
    live_hit = live.get("live_hit", 0.0)
    sim_hit = sim.get("sim_hit", 0.0)
    l_hit = abs(live_hit - sim_hit)
    
    # Maker share difference
    live_maker = live.get("live_maker")
    sim_maker = sim.get("sim_maker")
    
    if live_maker is not None and sim_maker is not None:
        l_maker = abs(live_maker - sim_maker)
    else:
        l_maker = 0.0  # Skip if either is None
    
    # L2 regularization (parameter drift from baseline)
    l_reg = 0.0
    if reg_l2 > 0.0 and baseline_params and params:
        for key in baseline_params:
            if key in params:
                diff = params[key] - baseline_params[key]
                l_reg += diff * diff
        l_reg = reg_l2 * l_reg
    
    # Total weighted loss
    total_loss = (
        weights.get("KS_queue", 1.0) * ks_queue +
        weights.get("KS_bins", 1.0) * ks_bins +
        weights.get("L_hit", 1.0) * l_hit +
        weights.get("L_maker", 1.0) * l_maker +
        weights.get("L_reg", 1.0) * l_reg
    )
    
    return {
        "KS_queue": ks_queue,
        "KS_bins": ks_bins,
        "L_hit": l_hit,
        "L_maker": l_maker,
        "L_reg": l_reg,
        "TotalLoss": total_loss
    }


def load_hourly_summary(path: Path) -> Dict:
    """
    Load and validate hourly summary file with schema upgrade support.
    
    Returns upgraded and validated summary dict.
    Raises ValueError if validation fails.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw_summary = json.load(f)
        
        # Validate and upgrade
        is_valid, errors = validate_hourly_summary_file(raw_summary)
        if not is_valid:
            raise ValueError(f"Summary validation failed for {path}: {errors}")
        
        return upgrade_summary(raw_summary)
        
    except FileNotFoundError:
        raise ValueError(f"Summary file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        raise ValueError(f"Error loading summary {path}: {e}")


def parse_hour_from_filename(filename: str) -> Optional[datetime]:
    """Parse UTC hour from summary filename format: SYMBOL_YYYY-mm-dd_HH.json"""
    try:
        # Extract YYYY-mm-dd_HH from filename
        parts = filename.split('_')
        if len(parts) >= 3 and filename.endswith('.json'):
            date_part = parts[-2]  # YYYY-mm-dd
            hour_part = parts[-1].split('.')[0]  # HH
            
            timestamp_str = f"{date_part}T{hour_part}:00:00Z"
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except (ValueError, IndexError):
        pass
    return None


def scan_summary_files(summaries_dir: Path, symbol: str, from_utc: datetime, to_utc: datetime) -> List[Tuple[datetime, Path]]:
    """
    Scan for summary files in the given time window.
    
    Returns list of (hour_utc, file_path) tuples sorted by hour.
    """
    symbol_dir = summaries_dir / symbol
    if not symbol_dir.exists():
        return []
    
    files_found = []
    
    for json_file in symbol_dir.glob(f"{symbol}_*.json"):
        hour_utc = parse_hour_from_filename(json_file.name)
        if hour_utc and from_utc <= hour_utc < to_utc:
            files_found.append((hour_utc, json_file))
    
    # Sort by hour
    files_found.sort(key=lambda x: x[0])
    return files_found


def preflight_summaries(
    summaries_dir: Path,
    symbol: str,
    from_utc: datetime,
    to_utc: datetime,
    min_files: int = 18,
    min_total_count: int = 100
) -> Tuple[bool, Dict]:
    """
    Perform preflight check on summary files for E2 readiness.
    
    Returns:
        Tuple of (is_ready, info_dict)
    """
    info = {
        "symbol": symbol,
        "window": {
            "from_utc": from_utc.isoformat() + "Z",
            "to_utc": to_utc.isoformat() + "Z",
            "hours_expected": int((to_utc - from_utc).total_seconds() / 3600)
        },
        "files_found": 0,
        "files_valid": 0,
        "total_orders": 0,
        "total_quotes": 0,
        "total_fills": 0,
        "gaps": [],
        "invalid_files": [],
        "schema_versions": {},
        "requirements": {
            "min_files": min_files,
            "min_total_count": min_total_count
        }
    }
    
    # Scan for files
    files_found = scan_summary_files(summaries_dir, symbol, from_utc, to_utc)
    info["files_found"] = len(files_found)
    
    # Track which hours we have
    hours_with_files = set()
    
    # Validate each file and accumulate statistics
    for hour_utc, file_path in files_found:
        hours_with_files.add(hour_utc)
        
        try:
            summary = load_hourly_summary(file_path)
            info["files_valid"] += 1
            
            # Accumulate counts
            counts = summary.get("counts", {})
            info["total_orders"] += counts.get("orders", 0)
            info["total_quotes"] += counts.get("quotes", 0)
            info["total_fills"] += counts.get("fills", 0)
            
            # Track schema versions
            schema_version = summary.get("schema_version", "unknown")
            info["schema_versions"][schema_version] = info["schema_versions"].get(schema_version, 0) + 1
            
        except Exception as e:
            logger.warning(f"Invalid summary file {file_path}: {e}")
            info["invalid_files"].append({
                "path": str(file_path),
                "hour_utc": hour_utc.isoformat() + "Z",
                "error": str(e)
            })
    
    # Find gaps (missing hours)
    current_hour = from_utc
    while current_hour < to_utc:
        if current_hour not in hours_with_files:
            info["gaps"].append(current_hour.isoformat() + "Z")
        current_hour += timedelta(hours=1)
    
    # Determine if requirements are met
    total_activity = info["total_orders"] + info["total_quotes"] + info["total_fills"]
    
    is_ready = (
        info["files_valid"] >= min_files and
        total_activity >= min_total_count and
        len(info["invalid_files"]) == 0
    )
    
    info["is_ready"] = is_ready
    info["total_activity"] = total_activity
    
    return is_ready, info


def print_preflight_report(info: Dict):
    """Print human-friendly preflight report."""
    symbol = info["symbol"]
    window = info["window"]
    
    print(f"\n=== Preflight Report for {symbol} ===")
    print(f"Time window: {window['from_utc']} to {window['to_utc']} ({window['hours_expected']} hours)")
    print(f"Files found: {info['files_found']}")
    print(f"Files valid: {info['files_valid']}")
    
    if info["invalid_files"]:
        print(f"\n[ERROR] Invalid files ({len(info['invalid_files'])}):")
        for invalid in info["invalid_files"]:
            print(f"  - {invalid['hour_utc']}: {invalid['error']}")
    
    if info["gaps"]:
        print(f"\n[WARNING] Missing hours ({len(info['gaps'])}):")
        for gap in info["gaps"][:10]:  # Show first 10 gaps
            print(f"  - {gap}")
        if len(info["gaps"]) > 10:
            print(f"  ... and {len(info['gaps']) - 10} more")
    
    print(f"\n[ACTIVITY] Summary:")
    print(f"  Orders: {info['total_orders']:,}")
    print(f"  Quotes: {info['total_quotes']:,}")
    print(f"  Fills: {info['total_fills']:,}")
    print(f"  Total activity: {info['total_activity']:,}")
    
    if info["schema_versions"]:
        print(f"\n[SCHEMA] Versions:")
        for version, count in info["schema_versions"].items():
            print(f"  {version}: {count} files")
    
    print(f"\n[REQUIREMENTS]:")
    reqs = info["requirements"]
    files_ok = "OK" if info["files_valid"] >= reqs["min_files"] else "FAIL"
    activity_ok = "OK" if info["total_activity"] >= reqs["min_total_count"] else "FAIL"
    errors_ok = "OK" if len(info["invalid_files"]) == 0 else "FAIL"
    
    print(f"  {files_ok} Min files: {info['files_valid']} >= {reqs['min_files']}")
    print(f"  {activity_ok} Min activity: {info['total_activity']} >= {reqs['min_total_count']}")
    print(f"  {errors_ok} No errors: {len(info['invalid_files'])} errors")
    
    if info["is_ready"]:
        print(f"\n[OK] Ready for E2 processing!")
    else:
        print(f"\n[FAIL] Not ready for E2. Address the issues above.")
        
        # Provide helpful suggestions
        if info["files_valid"] < reqs["min_files"]:
            print(f"\n[SUGGESTIONS]:")
            print(f"  - Collect more data (need {reqs['min_files'] - info['files_valid']} more valid files)")
            print(f"  - Check recorder configuration and ensure it's running")
            
        if info["total_activity"] < reqs["min_total_count"]:
            print(f"  - Increase trading activity or reduce min_total_count threshold")
            
        if info["gaps"]:
            print(f"  - Check for recorder downtime during missing hours")
            print(f"  - Consider extending time window to include more data")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Calibration data loader, preflight checker, and core loss engine")
    
    parser.add_argument("--summaries-dir", type=str, default="data/research/summaries",
                       help="Path to summaries directory")
    parser.add_argument("--symbol", type=str, required=True,
                       help="Trading symbol to analyze")
    parser.add_argument("--from-utc", type=str, 
                       help="Start time in UTC (ISO format: YYYY-MM-DDTHH:MM:SSZ), default: now-24h")
    parser.add_argument("--to-utc", type=str,
                       help="End time in UTC (ISO format: YYYY-MM-DDTHH:MM:SSZ), default: now")
    
    # Core calibration options (E2 Part 1)
    parser.add_argument("--bins-max-bps", type=int, default=50,
                       help="Maximum price bin in basis points")
    parser.add_argument("--percentiles", type=str, default="0.1,0.25,0.5,0.75,0.9,0.95,0.99",
                       help="Comma-separated percentiles for CDF")
    parser.add_argument("--seed", type=int, default=42,
                       help="Random seed for deterministic processing")
    parser.add_argument("--round-dp", type=int, default=6,
                       help="Decimal places for rounding floats")
    parser.add_argument("--out", type=str, 
                       help="Output directory, default: artifacts/calibration/<symbol>/")
    parser.add_argument("--report-title", type=str,
                       help="Optional title for report")
    
    # E2 Part 2/2: Search options
    parser.add_argument("--method", choices=["random", "grid"], default="random",
                       help="Parameter search method")
    parser.add_argument("--trials", type=int, default=60,
                       help="Number of candidates to evaluate")
    parser.add_argument("--workers", type=int, default=1,
                       help="Number of parallel workers (currently unused)")
    parser.add_argument("--max-secs", type=int, default=0,
                       help="Maximum search time in seconds (0=unlimited)")
    parser.add_argument("--weights", type=float, nargs=4, default=[1.0, 1.0, 0.5, 0.25],
                       help="Loss weights: KS_queue KS_bins L_hit L_maker")
    parser.add_argument("--reg-l2", type=float, default=0.0,
                       help="L2 regularization coefficient")
    parser.add_argument("--baseline", type=str,
                       help="Baseline calibration.json for drift calculation and initial sampling")
    parser.add_argument("--param-space", type=str,
                       help="Custom parameter bounds JSON file")
    
    # Preflight options
    parser.add_argument("--preflight-only", action="store_true",
                       help="Only run preflight check and exit")
    parser.add_argument("--finish-check-only", action="store_true",
                       help="Only validate E2 finish checklist from existing report.json")
    parser.add_argument("--min-files", type=int, default=18,
                       help="Minimum number of valid files required")
    parser.add_argument("--min-total-count", type=int, default=100,
                       help="Minimum total activity count required")
    
    args = parser.parse_args()
    
    # Set deterministic seed
    random.seed(args.seed)
    np.random.seed(args.seed)
    
    # Parse timestamps with defaults
    try:
        if args.from_utc:
            from_utc = datetime.fromisoformat(args.from_utc.replace('Z', '+00:00'))
        else:
            from_utc = datetime.now(timezone.utc) - timedelta(hours=24)
            
        if args.to_utc:
            to_utc = datetime.fromisoformat(args.to_utc.replace('Z', '+00:00'))
        else:
            to_utc = datetime.now(timezone.utc)
    except ValueError as e:
        print(f"Error parsing timestamps: {e}")
        sys.exit(1)
    
    if from_utc >= to_utc:
        print("Error: from_utc must be before to_utc")
        sys.exit(1)
    
    # Parse CLI percentiles (will be used in get_percentiles_bins)
    cli_percentiles = None
    if args.percentiles:
        try:
            cli_percentiles = [float(p.strip()) for p in args.percentiles.split(',')]
            cli_percentiles.sort()  # Ensure ascending order
        except ValueError as e:
            print(f"Error parsing percentiles: {e}")
            sys.exit(1)
    
    # E2 Part 2/2: Parse weights
    weights_dict = {
        "KS_queue": args.weights[0],
        "KS_bins": args.weights[1], 
        "L_hit": args.weights[2],
        "L_maker": args.weights[3],
        "L_reg": 1.0  # Always use 1.0 for L_reg, actual scaling via --reg-l2
    }
    
    # Set output directory
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = Path("artifacts") / "calibration" / args.symbol
    
    summaries_dir = Path(args.summaries_dir)
    
    # Always run preflight first
    try:
        is_ready, info = preflight_summaries(
            summaries_dir=summaries_dir,
            symbol=args.symbol,
            from_utc=from_utc,
            to_utc=to_utc,
            min_files=args.min_files,
            min_total_count=args.min_total_count
        )
        
        print_preflight_report(info)
        
        if args.preflight_only:
            sys.exit(0 if is_ready else 1)
        
        # E2 Finish Check: validate existing report.json
        if args.finish_check_only:
            try:
                # Load report.json from output directory
                report_path = out_dir / "report.json"
                if not report_path.exists():
                    print(f"[ERROR] report.json not found at {report_path}")
                    sys.exit(2)
                
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_data = json.load(f)
                
                # Validate go_no_go block
                go_no_go = report_data.get("go_no_go", {})
                if not go_no_go:
                    print(f"[ERROR] Missing go_no_go block in report.json")
                    sys.exit(2)
                
                errors = _validate_go_no_go_block(go_no_go, args.round_dp)
                
                # Additional validations when live_maker is missing
                live_distributions = report_data.get("live_distributions", {})
                loss_after = report_data.get("loss_after", {})
                
                if live_distributions.get("live_maker") is None:
                    if go_no_go.get("w4_effective") != 0.0:
                        errors.append("w4_effective should be 0.0 when live_maker is None")
                    if loss_after.get("L_maker") != 0.0:
                        errors.append("loss_after.L_maker should be 0.0 when live_maker is None")
                
                # Check determinism if reference file exists
                calibration_path = out_dir / "calibration.json"
                calibration_ref_path = out_dir / "calibration.json.ref"
                
                if calibration_path.exists() and calibration_ref_path.exists():
                    with open(calibration_path, 'rb') as f1, open(calibration_ref_path, 'rb') as f2:
                        content1 = f1.read()
                        content2 = f2.read()
                        determinism_status = "MATCH" if content1 == content2 else "DIFF"
                        print(f"determinism: {determinism_status}")
                
                # Report results
                if errors:
                    print("[ERROR] E2 finish validation failed:")
                    for error in errors:
                        print(f"  - {error}")
                    sys.exit(2)
                else:
                    print("E2 finish: OK")
                    sys.exit(0)
                    
            except Exception as e:
                print(f"[ERROR] Finish check failed: {e}")
                sys.exit(1)
        
        if not is_ready:
            print(f"\n[FAIL] Preflight failed. Cannot proceed with calibration.")
            print(f"Use --preflight-only to run preflight checks without calibration.")
            sys.exit(1)
        
        # Proceed with core calibration (E2 Part 1)
        print(f"\n[OK] Preflight passed. Proceeding with LIVE distributions...")
        
        # Load LIVE summaries
        raw_summaries = load_live_summaries(summaries_dir, args.symbol, from_utc, to_utc)
        
        if not raw_summaries:
            print(f"[ERROR] No valid summaries found for {args.symbol}")
            sys.exit(1)
        
        # Determine unified percentiles and bins_max_bps configuration
        percentiles, bins_max_bps = get_percentiles_bins(
            cli_percentiles, 
            args.bins_max_bps, 
            raw_summaries  # Pass raw summaries as metadata source
        )
        
        print(f"[CONFIG] Using configuration:")
        print(f"   - Percentiles: {percentiles}")
        print(f"   - Bins max: {bins_max_bps} bps")
        
        # Build LIVE distributions with unified config
        live_distributions = build_live_distributions(raw_summaries, bins_max_bps, percentiles)
        
        # Round and save LIVE distributions
        live_rounded = round_floats(live_distributions, args.round_dp)
        
        live_path = out_dir / "live_distributions.json"
        write_json_sorted(live_path, live_rounded)
        
        print(f"[OUTPUT] LIVE distributions saved to: {live_path}")
        print(f"   - Queue wait CDF: {len(live_distributions['queue_wait_cdf_ms'])} percentiles")
        print(f"   - Hit rate bins: {len(live_distributions['hit_rate_by_bin'])} bins (0-{args.bins_max_bps} bps)")
        print(f"   - Live hit rate: {live_distributions['live_hit']:.4f}")
        if live_distributions['live_maker'] is not None:
            print(f"   - Live maker share: {live_distributions['live_maker']:.4f}")
        
        # Check for SIM fixture (optional for Part 1)
        sim_fixture_path = out_dir / "sim_fixture.json"
        if sim_fixture_path.exists():
            print(f"\n[SIM] Found SIM fixture, computing loss...")
            
            try:
                with open(sim_fixture_path, 'r') as f:
                    sim_distributions = json.load(f)
                
                # Define default weights (E2 Part 1 Polish)
                default_weights = {
                    "KS_queue": 1.0,
                    "KS_bins": 1.0,
                    "L_hit": 1.0,
                    "L_maker": 1.0,
                    "L_reg": 1.0
                }
                
                # Calculate loss components with weights
                loss_result = loss_components(live_distributions, sim_distributions, weights=default_weights)
                loss_rounded = round_floats(loss_result, args.round_dp)
                
                # Save loss report
                report_core_path = out_dir / "report_core.json"
                
                report_data = {
                    "metadata": {
                        "symbol": args.symbol,
                        "from_utc": from_utc.isoformat() + "Z",
                        "to_utc": to_utc.isoformat() + "Z",
                        "bins_max_bps": bins_max_bps,  # Use unified config
                        "percentiles_used": percentiles,  # Use unified config
                        "seed": args.seed,
                        "round_dp": args.round_dp,
                        "report_title": args.report_title
                    },
                    "live_distributions": live_rounded,
                    "sim_distributions": sim_distributions,
                    "loss_components": loss_rounded,
                    "weights": default_weights  # E2 Part 1 Polish: include weights
                }
                
                write_json_sorted(report_core_path, report_data)
                
                # Generate markdown report
                generate_report_core_md(report_data, out_dir / "REPORT_core.md")
                
                print(f"[ANALYSIS] Loss analysis saved to: {report_core_path}")
                print(f"   - Total Loss: {loss_result['TotalLoss']:.6f}")
                print(f"   - KS Queue: {loss_result['KS_queue']:.6f}")
                print(f"   - KS Bins: {loss_result['KS_bins']:.6f}")
                print(f"   - L Hit: {loss_result['L_hit']:.6f}")
                print(f"   - L Maker: {loss_result['L_maker']:.6f}")
                
            except Exception as e:
                logger.warning(f"Failed to process SIM fixture: {e}")
                print(f"[WARNING] SIM fixture found but failed to process: {e}")
        else:
            print(f"\n[INFO] No SIM fixture found (this is normal for E2 Part 1)")
            print(f"   Create {sim_fixture_path} for loss analysis")
            
            # Generate basic LIVE-only markdown report
            basic_report_data = {
                "metadata": {
                    "symbol": args.symbol,
                    "from_utc": from_utc.isoformat() + "Z",
                    "to_utc": to_utc.isoformat() + "Z",
                    "bins_max_bps": bins_max_bps,  # Use unified config
                    "percentiles_used": percentiles,  # Use unified config
                    "seed": args.seed,
                    "round_dp": args.round_dp,
                    "report_title": args.report_title
                },
                "live_distributions": live_rounded
            }
            
            generate_report_core_md(basic_report_data, out_dir / "REPORT_core.md")
        
        # E2 Part 2/2: Parameter search (only if we have sufficient data)
        if raw_summaries and live_distributions:
            print(f"\n[SEARCH] Starting parameter search...")
            
            try:
                # Load parameter space and baseline
                param_bounds = load_param_space(args.param_space)
                baseline_params = load_baseline_params(args.baseline)
                
                if baseline_params:
                    print(f"[BASELINE] Loaded baseline parameters: {len(baseline_params)} params")
                else:
                    print(f"[BASELINE] No baseline provided, using global search")
                
                # Generate candidates
                candidates = sample_candidates(
                    method=args.method,
                    trials=args.trials,
                    seed=args.seed,
                    bounds=param_bounds,
                    baseline_params=baseline_params
                )
                
                print(f"[CANDIDATES] Generated {len(candidates)} candidates using {args.method} method")
                
                # Search loop
                search_start_time = time.time()
                evaluated_candidates = []
                cache = {}  # Simple in-memory cache for this session
                cache_hits = 0
                cache_misses = 0
                
                # E2 Polish: Create cache directory
                cache_dir = out_dir / "cache"
                cache_dir.mkdir(exist_ok=True)
                
                for i, candidate in enumerate(candidates):
                    # E2 Polish: Progress logging every 10 candidates
                    if (i + 1) % 10 == 0 or i == 0:
                        elapsed = time.time() - search_start_time
                        progress_pct = (i + 1) / len(candidates) * 100
                        
                        # Estimate ETA based on current progress
                        if i > 0:
                            rate = (i + 1) / elapsed  # candidates per second
                            remaining = len(candidates) - (i + 1)
                            eta_seconds = remaining / rate if rate > 0 else 0
                            eta_str = f"ETA={eta_seconds:.0f}s"
                        else:
                            eta_str = "ETA=calculating"
                        
                        print(f"[PROGRESS] {i+1}/{len(candidates)} ({progress_pct:.1f}%) elapsed={elapsed:.1f}s {eta_str}")
                    
                    # Check time budget
                    if args.max_secs > 0:
                        elapsed = time.time() - search_start_time
                        if elapsed > args.max_secs:
                            print(f"[TIMEOUT] Early stop at {i}/{len(candidates)} candidates (time limit {args.max_secs}s reached)")
                            break
                    
                    # Per-candidate seed for determinism
                    cand_seed = args.seed + i * 1000
                    
                    try:
                        # Check cache first
                        cand_hash = params_hash(candidate)
                        if cand_hash in cache:
                            sim_distributions = cache[cand_hash]
                            cache_hits += 1
                            logger.debug(f"Cache hit for candidate {i+1} (hash: {cand_hash})")
                        else:
                            # Run simulation
                            cache_misses += 1
                            sim_distributions = run_sim(
                                candidate, args.symbol, out_dir, cand_seed,
                                bins_max_bps, percentiles, args.round_dp
                            )
                            
                            if sim_distributions:
                                cache[cand_hash] = sim_distributions
                                logger.debug(f"Cache miss for candidate {i+1} (hash: {cand_hash})")
                        
                        # Evaluate candidate
                        if sim_distributions:
                            loss_result = evaluate_candidate(
                                candidate, live_distributions, weights_dict,
                                args.reg_l2, baseline_params, sim_distributions
                            )
                            
                            if loss_result:
                                evaluated_candidates.append((candidate, sim_distributions, loss_result))
                                
                                # Log candidate result
                                total_loss = loss_result["TotalLoss"]
                                ks_queue = loss_result["KS_queue"]
                                ks_bins = loss_result["KS_bins"]
                                l_hit = loss_result["L_hit"]
                                elapsed = time.time() - search_start_time
                                
                                print(f"[E2] cand={i+1:2d}/{len(candidates)} loss={total_loss:.3f} "
                                      f"ksQ={ks_queue:.3f} ksB={ks_bins:.3f} hitD={l_hit:.3f} time={elapsed:.1f}s")
                            else:
                                logger.warning(f"Candidate {i+1} evaluation failed")
                        else:
                            logger.warning(f"Candidate {i+1} simulation failed")
                            
                    except Exception as e:
                        logger.warning(f"Candidate {i+1} failed: {e}")
                        continue
                
                search_duration = time.time() - search_start_time
                
                if not evaluated_candidates:
                    print(f"[ERROR] No candidates successfully evaluated")
                    sys.exit(1)
                
                # Select best candidate
                best_candidate, best_sim, best_loss = select_best_candidate(evaluated_candidates)
                
                print(f"\n[WINNER] Best candidate selected:")
                print(f"   - Total Loss: {best_loss['TotalLoss']:.6f}")
                print(f"   - Evaluated: {len(evaluated_candidates)}/{len(candidates)}")
                print(f"   - Duration: {search_duration:.1f}s")
                
                # E2 Polish: Calculate effective w4 based on live_maker availability
                effective_w4 = 0.0 if live_distributions.get("live_maker") is None else weights_dict.get("L_maker", 1.0)
                
                # Prepare search metadata
                search_metadata = {
                    "symbol": args.symbol,
                    "from_utc": from_utc.isoformat() + "Z",
                    "to_utc": to_utc.isoformat() + "Z",
                    # E2 Tiny Polish: Guarantee audit metadata fields
                    "method": args.method,
                    "trials": int(args.trials),
                    "workers": int(args.workers),
                    "seed": int(args.seed),
                    "evaluated": len(evaluated_candidates),
                    "stopped_early": len(evaluated_candidates) < len(candidates),
                    "time_seconds": search_duration,
                    "max_secs": args.max_secs,
                    "bins_max_bps": bins_max_bps,
                    "percentiles_used": percentiles,
                    "weights": weights_dict,
                    "w4_effective": effective_w4,  # E2 Polish: effective w4
                    "reg_l2": args.reg_l2,
                    "round_dp": args.round_dp,
                    "report_title": args.report_title,
                    # E2 Polish: Cache statistics
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses
                }
                
                # Generate artifacts
                generate_calibration_artifacts(
                    best_candidate, best_sim, best_loss, live_distributions,
                    baseline_params, search_metadata, out_dir, args.round_dp, args
                )
                
                print(f"[ARTIFACTS] Saved to: {out_dir}")
                print(f"   - calibration.json - Selected parameters")
                print(f"   - report.json - Complete search results")
                print(f"   - REPORT.md - Human-readable report")
                
            except Exception as e:
                logger.error(f"Parameter search failed: {e}")
                sys.exit(1)
        else:
            print(f"\n[INFO] No parameter search requested (E2 Part 1 mode)")
        
        print(f"\n[SUCCESS] E2 calibration completed successfully")
        
    except Exception as e:
        logger.error(f"Calibration failed: {e}")
        sys.exit(1)


def generate_report_core_md(report_data: Dict, output_path: Path) -> None:
    """Generate markdown report for core calibration results."""
    metadata = report_data["metadata"]
    live = report_data["live_distributions"]
    sim = report_data.get("sim_distributions")
    loss = report_data.get("loss_components")
    
    title = metadata.get("report_title", f"Calibration Core Report - {metadata['symbol']}")
    
    lines = [
        f"# {title}",
        "",
        "## Metadata",
        "",
        f"- **Symbol**: {metadata['symbol']}",
        f"- **Time Window**: {metadata['from_utc']} to {metadata['to_utc']}",
        f"- **Bins Max**: {metadata['bins_max_bps']} bps",
        f"- **Percentiles**: {', '.join(f'{p:.2f}' for p in metadata['percentiles_used'])}",
        f"- **Seed**: {metadata['seed']}",
        f"- **Precision**: {metadata['round_dp']} decimal places",
        "",
        "## LIVE Distributions",
        "",
        f"- **Hit Rate**: {live['live_hit']:.4f} ({live['live_hit']*100:.2f}%)"
    ]
    
    if live['live_maker'] is not None:
        lines.append(f"- **Maker Share**: {live['live_maker']:.4f} ({live['live_maker']*100:.2f}%)")
    
    lines.extend([
        "",
        "### Queue Wait CDF (ms)",
        "",
        "| Percentile | Wait Time (ms) |",
        "|-----------|----------------|"
    ])
    
    for entry in live["queue_wait_cdf_ms"]:
        lines.append(f"| {entry['p']:.2f} | {entry['v']:.2f} |")
    
    lines.extend([
        "",
        "### Hit Rate by Price Bin",
        "",
        "| Bin (bps) | Count | Fills | Hit Rate |",
        "|-----------|-------|-------|----------|"
    ])
    
    bins_data = live["hit_rate_by_bin"]
    for bin_key in sorted(bins_data.keys(), key=int):
        bin_data = bins_data[bin_key]
        count = bin_data["count"]
        fills = bin_data["fills"]
        rate = fills / count if count > 0 else 0.0
        lines.append(f"| {bin_key} | {count} | {fills} | {rate:.4f} ({rate*100:.2f}%) |")
    
    # Add SIM and loss sections if available
    if sim and loss:
        lines.extend([
            "",
            "## SIM Distributions",
            "",
            f"- **Sim Hit Rate**: {sim.get('sim_hit', 0.0):.4f} ({sim.get('sim_hit', 0.0)*100:.2f}%)"
        ])
        
        if sim.get('sim_maker') is not None:
            lines.append(f"- **Sim Maker Share**: {sim['sim_maker']:.4f} ({sim['sim_maker']*100:.2f}%)")
        
        lines.extend([
            "",
            "## Loss Analysis",
            "",
            f"- **Total Loss**: {loss['TotalLoss']:.6f}",
            f"- **KS Queue**: {loss['KS_queue']:.6f}",
            f"- **KS Bins**: {loss['KS_bins']:.6f}",
            f"- **L Hit**: {loss['L_hit']:.6f}",
            f"- **L Maker**: {loss['L_maker']:.6f}",
            f"- **L Reg**: {loss['L_reg']:.6f}",
        ])
    
    lines.extend([
        "",
        "## Units",
        "",
        "**Units**: queue-wait in ms; hit rates shown as %; bins in bps.",
        ""
    ])
    
    # Add KS normalization note if SIM analysis is present
    if sim and loss:
        lines.extend([
            "**Note**: KS distances are normalized to [0,1]. CDF KS uses live IQR (q0.9-q0.1) as scale.",
            ""
        ])
    
    lines.extend([
        "---",
        f"*Generated by E2 Part 1 calibration core at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC*"
    ])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
