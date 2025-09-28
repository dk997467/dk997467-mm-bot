"""
Multi-strategy multiplexer with volatility-based regime switching.
"""

import time
from typing import Dict, List, Optional, Callable, Any
from src.audit.log import audit_event


class MultiStratMux:
    """Multi-strategy multiplexer with hysteresis and weight caps."""
    
    def __init__(self, 
                 profiles: Dict[str, Dict[str, Any]], 
                 hysteresis_s: int = 60,
                 weight_caps: Optional[Dict[str, float]] = None,
                 clock: Callable[[], float] = time.time,
                 metrics=None):
        """
        Initialize multi-strategy mux.
        
        Args:
            profiles: Dict of regime profiles with weights and bands
            hysteresis_s: Hysteresis time in seconds
            weight_caps: Optional weight caps per strategy
            clock: Time function (injectable for testing)
            metrics: Metrics registry (optional)
        """
        self.profiles = profiles
        self.hysteresis_s = hysteresis_s
        self.weight_caps = weight_caps or {}
        self.clock = clock
        self.metrics = metrics
        
        # State
        self.current_regime: Optional[str] = None
        self.last_switch_time: float = 0.0
        
        # Initialize metrics
        if self.metrics:
            self.strategy_weight_gauges = {}
            self.switch_counter = self.metrics.counter('strategy_switch_total', 'Strategy regime switches')
            
            # Create gauges for all strategies mentioned in profiles
            all_strategies = set()
            for profile in profiles.values():
                if 'weights' in profile:
                    all_strategies.update(profile['weights'].keys())
            
            for strategy in all_strategies:
                self.strategy_weight_gauges[strategy] = self.metrics.gauge(
                    f'strategy_weight_{strategy.lower()}', 
                    f'Weight for {strategy} strategy'
                )
    
    def _determine_regime(self, sigma: float) -> str:
        """Determine regime based on sigma and band ranges."""
        for regime, config in self.profiles.items():
            if 'band' in config:
                band = config['band']
                if len(band) >= 2:
                    # Use left-inclusive, right-exclusive: [low, high)
                    # Except for the last band which includes the upper bound
                    if sigma >= band[0] and (sigma < band[1] or regime == max(self.profiles.keys())):
                        return regime
        
        # Fallback to first regime if no match
        return next(iter(self.profiles.keys()))
    
    def _apply_weight_caps(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Apply weight caps and normalize to sum=1.0."""
        capped = {}
        for strategy, weight in weights.items():
            if strategy in self.weight_caps:
                capped[strategy] = min(weight, self.weight_caps[strategy])
            else:
                capped[strategy] = weight
        
        # Normalize to sum=1.0
        total = sum(capped.values())
        if total > 0:
            for strategy in capped:
                capped[strategy] /= total
        
        return capped
    
    def on_sigma(self, sigma: float) -> Dict[str, float]:
        """
        Process sigma update and return strategy weights.
        
        Args:
            sigma: Current volatility estimate
            
        Returns:
            Dict of strategy weights (sum=1.0)
        """
        current_time = self.clock()
        target_regime = self._determine_regime(sigma)
        
        # Apply hysteresis
        if (self.current_regime is not None and 
            self.current_regime != target_regime and
            current_time - self.last_switch_time < self.hysteresis_s):
            # Stay in current regime due to hysteresis
            regime = self.current_regime
        else:
            # Switch to target regime
            if self.current_regime != target_regime:
                self.last_switch_time = current_time
                if self.metrics and self.switch_counter:
                    self.switch_counter.inc()
                try:
                    audit_event("MUX", "-", {"regime": str(target_regime), "weights": ""})
                except Exception:
                    pass
            regime = target_regime
            self.current_regime = regime
        
        # Get weights for current regime
        profile = self.profiles.get(regime, {})
        raw_weights = profile.get('weights', {})
        
        # Apply caps and normalize
        final_weights = self._apply_weight_caps(raw_weights)
        
        # Update metrics
        if self.metrics:
            for strategy, weight in final_weights.items():
                if strategy in self.strategy_weight_gauges:
                    self.strategy_weight_gauges[strategy].set(weight)
        
        # Log
        weights_str = ",".join(f"{k}:{v:.6f}" for k, v in sorted(final_weights.items()))
        print(f"MUX ts={current_time:.0f} sigma={sigma:.6f} regime={regime} weights={weights_str}")
        try:
            # Compact weights string to avoid high cardinality
            audit_event("MUX", "-", {"regime": str(regime), "weights": weights_str})
        except Exception:
            pass
        
        return final_weights
