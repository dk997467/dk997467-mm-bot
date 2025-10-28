"""
Symbol filters cache with TTL.

Caches symbol trading filters (tickSize, stepSize, minQty) to reduce API calls.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from tools.obs import metrics


@dataclass
class SymbolFilters:
    """
    Trading filters for a symbol.
    
    Attributes:
        symbol: Trading symbol (e.g., BTCUSDT)
        tick_size: Minimum price increment
        step_size: Minimum quantity increment
        min_qty: Minimum order quantity
        price_precision: Price decimal places (optional)
        qty_precision: Quantity decimal places (optional)
    """
    
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    price_precision: int = 2
    qty_precision: int = 8
    
    def __post_init__(self):
        """Ensure numeric values are Decimal."""
        if not isinstance(self.tick_size, Decimal):
            object.__setattr__(self, "tick_size", Decimal(str(self.tick_size)))
        if not isinstance(self.step_size, Decimal):
            object.__setattr__(self, "step_size", Decimal(str(self.step_size)))
        if not isinstance(self.min_qty, Decimal):
            object.__setattr__(self, "min_qty", Decimal(str(self.min_qty)))
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "symbol": self.symbol,
            "tick_size": float(self.tick_size),
            "step_size": float(self.step_size),
            "min_qty": float(self.min_qty),
            "price_precision": self.price_precision,
            "qty_precision": self.qty_precision,
        }


class SymbolFiltersCache:
    """
    Cache for symbol filters with TTL.
    
    Reduces API calls by caching filters for each symbol.
    """
    
    def __init__(self, clock: Callable[[], int], ttl_s: int = 600):
        """
        Initialize cache.
        
        Args:
            clock: Clock function returning current timestamp in ms
            ttl_s: Time-to-live for cache entries in seconds (default: 10 minutes)
        """
        self._clock = clock
        self._ttl_ms = ttl_s * 1000
        self._cache: dict[str, tuple[SymbolFilters, int]] = {}
    
    def get(
        self,
        symbol: str,
        fetcher: Callable[[], SymbolFilters],
    ) -> SymbolFilters:
        """
        Get filters for symbol, fetching if not cached or expired.
        
        Args:
            symbol: Trading symbol
            fetcher: Function to fetch filters if not cached
        
        Returns:
            SymbolFilters for the symbol
        """
        now = self._clock()
        
        # Check cache
        if symbol in self._cache:
            filters, cached_at = self._cache[symbol]
            age_ms = now - cached_at
            
            if age_ms < self._ttl_ms:
                # Cache hit
                metrics.SYMBOL_FILTERS_SOURCE.inc(source="cached")
                return filters
        
        # Cache miss or expired - fetch new
        try:
            filters = fetcher()
            self._cache[symbol] = (filters, now)
            metrics.SYMBOL_FILTERS_SOURCE.inc(source="fetched")
            return filters
        except Exception as e:
            # Fetch failed - use stale cache if available
            if symbol in self._cache:
                filters, _ = self._cache[symbol]
                metrics.SYMBOL_FILTERS_SOURCE.inc(source="stale")
                return filters
            
            # No cache and fetch failed - use default
            metrics.SYMBOL_FILTERS_SOURCE.inc(source="default")
            metrics.SYMBOL_FILTERS_FETCH_ERRORS.inc()
            
            return _get_default_filters(symbol)
    
    def clear(self, symbol: str | None = None):
        """
        Clear cache for symbol or all symbols.
        
        Args:
            symbol: Symbol to clear (None = clear all)
        """
        if symbol is None:
            self._cache.clear()
        else:
            self._cache.pop(symbol, None)


def _get_default_filters(symbol: str) -> SymbolFilters:
    """
    Get default filters for unknown symbols.
    
    These are safe defaults that work for most symbols.
    """
    # Common defaults based on typical exchange specs
    defaults = {
        "BTCUSDT": SymbolFilters(
            symbol=symbol,
            tick_size=Decimal("0.01"),
            step_size=Decimal("0.00001"),
            min_qty=Decimal("0.00001"),
            price_precision=2,
            qty_precision=5,
        ),
        "ETHUSDT": SymbolFilters(
            symbol=symbol,
            tick_size=Decimal("0.01"),
            step_size=Decimal("0.0001"),
            min_qty=Decimal("0.0001"),
            price_precision=2,
            qty_precision=4,
        ),
        "SOLUSDT": SymbolFilters(
            symbol=symbol,
            tick_size=Decimal("0.001"),
            step_size=Decimal("0.01"),
            min_qty=Decimal("0.01"),
            price_precision=3,
            qty_precision=2,
        ),
    }
    
    if symbol in defaults:
        return defaults[symbol]
    
    # Generic default
    return SymbolFilters(
        symbol=symbol,
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        price_precision=2,
        qty_precision=3,
    )


def from_live(exchange_client: Any, symbol: str) -> SymbolFilters:
    """
    Adapter to fetch filters from live exchange client.
    
    Args:
        exchange_client: Exchange client with fetch_symbol_filters_live method
        symbol: Trading symbol
    
    Returns:
        SymbolFilters parsed from exchange response
    """
    if hasattr(exchange_client, "fetch_symbol_filters_live"):
        return exchange_client.fetch_symbol_filters_live(symbol)
    
    # Fallback if method not available
    return _get_default_filters(symbol)

