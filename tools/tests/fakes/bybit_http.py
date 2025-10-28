"""
Fake Bybit HTTP responses for testing.

Provides deterministic responses for Bybit REST API without real network I/O.
"""

from decimal import Decimal
from typing import Any


class FakeBybitHttp:
    """
    Fake Bybit HTTP client for testing.
    
    Returns deterministic responses for common endpoints.
    """
    
    def __init__(self, testnet: bool = False):
        """
        Initialize fake HTTP client.
        
        Args:
            testnet: Whether to simulate testnet mode
        """
        self._testnet = testnet
        self._custom_filters: dict[str, dict[str, Any]] = {}
    
    def set_custom_filters(self, symbol: str, filters: dict[str, Any]):
        """
        Set custom filters for a symbol (for testing edge cases).
        
        Args:
            symbol: Trading symbol
            filters: Filter dict with tick_size, step_size, min_qty
        """
        self._custom_filters[symbol] = filters
    
    def get_instruments_info(self, symbol: str | None = None) -> dict[str, Any]:
        """
        Fake response for GET /v5/market/instruments-info.
        
        Args:
            symbol: Trading symbol (None = all symbols)
        
        Returns:
            Fake instruments info response
        """
        # Deterministic filters for common symbols
        instruments = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "baseCoin": "BTC",
                "quoteCoin": "USDT",
                "status": "Trading",
                "priceFilter": {
                    "tickSize": "0.01",
                    "minPrice": "0.01",
                    "maxPrice": "999999.00",
                },
                "lotSizeFilter": {
                    "qtyStep": "0.00001",
                    "minOrderQty": "0.00001",
                    "maxOrderQty": "1000.00",
                },
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "baseCoin": "ETH",
                "quoteCoin": "USDT",
                "status": "Trading",
                "priceFilter": {
                    "tickSize": "0.01",
                    "minPrice": "0.01",
                    "maxPrice": "99999.00",
                },
                "lotSizeFilter": {
                    "qtyStep": "0.0001",
                    "minOrderQty": "0.0001",
                    "maxOrderQty": "10000.00",
                },
            },
            "SOLUSDT": {
                "symbol": "SOLUSDT",
                "baseCoin": "SOL",
                "quoteCoin": "USDT",
                "status": "Trading",
                "priceFilter": {
                    "tickSize": "0.001",
                    "minPrice": "0.001",
                    "maxPrice": "9999.000",
                },
                "lotSizeFilter": {
                    "qtyStep": "0.01",
                    "minOrderQty": "0.01",
                    "maxOrderQty": "100000.00",
                },
            },
        }
        
        # Apply custom filters if set
        for sym, custom in self._custom_filters.items():
            if sym in instruments:
                if "tick_size" in custom:
                    instruments[sym]["priceFilter"]["tickSize"] = str(custom["tick_size"])
                if "step_size" in custom:
                    instruments[sym]["lotSizeFilter"]["qtyStep"] = str(custom["step_size"])
                if "min_qty" in custom:
                    instruments[sym]["lotSizeFilter"]["minOrderQty"] = str(custom["min_qty"])
        
        # Filter by symbol if requested
        if symbol:
            if symbol in instruments:
                result_list = [instruments[symbol]]
            else:
                result_list = []
        else:
            result_list = list(instruments.values())
        
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "category": "linear",
                "list": result_list,
            },
            "time": 1698765432000,
        }
    
    def get_open_orders(self, symbol: str | None = None) -> dict[str, Any]:
        """
        Fake response for GET /v5/order/realtime.
        
        Args:
            symbol: Trading symbol filter
        
        Returns:
            Fake open orders response
        """
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [],
                "nextPageCursor": "",
            },
            "time": 1698765432000,
        }
    
    def get_position(self, symbol: str) -> dict[str, Any]:
        """
        Fake response for GET /v5/position/list.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Fake position response
        """
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [
                    {
                        "symbol": symbol,
                        "side": "None",
                        "size": "0",
                        "avgPrice": "0",
                        "unrealisedPnl": "0",
                    }
                ],
            },
            "time": 1698765432000,
        }


def create_fake_bybit_response_error(code: int = 10001, msg: str = "Error") -> dict[str, Any]:
    """
    Create fake error response.
    
    Args:
        code: Error code
        msg: Error message
    
    Returns:
        Fake error response
    """
    return {
        "retCode": code,
        "retMsg": msg,
        "result": {},
        "time": 1698765432000,
    }

