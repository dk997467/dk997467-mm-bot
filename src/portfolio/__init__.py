"""
Portfolio allocation module.

Provides portfolio allocation strategies with manual, inverse volatility,
and risk parity modes.
"""

from .allocator import PortfolioAllocator, PortfolioTarget

__all__ = ['PortfolioAllocator', 'PortfolioTarget']
