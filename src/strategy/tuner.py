#!/usr/bin/env python3
"""
Walk-forward strategy parameter tuner for market making bot.

This module provides CLI interface and utilities for tuning strategy parameters
using walk-forward analysis with deterministic splits.
"""

import argparse
import shutil
import hashlib
import json
import logging
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

import polars as pl

# Try to import numpy for additional RNG seeding
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


def round_dict(data: dict, decimals: int) -> dict:
    """Round all float values in dict to specified decimal places."""
    rounded = {}
    for key, value in data.items():
        if isinstance(value, float):
            rounded[key] = round(value, decimals)
        elif isinstance(value, dict):
            rounded[key] = round_dict(value, decimals)
        elif isinstance(value, list):
            rounded[key] = [round(x, decimals) if isinstance(x, float) else x for x in value]
        else:
            rounded[key] = value
    return rounded


def calculate_baseline_drift(new_params: dict, baseline_params: dict) -> dict:
    """Calculate parameter drift percentage relative to baseline."""
    WHITELISTED_KEYS = [
        "k_vola_spread", "skew_coeff", "levels_per_side", "level_spacing_coeff",
        "min_time_in_book_ms", "replace_threshold_bps", "imbalance_cutoff"
    ]
    
    drift_pct = {}
    eps = 1e-9  # Small epsilon to avoid division by zero
    
    for key in WHITELISTED_KEYS:
        if key in new_params and key in baseline_params:
            new_val = new_params[key]
            base_val = baseline_params[key]
            
            # Calculate drift: 100 * |new - base| / max(eps, |base|)
            if isinstance(new_val, (int, float)) and isinstance(base_val, (int, float)):
                drift_pct[key] = 100.0 * abs(new_val - base_val) / max(eps, abs(base_val))
    
    return drift_pct


class TimeSplit(NamedTuple):
    """Represents a single train/validation split."""
    train_start: datetime
    train_end: datetime
    validate_start: datetime
    validate_end: datetime
    split_id: int


def seed_all(seed: int) -> None:
    """Seed all random number generators for reproducibility."""
    random.seed(seed)
    if NUMPY_AVAILABLE:
        np.random.seed(seed)
    logging.debug(f"Seeded all RNGs with seed: {seed}")


def get_git_sha() -> str:
    """Get git SHA from repository, fallback to 'unknown'."""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            text=True, 
            cwd=Path(__file__).parent.parent.parent
        )
        return result.strip()[:8]  # Return first 8 chars
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def cfg_sanitized_hash(cfg: Any) -> str:
    """Compute hash of sanitized config, excluding secrets."""
    if hasattr(cfg, 'to_sanitized'):
        # Use existing sanitizer if available
        data = cfg.to_sanitized()
    else:
        # Fallback: convert to dict and mask common secret fields
        if hasattr(cfg, 'to_dict'):
            data = cfg.to_dict()
        elif hasattr(cfg, '__dict__'):
            data = cfg.__dict__.copy()
        else:
            data = str(cfg)
        
        # Mask common secret fields
        if isinstance(data, dict):
            for key in ['api_key', 'api_secret', 'password', 'secret', 'token']:
                if key in data:
                    data[key] = "***"
    
    # Convert to JSON string and hash
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class WalkForwardTuner:
    """Walk-forward parameter tuning with deterministic splits."""
    
    def __init__(self, seed: int, round_dp: int = 6, min_fills: int = 1, min_val_minutes: int = 1):
        """Initialize tuner with fixed seed for reproducibility."""
        self.seed = seed
        self.round_dp = round_dp
        self.min_fills = min_fills
        self.min_val_minutes = min_val_minutes
        seed_all(seed)
        self.rng = random.Random(seed)
        logging.info(f"Initialized tuner with seed: {seed}")
    
    def generate_splits(
        self,
        data_start: datetime,
        data_end: datetime,
        train_days: int,
        validate_hours: int,
        step_hours: Optional[int] = None
    ) -> List[TimeSplit]:
        """
        Generate walk-forward splits.

        Args:
            data_start: Start of available data
            data_end: End of available data
            train_days: Training window size in days
            validate_hours: Validation window size in hours
            step_hours: Step size between splits in hours (default: validate_hours)

        Returns:
            List of time splits

        Raises:
            ValueError: If step_hours <= 0 or if (train_days + validate_hours) exceeds data range
        """
        if step_hours is None:
            step_hours = validate_hours

        # Validate step_hours
        if step_hours <= 0:
            raise ValueError("step_hours must be positive")

        # Validate that train + validate window fits in data range
        total_window_hours = (train_days * 24) + validate_hours
        data_range_hours = (data_end - data_start).total_seconds() / 3600

        if total_window_hours > data_range_hours:
            raise ValueError(
                f"Combined train ({train_days} days) + validate ({validate_hours} hours) = "
                f"{total_window_hours} hours exceeds available data range of {data_range_hours:.1f} hours"
            )

        splits: List[TimeSplit] = []
        split_id = 0

        current_start = data_start
        train_delta = timedelta(days=train_days)
        validate_delta = timedelta(hours=validate_hours)
        step_delta = timedelta(hours=step_hours)

        while current_start + train_delta + validate_delta <= data_end:
            train_end = current_start + train_delta
            validate_start = train_end
            validate_end = validate_start + validate_delta

            split = TimeSplit(
                train_start=current_start,
                train_end=train_end,
                validate_start=validate_start,
                validate_end=validate_end,
                split_id=split_id
            )
            splits.append(split)

            # Next split starts after current split start + step
            current_start = current_start + step_delta
            split_id += 1

        logging.info(f"Generated {len(splits)} splits")
        return splits

    def seed_split(self, split_index: int) -> None:
        """Seed RNG for a specific split to ensure deterministic but different streams."""
        split_seed = self.seed + split_index
        seed_all(split_seed)
        # Also reseed the local RNG used for parameter generation
        self.rng.seed(split_seed)
        logging.debug(f"Seeded split {split_index} with seed: {split_seed}")
    
    def load_data(self, data_path: Path, symbol: str) -> pl.DataFrame:
        """Load and prepare data for tuning."""
        # TODO: Implement data loading logic
        # This should load orderbook snapshots, trades, etc.
        logging.info(f"Loading data from {data_path} for symbol {symbol}")
        # For now, create mock data for testing
        import numpy as np
        
        # Create mock data with timestamp column
        start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Generate timestamps every hour
        timestamps = []
        current = start_time
        while current <= end_time:
            timestamps.append(current)
            current += timedelta(hours=1)
        
        # Create mock DataFrame
        mock_data = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": [symbol] * len(timestamps),
            "price": np.random.uniform(100, 200, len(timestamps)),
            "volume": np.random.uniform(1000, 10000, len(timestamps))
        })
        
        return mock_data
    
    def evaluate_split(
        self,
        split: TimeSplit,
        train_data: pl.DataFrame,
        validate_data: pl.DataFrame,
        params: dict
    ) -> float:
        """Evaluate a single parameter set on validation data."""
        # TODO: Implement strategy evaluation logic
        # This should run the strategy with given params on validation data
        logging.info(f"Evaluating split {split.split_id} with params: {params}")
        return 0.0
    
    def grid_search(
        self,
        splits: List[TimeSplit],
        param_grid: dict,
        data: pl.DataFrame
    ) -> List[Tuple[dict, float]]:
        """Perform grid search over parameter space."""
        results = []
        total_combinations = 1
        for values in param_grid.values():
            total_combinations *= len(values)
        
        logging.info(f"Grid search: {total_combinations} parameter combinations")
        
        # TODO: Implement grid search logic
        return results
    
    def random_search(
        self,
        splits: List[TimeSplit],
        param_space: dict,
        trials: int,
        data: pl.DataFrame
    ) -> List[Tuple[dict, float]]:
        """Perform random search over parameter space."""
        results = []
        logging.info(f"Random search: {trials} trials")
        
        # TODO: Implement random search logic
        return results
    
    def tune_split(
        self,
        split: TimeSplit,
        param_space: dict,
        method: str,
        trials: int,
        lambda_cvar: float,
        data: pl.DataFrame
    ) -> Tuple[dict, dict]:
        """
        Tune parameters for a single split.
            
        Returns:
            (best_params, metrics) tuple
        """
        # Seed for this split
        self.seed_split(split.split_id)
        
        # Extract train and validate data slices
        train_data = data.filter(
            (pl.col("timestamp") >= split.train_start) &
            (pl.col("timestamp") < split.train_end)
        )
        validate_data = data.filter(
            (pl.col("timestamp") >= split.validate_start) &
            (pl.col("timestamp") < split.validate_end)
        )
        
        if method == "random":
            best_params, best_objective = self._random_search_split(
                split.split_id, train_data, param_space, trials, lambda_cvar
            )
        elif method == "grid":
            best_params, best_objective = self._grid_search_split(
                train_data, param_space, lambda_cvar
            )
        else:
            raise ValueError(f"Unknown method: {method}")
        
        # Evaluate best params on validation data
        metrics = self._evaluate_params_split(best_params, validate_data)
        
        return best_params, metrics
    
    def _random_search_split(
        self,
        split_id: int,
        train_data: pl.DataFrame,
        param_space: dict,
        trials: int,
        lambda_cvar: float
    ) -> Tuple[dict, float]:
        """Random search for a single split with deterministic per-trial RNG."""
        base_trial_seed = self.seed + split_id * 10000
        best_params = None
        best_objective = float('-inf')
        
        for trial_id in range(trials):
            # Per-trial RNG allows safe parallelism
            local_rng = random.Random(base_trial_seed + trial_id)
            params = self._generate_random_params_with_rng(local_rng, param_space)
            
            # Evaluate on train data
            metrics = self._evaluate_params_split(params, train_data)
            objective = self._calculate_objective(metrics, lambda_cvar)
            
            if objective > best_objective:
                best_objective = objective
                best_params = params.copy()
        
        return best_params, best_objective
    
    def _grid_search_split(
        self,
        train_data: pl.DataFrame,
        param_space: dict,
        lambda_cvar: float
    ) -> Tuple[dict, float]:
        """Grid search for a single split."""
        best_params = None
        best_objective = float('-inf')
        
        # Generate all parameter combinations
        param_combinations = self._generate_grid_params(param_space)
        
        for params in param_combinations:
            # Evaluate on train data
            metrics = self._evaluate_params_split(params, train_data)
            objective = self._calculate_objective(metrics, lambda_cvar)
            
            if objective > best_objective:
                best_objective = objective
                best_params = params.copy()
        
        return best_params, best_objective
    
    def _generate_random_params(self, param_space: dict) -> dict:
        """Generate random parameters within the specified space."""
        return self._generate_random_params_with_rng(self.rng, param_space)

    def _generate_random_params_with_rng(self, rng: random.Random, param_space: dict) -> dict:
        """Generate random parameters using provided RNG (for deterministic trials)."""
        params = {}
        for param_name, param_range in param_space.items():
            if isinstance(param_range, (list, tuple)):
                params[param_name] = rng.choice(param_range)
            elif isinstance(param_range, dict):
                min_val = param_range['min']
                max_val = param_range['max']
                if param_range.get('type') == 'int':
                    params[param_name] = rng.randint(min_val, max_val)
                else:
                    params[param_name] = rng.uniform(min_val, max_val)
            else:
                params[param_name] = param_range
        return params
    
    def _generate_grid_params(self, param_space: dict) -> List[dict]:
        """Generate all parameter combinations for grid search."""
        import itertools
        
        param_names = list(param_space.keys())
        param_values = []
        
        for param_name in param_names:
            param_range = param_space[param_name]
            if isinstance(param_range, (list, tuple)):
                param_values.append(param_range)
            elif isinstance(param_range, dict):
                # For continuous ranges, create discrete steps
                min_val = param_range['min']
                max_val = param_range['max']
                steps = param_range.get('steps', 5)
                if param_range.get('type') == 'int':
                    values = list(range(min_val, max_val + 1, max(1, (max_val - min_val) // steps)))
                else:
                    values = [min_val + i * (max_val - min_val) / (steps - 1) for i in range(steps)]
                param_values.append(values)
            else:
                param_values.append([param_range])
        
        # Generate all combinations
        combinations = list(itertools.product(*param_values))
        
        # Convert to list of dicts
        result = []
        for combo in combinations:
            params = dict(zip(param_names, combo))
            result.append(params)
        
        return result
    
    def _evaluate_params_split(self, params: dict, data: pl.DataFrame) -> dict:
        """
        Evaluate parameters on data slice.
        
        Returns deterministic metrics for the given parameters and data.
        """
        # Seed RNG for deterministic evaluation
        param_hash = hash(str(sorted(params.items())))
        self.rng.seed(param_hash)
        
        # Simulate strategy execution with given parameters
        # This is a placeholder - in real implementation, this would call backtest.run
        
        # Base units metrics. Keep legacy keys for compatibility.
        net_pnl = self.rng.uniform(-500, 1000)
        maker_rebate = self.rng.uniform(0, 50)
        taker_fees = self.rng.uniform(0, 100)
        hit_rate = self.rng.uniform(0.3, 0.9)
        maker_share = self.rng.uniform(0.5, 0.95)
        sharpe = self.rng.uniform(0.5, 2.5)
        cvar95 = self.rng.uniform(-800, -200)
        avg_queue_wait_ms = int(self.rng.uniform(100, 5000))
        quotes = int(self.rng.randint(100, 1000))
        fills = int(self.rng.randint(50, 500))

        metrics = {
            "net_pnl_usd": net_pnl,
            "maker_rebate_usd": maker_rebate,
            "taker_fees_usd": taker_fees,
            "hit_rate": hit_rate,
            "maker_share": maker_share,
            "sharpe": sharpe,
            "cvar95_usd": cvar95,
            "avg_queue_wait_ms": avg_queue_wait_ms,
            "quotes": quotes,
            "fills": fills,
            # legacy mirrors
            "net_pnl": net_pnl,
            "maker_rebate": maker_rebate,
            "taker_fees": taker_fees,
            "cvar95": cvar95,
            "avg_queue_wait": avg_queue_wait_ms / 1000.0,
        }
        
        return metrics
    
    def _calculate_objective(self, metrics: dict, lambda_cvar: float) -> float:
        """Calculate objective function: NetPnL - λ*|CVaR95| in base units."""
        net_pnl = metrics.get("net_pnl_usd", metrics.get("net_pnl", 0.0))
        cvar95 = metrics.get("cvar95_usd", metrics.get("cvar95", 0.0))
        objective = net_pnl - lambda_cvar * abs(cvar95)
        return objective
    
    def check_gates(self, metrics: dict, gates: dict) -> Tuple[bool, List[str]]:
        """
        Check if metrics pass all gates.
        
        Returns:
            (passed, reasons) tuple
        """
        passed = True
        reasons = []
        
        # Hit rate gate
        if metrics["hit_rate"] < gates["min_hit"]:
            passed = False
            reasons.append(f"Hit rate: {metrics['hit_rate']:.3f} < {gates['min_hit']:.3f}")
        
        # Maker share gate
        if metrics["maker_share"] < gates["min_maker"]:
            passed = False
            reasons.append(f"Maker share: {metrics['maker_share']:.3f} < {gates['min_maker']:.3f}")
        
        # CVaR95 gate (CVaR95 is negative, so we check if it's >= -max_cvar)
        if metrics["cvar95"] < -gates["max_cvar"]:
            passed = False
            reasons.append(f"CVaR95: {metrics['cvar95']:.3f} < -{gates['max_cvar']:.3f}")
        
        # NetPnL gate
        if metrics["net_pnl"] < gates["min_pnl"]:
            passed = False
            reasons.append(f"NetPnL: {metrics['net_pnl']:.3f} < {gates['min_pnl']:.3f}")
        
        return passed, reasons
    
    def _choose_champion(self, split_results: List[dict], lambda_cvar: float) -> dict:
        """Choose champion based on best average objective with tiebreakers."""
        if not split_results:
            raise ValueError("No split results to choose champion from")
        
        # Calculate average objective for each parameter set
        param_objectives = {}
        
        for result in split_results:
            params_key = str(sorted(result["params"].items()))
            metrics = result["metrics"]
            
            if params_key not in param_objectives:
                param_objectives[params_key] = {
                    "params": result["params"],
                    "objectives": [],
                    "metrics_list": []
                }
            
            objective = self._calculate_objective(metrics, lambda_cvar)
            param_objectives[params_key]["objectives"].append(objective)
            param_objectives[params_key]["metrics_list"].append(metrics)
        
        # Calculate aggregated metrics for each parameter set for tiebreaking
        candidate_data = []
        for params_key, data in param_objectives.items():
            avg_objective = sum(data["objectives"]) / len(data["objectives"])
            
            # Calculate aggregated metrics using base units
            metrics_list = data["metrics_list"]
            net_pnl_values = [m.get("net_pnl_usd", m.get("net_pnl", 0)) for m in metrics_list]
            cvar95_values = [m.get("cvar95_usd", m.get("cvar95", 0)) for m in metrics_list]
            hit_rate_values = [m.get("hit_rate", 0) for m in metrics_list]
            
            # Calculate tiebreaker metrics
            win_ratio = sum(1 for pnl in net_pnl_values if pnl > 0) / len(net_pnl_values) if net_pnl_values else 0
            net_pnl_mean = sum(net_pnl_values) / len(net_pnl_values) if net_pnl_values else 0
            cvar95_mean = sum(cvar95_values) / len(cvar95_values) if cvar95_values else 0
            
            # Parameter complexity (simple heuristic: sum of numeric param values)
            param_complexity = sum(v for v in data["params"].values() if isinstance(v, (int, float)))
            
            candidate_data.append({
                "params_key": params_key,
                "avg_objective": avg_objective,
                "win_ratio": win_ratio,
                "net_pnl_mean": net_pnl_mean,
                "cvar95_mean_abs": abs(cvar95_mean),
                "param_complexity": param_complexity,
                "data": data
            })
        
        # Sort by tiebreakers: (1) avg_objective DESC, (2) win_ratio DESC, 
        # (3) net_pnl_mean DESC, (4) cvar95_mean_abs ASC, (5) param_complexity ASC
        candidate_data.sort(key=lambda x: (
            -x["avg_objective"],
            -x["win_ratio"],
            -x["net_pnl_mean"],
            x["cvar95_mean_abs"],
            x["param_complexity"]
        ))
        
        best_candidate = candidate_data[0]
        best_params_key = best_candidate["params_key"]
        
        # Calculate average metrics for champion
        champion_data = param_objectives[best_params_key]
        champion_metrics = {}
        
        # Average all numeric metrics using base units
        base_metric_names = ["net_pnl_usd", "maker_rebate_usd", "taker_fees_usd", 
                            "cvar95_usd", "hit_rate", "maker_share", "sharpe",
                            "avg_queue_wait_ms", "quotes", "fills"]
        
        # Legacy metric names for backward compatibility
        legacy_metric_names = ["net_pnl", "maker_rebate", "taker_fees", "cvar95", 
                              "avg_queue_wait"]
        
        # Average base metrics
        for metric_name in base_metric_names:
            values = []
            for metrics in champion_data["metrics_list"]:
                if metric_name in metrics:
                    values.append(metrics[metric_name])
            if values:
                champion_metrics[metric_name] = sum(values) / len(values)
        
        # Average legacy metrics for backward compatibility
        for metric_name in legacy_metric_names:
            values = []
            for metrics in champion_data["metrics_list"]:
                if metric_name in metrics:
                    values.append(metrics[metric_name])
            if values:
                champion_metrics[metric_name] = sum(values) / len(values)
        
        return {
            "params": champion_data["params"],
            "metrics": champion_metrics,
            "avg_objective": best_candidate["avg_objective"]
        }
    
    def save_detailed_report(
        self,
        splits: List[TimeSplit],
        split_results: List[dict],
        champion_params: dict,
        champion_metrics: dict,
        gates: dict,
        gate_reasons: List[str],
        output_dir: Path,
        symbol: str,
        cfg_hash: str,
        git_sha: str,
        exit_code: int = 0,
        gates_passed: bool = True,
        skipped_splits: List[dict] = None,
        baseline_drift: dict = None
    ) -> None:
        """Save detailed report with metrics table, gates information, exit code, and baseline drift."""
        # Ensure UTC timezone and ISO8601 format with 'Z'
        def to_utc_iso(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace('+00:00', 'Z')
        
        if skipped_splits is None:
            skipped_splits = []
        
        # Create report.json with exit code and gates information
        report_data = {
            "git_sha": git_sha,
            "cfg_hash": cfg_hash,
            "seed": self.seed,
            "exit_code": exit_code,
            "gates": {
                "passed": gates_passed,
                "reasons": gate_reasons,
                "thresholds": gates
            },
            "champion_params": champion_params,
            "champion_metrics": champion_metrics,
            "skipped_splits": skipped_splits,
            "baseline_drift_pct": baseline_drift if baseline_drift else {},
            "splits": []
        }
        
        for split, result in zip(splits, split_results):
            split_data = {
                "split_id": split.split_id,
                "time_bounds": {
                    "train_from": to_utc_iso(split.train_start),
                    "train_to": to_utc_iso(split.train_end),
                    "val_from": to_utc_iso(split.validate_start),
                    "val_to": to_utc_iso(split.validate_end)
                },
                "best_params": result["params"],
                "metrics": result["metrics"]
            }
            report_data["splits"].append(split_data)
        
        # Round all floats and save report.json with sorted keys for determinism
        report_data = round_dict(report_data, self.round_dp)
        report_file = output_dir / "report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, sort_keys=True, ensure_ascii=False)
        
        # Create detailed REPORT.md with polished format
        report_md_file = output_dir / "REPORT.md"
        with open(report_md_file, 'w', encoding='utf-8') as f:
            # Title line with git SHA, config hash, and seed
            title_line = f"{symbol} • {git_sha[:8]} • cfg={cfg_hash} • seed={self.seed}"
            if hasattr(self, 'report_title') and self.report_title:
                title_line = f"{self.report_title} • {title_line}"
            f.write(f"# {title_line}\n\n")
            
            # Summary information
            f.write(f"**Total Splits**: {len(splits)} (Used: {len(split_results)}, Skipped: {len(skipped_splits)})\n\n")
            
            # Table for used splits with units in headers
            if split_results:
                f.write("## Split Results (Used Only)\n\n")
                f.write("| i | Train[UTC] | Validate[UTC] | NetPnL($) | CVaR95($) | Hit(%) | Maker(%) | Fills | Quotes | AvgQueueWait(ms) |\n")
                f.write("|---|------------|---------------|-----------|-----------|--------|----------|-------|--------|------------------|\n")
                
                for result in split_results:
                    split_id = result["split_id"]
                    metrics = result["metrics"]
                    
                    # Find the corresponding split for time bounds
                    split = next((s for s in splits if s.split_id == split_id), None)
                    if not split:
                        continue
                    
                    # Extract metrics with base unit preference
                    net_pnl = metrics.get("net_pnl_usd", metrics.get("net_pnl", 0))
                    cvar95 = metrics.get("cvar95_usd", metrics.get("cvar95", 0))
                    hit_rate_pct = metrics.get("hit_rate", 0) * 100
                    maker_share_pct = metrics.get("maker_share", 0) * 100
                    fills = int(metrics.get("fills", 0))
                    quotes = int(metrics.get("quotes", 0))
                    avg_wait_ms = metrics.get("avg_queue_wait_ms", metrics.get("avg_queue_wait", 0))
                    
                    train_range = f"{to_utc_iso(split.train_start)[:10]} to {to_utc_iso(split.train_end)[:10]}"
                    val_range = f"{to_utc_iso(split.validate_start)[:10]} to {to_utc_iso(split.validate_end)[:10]}"
                    
                    f.write(f"| {split_id:03d} | {train_range} | {val_range} | {net_pnl:.2f} | {cvar95:.2f} | {hit_rate_pct:.1f} | {maker_share_pct:.1f} | {fills} | {quotes} | {avg_wait_ms:.1f} |\n")
            
            # Skipped splits section
            if skipped_splits:
                f.write("\n## Skipped Splits\n\n")
                for skip_info in skipped_splits:
                    f.write(f"- **Split {skip_info['split_id']:03d}**: {skip_info['reason']}\n")
            
            f.write("\n")
            
            # Champion section with parameters and aggregated metrics
            f.write("## Champion\n\n")
            f.write("**Parameters**:\n```json\n")
            f.write(json.dumps(champion_params, indent=2, sort_keys=True))
            f.write("\n```\n\n")
            
            f.write("**Aggregated Metrics** (across used splits):\n")
            # Show both base and rendered units
            net_pnl_usd = champion_metrics.get("net_pnl_usd", champion_metrics.get("net_pnl", 0))
            cvar95_usd = champion_metrics.get("cvar95_usd", champion_metrics.get("cvar95", 0))
            hit_rate = champion_metrics.get("hit_rate", 0)
            maker_share = champion_metrics.get("maker_share", 0)
            sharpe = champion_metrics.get("sharpe", 0)
            
            f.write(f"- **NetPnL**: ${net_pnl_usd:.2f}\n")
            f.write(f"- **CVaR95**: ${cvar95_usd:.2f}\n")
            f.write(f"- **Hit Rate**: {hit_rate:.3f} ({hit_rate*100:.1f}%)\n")
            f.write(f"- **Maker Share**: {maker_share:.3f} ({maker_share*100:.1f}%)\n")
            f.write(f"- **Sharpe**: {sharpe:.3f}\n")
            
            # Baseline drift section if available
            if baseline_drift:
                f.write(f"\n**Baseline Drift**:\n")
                for param_key, drift_pct in baseline_drift.items():
                    f.write(f"- {param_key}: {drift_pct:.1f}%\n")
            
            f.write("\n## Gates & Validation\n\n")
            f.write("**Thresholds**:\n")
            f.write(f"- Hit Rate: >= {gates['min_hit']:.3f}\n")
            f.write(f"- Maker Share: >= {gates['min_maker']:.3f}\n")
            f.write(f"- CVaR95 loss limit: <= {gates['max_cvar']:.2f}\n")
            f.write(f"- NetPnL: >= {gates['min_pnl']:.2f}\n\n")
            
            if gates_passed:
                f.write("**Result**: PASSED ✅\n\n")
            else:
                f.write("**Result**: FAILED ❌\n")
                f.write("**Reasons**:\n")
                for reason in gate_reasons:
                    f.write(f"- {reason}\n")
                f.write("\n")
            
            # Footer with units explanation
            f.write("---\n\n")
            f.write("**Units Note**: USD values are base units; percentages and bps shown for display convenience only.\n")
        
        logging.info(f"Saved detailed report to {report_file}")
        logging.info(f"Saved REPORT.md to {report_md_file}")
    
    def save_split_result(
        self,
        split: TimeSplit,
        best_params: dict,
        metrics: dict,
        output_dir: Path,
        symbol: str,
        cfg_hash: str,
        git_sha: str,
        skipped: bool = False,
        skip_reason: str = ""
    ) -> None:
        """Save individual split result with metadata and zero-padded filename."""
        # Ensure UTC timezone and ISO8601 format with 'Z'
        def to_utc_iso(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace('+00:00', 'Z')
        
        result = {
            "split_id": split.split_id,
            "git_sha": git_sha,
            "cfg_hash": cfg_hash,
            "seed": self.seed,
            "time_bounds": {
                "train_from": to_utc_iso(split.train_start),
                "train_to": to_utc_iso(split.train_end),
                "val_from": to_utc_iso(split.validate_start),
                "val_to": to_utc_iso(split.validate_end)
            },
            "best_params": best_params,
            "metrics": metrics
        }
        
        # Add skip information if applicable
        if skipped:
            result["skipped"] = True
            result["skip_reason"] = skip_reason
        
        # Round all floats before saving
        result = round_dict(result, self.round_dp)
        
        # Create symbol-specific directory
        symbol_dir = output_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # Save split result with zero-padded filename
        result_file = symbol_dir / f"split_{split.split_id:03d}_best.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, sort_keys=True, ensure_ascii=False)
        
        logging.info(f"Saved split {split.split_id} result to {result_file}")
    
    def save_champion_result(
        self,
        splits: List[TimeSplit],
        champion_params: dict,
        champion_metrics: dict,
        output_dir: Path,
        symbol: str,
        cfg_hash: str,
        git_sha: str
    ) -> None:
        """Save champion result and summary report."""
        # Ensure UTC timezone and ISO8601 format with 'Z'
        def to_utc_iso(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat().replace('+00:00', 'Z')
        
        # Create symbol-specific directory
        symbol_dir = output_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # Save champion result with all metadata
        champion_result = {
            "git_sha": git_sha,
            "cfg_hash": cfg_hash,
            "seed": self.seed,
            "champion_params": champion_params,
            "champion_metrics": champion_metrics,
            "splits_summary": [
                {
                    "split_id": split.split_id,
                    "time_bounds": {
                        "train_from": to_utc_iso(split.train_start),
                        "train_to": to_utc_iso(split.train_end),
                        "val_from": to_utc_iso(split.validate_start),
                        "val_to": to_utc_iso(split.validate_end)
                    }
                }
                for split in splits
            ]
        }
        
        # Round all floats before saving
        champion_result = round_dict(champion_result, self.round_dp)
        
        champion_file = symbol_dir / "champion.json"
        with open(champion_file, 'w', encoding='utf-8') as f:
            json.dump(champion_result, f, indent=2, sort_keys=True, ensure_ascii=False)
        
        # Save human-readable report
        report_file = symbol_dir / "REPORT.md"
        with open(report_file, 'w') as f:
            f.write(f"# Walk-forward Tuning Report for {symbol}\n\n")
            f.write(f"- **Git SHA**: {git_sha}\n")
            f.write(f"- **Config Hash**: {cfg_hash}\n")
            f.write(f"- **Seed**: {self.seed}\n")
            f.write(f"- **Total Splits**: {len(splits)}\n\n")
            
            f.write("## Time Windows\n\n")
            f.write("| Split | Train From | Train To | Validate From | Validate To |\n")
            f.write("|-------|------------|----------|---------------|-------------|\n")
            for split in splits:
                f.write(f"| {split.split_id} | {to_utc_iso(split.train_start)} | {to_utc_iso(split.train_end)} | {to_utc_iso(split.validate_start)} | {to_utc_iso(split.validate_end)} |\n")
            
            f.write(f"\n## Champion Parameters\n\n")
            f.write("```json\n")
            f.write(json.dumps(champion_params, indent=2))
            f.write("\n```\n\n")
            
            f.write(f"## Champion Metrics\n\n")
            f.write("```json\n")
            f.write(json.dumps(champion_metrics, indent=2))
            f.write("\n```\n\n")
            
            f.write("## Gates & Validation\n\n")
            f.write("**CVaR95 Gate**: CVaR95 represents negative PnL at 95% confidence level.\n")
            f.write("Gate is 'not worse than -X' -> pass if CVaR95 >= -X.\n")
            f.write("Example: Gate of -1000 means CVaR95 must be >= -1000 to pass.\n")
        
        logging.info(f"Saved champion result to {champion_file}")
        logging.info(f"Saved report to {report_file}")


def main():
    """CLI entry point for walk-forward tuning."""
    parser = argparse.ArgumentParser(
        description="Walk-forward strategy parameter tuner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required arguments
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Enable walk-forward mode"
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to data directory or file"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Trading symbol to tune for"
    )
    
    # Split configuration
    parser.add_argument(
        "--train-days",
        type=int,
        default=30,
        help="Training window size in days"
    )
    parser.add_argument(
        "--validate-hours",
        type=int,
        default=24,
        help="Validation window size in hours"
    )
    parser.add_argument(
        "--step-hours",
        type=int,
        help="Step size between splits in hours (default: validate-hours)"
    )
    
    # Search configuration
    parser.add_argument(
        "--method",
        choices=["grid", "random"],
        default="random",
        help="Search method"
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=100,
        help="Number of trials for random search"
    )
    
    # Objective function
    parser.add_argument(
        "--lambda-cvar",
        type=float,
        default=0.1,
        help="CVaR penalty weight in objective: avg(NetPnL) - λ*CVaR95"
    )
    
    # Gates configuration
    parser.add_argument(
        "--gate-min-hit",
        type=float,
        default=0.6,
        help="Minimum hit rate threshold (0.0-1.0)"
    )
    parser.add_argument(
        "--gate-min-maker",
        type=float,
        default=0.7,
        help="Minimum maker share threshold (0.0-1.0)"
    )
    parser.add_argument(
        "--gate-max-cvar",
        type=float,
        default=1000.0,
        help="Maximum CVaR95 threshold (positive value, will be negated)"
    )
    parser.add_argument(
        "--gate-min-pnl",
        type=float,
        default=100.0,
        help="Minimum NetPnL threshold"
    )
    
    # Baseline comparison
    parser.add_argument(
        "--baseline-json",
        type=Path,
        help="Path to baseline results for parameter drift analysis"
    )
    
    # Reproducibility
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible results"
    )
    
    # Output
    parser.add_argument(
        "--out",
        type=Path,
        help="Output directory (default: artifacts/tuning/<symbol>/)"
    )
    
    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    # D2 additions
    parser.add_argument('--workers', type=int, default=1,
                        help='Number of workers for parallel tuning per split (default: 1)')
    parser.add_argument('--round-dp', type=int, default=6,
                        help='Decimal places for float rounding in JSON/report (default: 6)')
    parser.add_argument('--min-fills', type=int, default=1,
                        help='Skip validation slices with fewer fills than this (default: 1)')
    parser.add_argument('--min-val-minutes', type=int, default=1,
                        help='Skip validation slices shorter than this in minutes (default: 1)')
    parser.add_argument('--report-title', type=str,
                        help='Optional title prefix for REPORT.md')
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    if not args.walk_forward:
        logging.error("--walk-forward flag is required")
        sys.exit(1)
    
    # Validate CLI arguments
    if args.step_hours is not None and args.step_hours <= 0:
        logging.error("--step-hours must be positive")
        sys.exit(1)
    
    if args.train_days <= 0:
        logging.error("--train-days must be positive")
        sys.exit(1)
    
    if args.validate_hours <= 0:
        logging.error("--validate-hours must be positive")
        sys.exit(1)
    
    if args.trials <= 0:
        logging.error("--trials must be positive")
        sys.exit(1)
    
    # Set default step_hours if not provided
    if args.step_hours is None:
        args.step_hours = args.validate_hours
    
    # Set default output directory
    if args.out is None:
        args.out = Path("artifacts/tuning")
    
    # Create output directory
    args.out.mkdir(parents=True, exist_ok=True)
    
    # Get metadata
    git_sha = get_git_sha()
    cfg_hash = "unknown"  # TODO: Get from actual config when available
    
    # Seed all RNGs globally
    seed_all(args.seed)
    
    # Initialize tuner
    tuner = WalkForwardTuner(
        seed=args.seed,
        round_dp=args.round_dp,
        min_fills=args.min_fills,
        min_val_minutes=args.min_val_minutes
    )
    
    # Set optional report title
    if args.report_title:
        tuner.report_title = args.report_title
    
    # Load data
    data = tuner.load_data(args.data, args.symbol)
    
    # Generate splits
    # TODO: Extract actual data start/end from loaded data
    data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    data_end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    
    splits = tuner.generate_splits(
        data_start=data_start,
        data_end=data_end,
                train_days=args.train_days,
                validate_hours=args.validate_hours,
        step_hours=args.step_hours
    )
    
    # Print split information
    print(f"Generated {len(splits)} splits:")
    print(f"Train window: {args.train_days} days")
    print(f"Validate window: {args.validate_hours} hours")
    print(f"Step size: {args.step_hours} hours")
    print(f"Method: {args.method}")
    print(f"Trials: {args.trials}")
    print(f"Lambda CVaR: {args.lambda_cvar}")
    print(f"Git SHA: {git_sha}")
    print(f"Config Hash: {cfg_hash}")
    print(f"Seed: {args.seed}\n")
    
    # Define parameter space for tuning
    param_space = {
        "spread_bps": [5, 10, 15, 20, 25],
        "size_usd": [100, 200, 500, 1000],
        "refresh_ms": [100, 200, 500, 1000],
        "max_pos_usd": [1000, 2000, 5000, 10000]
    }
    
    # Process each split
    split_results = []
    skipped_splits = []
    for split in splits:
        print(f"Processing split {split.split_id}...")
        
        # Check skip criteria
        val_duration_minutes = (split.validate_end - split.validate_start).total_seconds() / 60
        should_skip = False
        skip_reason = ""
        
        if val_duration_minutes < args.min_val_minutes:
            should_skip = True
            skip_reason = f"Validation window too short: {val_duration_minutes:.1f} < {args.min_val_minutes} minutes"
        
        if should_skip:
            # Save skipped split
            tuner.save_split_result(
                split=split,
                best_params={},
                metrics={},
                output_dir=args.out,
                symbol=args.symbol,
                cfg_hash=cfg_hash,
                git_sha=git_sha,
                skipped=True,
                skip_reason=skip_reason
            )
            skipped_splits.append({"split_id": split.split_id, "reason": skip_reason})
            print(f"  SKIPPED: {skip_reason}")
            continue
        
        # Tune parameters for this split
        best_params, metrics = tuner.tune_split(
            split=split,
            param_space=param_space,
            method=args.method,
            trials=args.trials,
            lambda_cvar=args.lambda_cvar,
            data=data
        )
        
        # Check fills count (post-evaluation)
        fills_count = metrics.get("fills", 0)
        if fills_count < args.min_fills:
            skip_reason = f"Too few fills: {fills_count} < {args.min_fills}"
            tuner.save_split_result(
                split=split,
                best_params=best_params,
                metrics=metrics,
                output_dir=args.out,
                symbol=args.symbol,
                cfg_hash=cfg_hash,
                git_sha=git_sha,
                skipped=True,
                skip_reason=skip_reason
            )
            skipped_splits.append({"split_id": split.split_id, "reason": skip_reason})
            print(f"  SKIPPED: {skip_reason}")
            continue
        
        # Save valid split result
        tuner.save_split_result(
            split=split,
            best_params=best_params,
            metrics=metrics,
            output_dir=args.out,
            symbol=args.symbol,
            cfg_hash=cfg_hash,
            git_sha=git_sha
        )
        
        split_results.append({
            "split_id": split.split_id,
            "params": best_params,
            "metrics": metrics
        })
        
        print(f"  Best params: {best_params}")
        print(f"  NetPnL: {metrics['net_pnl']:.1f}")
        print(f"  Hit rate: {metrics['hit_rate']:.3f}")
        print(f"  Maker share: {metrics['maker_share']:.3f}")
        print(f"  CVaR95: {metrics['cvar95']:.1f}")
    
    # Choose champion (best average objective across splits)
    print("\nChoosing champion...")
    if not split_results:
        print("No valid splits found - all splits were skipped")
        print("Cannot select champion without any valid results")
        
        # Create dummy champion for consistency
        champion_params = {}
        champion_metrics = {}
        
        # Set exit code to 1 (internal error)
        exit_code = 1
        gate_reasons = ["No valid splits found"]
        gates_passed = False
        baseline_drift = {}
        gates = {
            "min_hit": args.gate_min_hit,
            "min_maker": args.gate_min_maker,
            "max_cvar": args.gate_max_cvar,
            "min_pnl": args.gate_min_pnl
        }
    else:
        champion = tuner._choose_champion(split_results, args.lambda_cvar)
        champion_params = champion["params"]
        champion_metrics = champion["metrics"]
        
        print(f"Champion params: {champion_params}")
        print(f"Champion metrics: {champion_metrics}")
        
        # Calculate baseline drift if baseline provided
        baseline_drift = None
        if args.baseline_json:
            try:
                with open(args.baseline_json, 'r') as f:
                    baseline_data = json.load(f)
                baseline_params = baseline_data.get("champion_params", baseline_data.get("params", {}))
                baseline_drift = calculate_baseline_drift(champion_params, baseline_params)
                print(f"Baseline drift: {baseline_drift}")
            except Exception as e:
                logging.warning(f"Failed to load baseline from {args.baseline_json}: {e}")
                baseline_drift = {}
        
        # Check gates
        gates = {
            "min_hit": args.gate_min_hit,
            "min_maker": args.gate_min_maker,
            "max_cvar": args.gate_max_cvar,
            "min_pnl": args.gate_min_pnl
        }
        
        gates_passed, gate_reasons = tuner.check_gates(champion_metrics, gates)
        
        # Determine exit code and print results
        if not gates_passed:
            print("\n❌ GATES FAILED:")
            for reason in gate_reasons:
                print(f"  - {reason}")
            print(f"\nExiting with code 2 (gate failure)")
            exit_code = 2
        else:
            print("\n✅ All gates passed!")
            exit_code = 0
    
    print(f"Champion params: {champion_params}")
    print(f"Champion metrics: {champion_metrics}")
    
    # Save champion result
    tuner.save_champion_result(
        splits=splits,
        champion_params=champion_params,
        champion_metrics=champion_metrics,
        output_dir=args.out,
        symbol=args.symbol,
        cfg_hash=cfg_hash,
        git_sha=git_sha
    )
    
    # Save detailed report with exit code and gate information
    tuner.save_detailed_report(
        splits=splits,
        split_results=split_results,
        champion_params=champion_params,
        champion_metrics=champion_metrics,
        gates=gates,
        gate_reasons=gate_reasons,
        output_dir=args.out,
        symbol=args.symbol,
        cfg_hash=cfg_hash,
        git_sha=git_sha,
        exit_code=exit_code,
        gates_passed=gates_passed,
        skipped_splits=skipped_splits,
        baseline_drift=baseline_drift
    )

    # Backward-compatibility: also mirror artifacts under artifacts/tuner/<symbol>/ if expected by tests
    legacy_dir = Path("artifacts/tuner") / args.symbol
    legacy_dir.mkdir(parents=True, exist_ok=True)
    # Copy champion.json and REPORT.md if available
    src_champion = args.out / args.symbol / "champion.json"
    if src_champion.exists():
        shutil.copy2(src_champion, legacy_dir / "champion.json")
    src_report_md = args.out / args.symbol / "REPORT.md"
    if src_report_md.exists():
        shutil.copy2(src_report_md, legacy_dir / "REPORT.md")
    src_report_json = args.out / "report.json"
    if src_report_json.exists():
        shutil.copy2(src_report_json, legacy_dir / "report.json")
    
    print(f"\n✅ Walk-forward tuning completed!")
    print(f"Results saved to: {args.out}")
    print(f"Champion parameters: {champion_params}")
    print(f"Gates passed: {gates_passed}")
    
    # Exit with appropriate code
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Internal error: {e}")
        sys.exit(1)  # Internal/IO error
