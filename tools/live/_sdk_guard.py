"""
Guard imports for optional live trading dependencies.

This module provides lazy loading for exchange SDKs that are only needed
for live trading. These dependencies are in the [live] extras group.

Usage:
    from tools.live._sdk_guard import load_bybit_sdk
    
    bybit = load_bybit_sdk()
    # Use bybit SDK...
"""

from typing import Any


def load_bybit_sdk() -> Any:
    """
    Lazily load Bybit SDK (bybit-connector).
    
    This function attempts to import the bybit_connector package, which is
    only available when the [live] extras are installed.
    
    Returns:
        The bybit_connector module
        
    Raises:
        RuntimeError: If bybit-connector SDK is not installed
        
    Example:
        >>> bybit = load_bybit_sdk()
        >>> # Use bybit SDK methods...
    """
    try:
        import bybit_connector  # type: ignore
        return bybit_connector
    except ImportError as e:
        raise RuntimeError(
            "Bybit SDK (bybit-connector) is not installed.\n"
            "Install live trading dependencies with:\n"
            "  pip install -e .[live]\n"
            "or:\n"
            "  pip install -r requirements_live.txt"
        ) from e


# TODO: Add more SDK guard loaders as needed
# def load_kucoin_sdk() -> Any:
#     """Load KuCoin SDK (when implemented)."""
#     try:
#         import kucoin  # type: ignore
#         return kucoin
#     except ImportError as e:
#         raise RuntimeError("KuCoin SDK not installed...") from e

