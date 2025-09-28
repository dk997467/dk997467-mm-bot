"""
Position skew guard for market making bot.

Monitors position skew by symbol and color, applying deterministic decisions.
"""

from typing import Dict, Set
from dataclasses import dataclass
from src.audit.log import audit_event


@dataclass
class PositionSkewDecision:
    """Result of position skew evaluation."""
    symbol_breach: Set[str]
    color_breach: bool
    bias_sign: int  # -1, 0, +1 toward reducing existing skew


class PositionSkewGuard:
    """Guard that monitors position skew and makes deterministic decisions."""
    
    def __init__(self, per_symbol_abs_limit: float, per_color_abs_limit: float):
        self.per_symbol_abs_limit = per_symbol_abs_limit
        self.per_color_abs_limit = per_color_abs_limit
        self._last_pos_skew_abs: float = 0.0
        
    def evaluate(self, positions_by_symbol: Dict[str, float], 
                 color_by_symbol: Dict[str, str]) -> PositionSkewDecision:
        """Evaluate position skew and return deterministic decision."""
        symbol_breach = set()
        color_breach = False
        bias_sign = 0
        
        # Compute pos_skew_abs using a deterministic symbol (max absolute skew)
        try:
            max_allowed = float(self.per_symbol_abs_limit) if float(self.per_symbol_abs_limit) > 0.0 else 0.0
            max_abs = 0.0
            if positions_by_symbol:
                for _sym, _pos in positions_by_symbol.items():
                    a = abs(float(_pos))
                    if a > max_abs:
                        max_abs = a
            if max_allowed > 0.0:
                self._last_pos_skew_abs = float(max_abs / max_allowed)
            else:
                self._last_pos_skew_abs = 0.0
        except Exception:
            self._last_pos_skew_abs = 0.0

        # Check per-symbol limits
        if self.per_symbol_abs_limit > 0:
            for symbol, position in positions_by_symbol.items():
                if abs(position) > self.per_symbol_abs_limit:
                    symbol_breach.add(symbol)
        
        # Check per-color limits
        if self.per_color_abs_limit > 0:
            color_positions = {}
            for symbol, position in positions_by_symbol.items():
                color = color_by_symbol.get(symbol, 'blue')
                color_positions[color] = color_positions.get(color, 0.0) + position
            
            # Find color with largest absolute breach
            max_breach_abs = 0.0
            max_breach_position = 0.0
            
            for color, total_position in color_positions.items():
                breach_abs = abs(total_position) - self.per_color_abs_limit
                if breach_abs > max_breach_abs:
                    max_breach_abs = breach_abs
                    max_breach_position = total_position
            
            if max_breach_abs > 0:
                color_breach = True
                # bias_sign toward reducing existing skew
                if max_breach_position > 0:
                    bias_sign = -1  # reduce positive skew
                elif max_breach_position < 0:
                    bias_sign = +1  # reduce negative skew
                else:
                    bias_sign = 0
                try:
                    audit_event("GUARD", "-", {"name": "pos_skew", "event": "breach", "value": float(self._last_pos_skew_abs)})
                except Exception:
                    pass
            else:
                # Recover event when previously breached
                if getattr(self, '_was_breach', False):
                    try:
                        audit_event("GUARD", "-", {"name": "pos_skew", "event": "recover", "value": float(self._last_pos_skew_abs)})
                    except Exception:
                        pass
            self._was_breach = bool(max_breach_abs > 0)
        
        return PositionSkewDecision(
            symbol_breach=symbol_breach,
            color_breach=color_breach,
            bias_sign=bias_sign
        )
