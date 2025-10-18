#!/usr/bin/env python3
"""
Warm-up and Ramp-down Manager for Soak Tests

Implements:
- Warm-up preset application (iterations 1-4)
- Auto ramp-down to baseline (iterations 5+)
- Adaptive velocity guard thresholds
- Tuner micro-steps discipline (≤2 keys, cooldown)
- Latency pre-buffer
- Risk/inventory limits on warmup
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class WarmupManager:
    """
    Manages warm-up and ramp-down phases for soak tests.
    
    Phases:
    - Warmup (iters 1-4): Conservative parameters, WARN-only gates
    - Ramp-down (iters 5-6): Linear interpolation back to baseline
    - Steady (iters 7+): Normal baseline parameters
    
    Features:
    - Adaptive velocity guard (relaxed on warmup)
    - Tuner micro-steps (max 2 keys per iteration)
    - Cooldown tracking (1 iteration per key)
    - Latency pre-buffer on warmup
    - Risk/inventory limits
    """
    
    def __init__(
        self,
        warmup_preset_name: str = "warmup_conservative_v1",
        warmup_iterations: int = 4,
        rampdown_steps: int = 2
    ):
        self.warmup_preset_name = warmup_preset_name
        self.warmup_iterations = warmup_iterations
        self.rampdown_steps = rampdown_steps
        self.rampdown_start = warmup_iterations + 1
        
        # State tracking
        self.warmup_overrides: Dict[str, Any] = {}
        self.baseline_overrides: Dict[str, Any] = {}
        self.last_changed_keys: Dict[str, int] = {}  # key -> last_iteration
        
        # Load warmup preset
        self.warmup_preset = self._load_warmup_preset()
    
    def _load_warmup_preset(self) -> Dict[str, Any]:
        """Load warm-up preset from file."""
        preset_path = Path(__file__).parent / "presets" / f"{self.warmup_preset_name}.json"
        
        if not preset_path.exists():
            print(f"[WARMUP] WARN: Preset {self.warmup_preset_name} not found, using empty")
            return {}
        
        with open(preset_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def is_warmup_phase(self, iteration: int) -> bool:
        """Check if current iteration is in warmup phase."""
        return 1 <= iteration <= self.warmup_iterations
    
    def is_rampdown_phase(self, iteration: int) -> bool:
        """Check if current iteration is in ramp-down phase."""
        return self.rampdown_start <= iteration < (self.rampdown_start + self.rampdown_steps)
    
    def is_steady_phase(self, iteration: int) -> bool:
        """Check if current iteration is in steady phase."""
        return iteration >= (self.rampdown_start + self.rampdown_steps)
    
    def get_phase_name(self, iteration: int) -> str:
        """Get human-readable phase name."""
        if self.is_warmup_phase(iteration):
            return "WARMUP"
        elif self.is_rampdown_phase(iteration):
            return "RAMPDOWN"
        else:
            return "STEADY"
    
    def apply_warmup_overrides(
        self,
        baseline_overrides: Dict[str, Any],
        iteration: int
    ) -> Dict[str, Any]:
        """
        Apply warmup overrides based on current iteration.
        
        Returns:
            Overrides dict with warmup/rampdown/steady adjustments
        """
        if not self.warmup_preset:
            return baseline_overrides
        
        # Store baseline for ramp-down
        if not self.baseline_overrides:
            self.baseline_overrides = json.loads(json.dumps(baseline_overrides))  # deep copy
        
        if self.is_warmup_phase(iteration):
            # Apply full warmup preset
            return self._apply_preset_changes(baseline_overrides, self.warmup_preset)
        
        elif self.is_rampdown_phase(iteration):
            # Linear interpolation from warmup to baseline
            progress = (iteration - self.rampdown_start) / self.rampdown_steps
            return self._interpolate_overrides(
                self._apply_preset_changes(baseline_overrides, self.warmup_preset),
                baseline_overrides,
                progress
            )
        
        else:
            # Steady phase: use baseline
            return baseline_overrides
    
    def _apply_preset_changes(
        self,
        overrides: Dict[str, Any],
        preset: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply preset changes to overrides dict."""
        result = json.loads(json.dumps(overrides))  # deep copy
        changes = preset.get("changes", {})
        
        for section_name, section_changes in changes.items():
            if section_name not in result:
                result[section_name] = {}
            
            for param_name, delta_spec in section_changes.items():
                op = delta_spec.get("op")
                value = delta_spec.get("value")
                
                if op == "add":
                    current = result[section_name].get(param_name, 0)
                    result[section_name][param_name] = current + value
                
                elif op == "mul":
                    current = result[section_name].get(param_name, 1.0)
                    result[section_name][param_name] = current * value
        
        return result
    
    def _interpolate_overrides(
        self,
        start: Dict[str, Any],
        end: Dict[str, Any],
        progress: float
    ) -> Dict[str, Any]:
        """
        Linear interpolation between two override dicts.
        
        progress: 0.0 = start, 1.0 = end
        """
        result = {}
        
        # Get all keys from both dicts
        all_keys = set(start.keys()) | set(end.keys())
        
        for key in all_keys:
            start_val = start.get(key, 0)
            end_val = end.get(key, 0)
            
            if isinstance(start_val, dict) and isinstance(end_val, dict):
                # Recursive interpolation for nested dicts
                result[key] = self._interpolate_overrides(start_val, end_val, progress)
            
            elif isinstance(start_val, (int, float)) and isinstance(end_val, (int, float)):
                # Numeric interpolation
                result[key] = start_val + (end_val - start_val) * progress
            
            else:
                # Non-numeric: use end value when progress > 0.5
                result[key] = end_val if progress > 0.5 else start_val
        
        return result
    
    def get_kpi_gate_mode(self, iteration: int) -> str:
        """
        Get KPI gate mode for current iteration.
        
        Returns: "WARN" (warmup), "NORMAL" (steady)
        """
        if self.is_warmup_phase(iteration):
            return "WARN"
        else:
            return "NORMAL"
    
    def get_velocity_threshold(self, iteration: int, base_threshold: float = 0.15) -> float:
        """
        Get velocity guard threshold for current iteration.
        
        Warmup: +50% more lenient
        Steady: baseline
        """
        if self.is_warmup_phase(iteration):
            return base_threshold * 1.5  # 50% more lenient
        else:
            return base_threshold
    
    def filter_tuner_deltas(
        self,
        deltas: Dict[str, float],
        iteration: int,
        max_keys: int = 2
    ) -> Tuple[Dict[str, float], str]:
        """
        Filter tuner deltas to enforce micro-steps discipline.
        
        Rules:
        - Max 2 keys per iteration
        - Cooldown: 1 iteration per key (can't change same key twice in a row)
        
        Returns:
            (filtered_deltas, skip_reason)
        """
        if not deltas:
            return deltas, ""
        
        # Remove keys on cooldown
        available_keys = {}
        for key, value in deltas.items():
            last_changed = self.last_changed_keys.get(key, 0)
            if iteration > last_changed + 1:  # Cooldown = 1 iteration
                available_keys[key] = value
            else:
                print(f"[WARMUP] Cooldown: {key} skipped (last changed: iter {last_changed})")
        
        if not available_keys:
            return {}, "all_keys_on_cooldown"
        
        # Limit to max_keys (prioritize by absolute delta size)
        if len(available_keys) > max_keys:
            sorted_keys = sorted(
                available_keys.items(),
                key=lambda x: abs(x[1]),
                reverse=True
            )
            filtered = dict(sorted_keys[:max_keys])
            print(f"[WARMUP] Micro-steps: Limited to {max_keys} keys (dropped: {len(available_keys) - max_keys})")
        else:
            filtered = available_keys
        
        # Update last_changed tracking
        for key in filtered.keys():
            self.last_changed_keys[key] = iteration
        
        return filtered, ""
    
    def get_latency_prebuffer(
        self,
        iteration: int,
        current_p95: float,
        warmup_target: float = 350.0
    ) -> float:
        """
        Get latency pre-buffer adjustment for spread.
        
        On warmup: Add safety buffer if p95 > target
        On steady: No buffer
        
        Returns: additional spread_bps to add
        """
        if not self.is_warmup_phase(iteration):
            return 0.0
        
        if current_p95 > warmup_target:
            # Add 0.01 bps per 10ms over target
            overage_ms = current_p95 - warmup_target
            buffer_bps = (overage_ms / 10.0) * 0.01
            return min(buffer_bps, 0.05)  # Cap at 0.05 bps
        
        return 0.0
    
    def get_risk_limits(self, iteration: int) -> Dict[str, float]:
        """
        Get risk/inventory limits for current iteration.
        
        Warmup: Stricter limits (80% of normal)
        Steady: Normal limits
        """
        if self.is_warmup_phase(iteration):
            return {
                "max_risk_ratio": 0.50,  # vs 0.60 normal
                "position_limit_multiplier": 0.80,  # 80% of normal
                "rescue_taker_block_threshold": 0.45  # Block rescue if risk > 45%
            }
        else:
            return {
                "max_risk_ratio": 0.60,
                "position_limit_multiplier": 1.00,
                "rescue_taker_block_threshold": 0.55
            }
    
    def should_block_rescue_taker(
        self,
        iteration: int,
        current_risk: float,
        current_p95: float
    ) -> Tuple[bool, str]:
        """
        Check if taker rescue should be blocked.
        
        Block conditions:
        - Warmup: risk > 45% OR p95 > 360ms
        - Steady: risk > 55% OR p95 > 400ms
        
        Returns: (should_block, reason)
        """
        limits = self.get_risk_limits(iteration)
        
        if current_risk > limits["rescue_taker_block_threshold"]:
            return True, f"risk={current_risk:.1%} > {limits['rescue_taker_block_threshold']:.0%}"
        
        p95_threshold = 360.0 if self.is_warmup_phase(iteration) else 400.0
        if current_p95 > p95_threshold:
            return True, f"p95={current_p95:.0f}ms > {p95_threshold:.0f}ms"
        
        return False, ""
    
    def log_phase_transition(self, iteration: int):
        """Log phase transition info."""
        phase = self.get_phase_name(iteration)
        gate_mode = self.get_kpi_gate_mode(iteration)
        
        if iteration == 1:
            print(f"\n{'='*60}")
            print(f"[WARMUP] PHASE: {phase} (iterations 1-{self.warmup_iterations})")
            print(f"[WARMUP] KPI Gate: {gate_mode} mode (no FAIL on warmup)")
            print(f"[WARMUP] Preset: {self.warmup_preset_name}")
            print(f"{'='*60}\n")
        
        elif iteration == self.rampdown_start:
            print(f"\n{'='*60}")
            print(f"[WARMUP] PHASE: {phase} (iterations {self.rampdown_start}-{self.rampdown_start + self.rampdown_steps - 1})")
            print(f"[WARMUP] Ramping down to baseline over {self.rampdown_steps} iterations")
            print(f"{'='*60}\n")
        
        elif iteration == self.rampdown_start + self.rampdown_steps:
            print(f"\n{'='*60}")
            print(f"[WARMUP] PHASE: {phase} (baseline parameters restored)")
            print(f"[WARMUP] KPI Gate: {gate_mode} mode (full enforcement)")
            print(f"{'='*60}\n")

