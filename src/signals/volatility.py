"""
Simple volatility estimation using stdlib only.
"""

import math
from typing import List


def ewma_volatility(returns: List[float], alpha: float = 0.06) -> float:
    """
    Calculate exponentially weighted moving average volatility.
    
    Args:
        returns: List of returns
        alpha: Decay factor (0 < alpha <= 1)
        
    Returns:
        Volatility (standard deviation)
    """
    if not returns:
        return 0.0
    
    if len(returns) == 1:
        return abs(returns[0])
    
    # Initialize with first squared return
    var = returns[0] * returns[0]
    
    # EWMA variance calculation
    for r in returns[1:]:
        var = alpha * (r * r) + (1.0 - alpha) * var
    
    # Return standard deviation
    return math.sqrt(max(0.0, var))
