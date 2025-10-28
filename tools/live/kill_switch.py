"""
Kill-switch for live trading mode.

Requires dual consent:
1. Environment variable MM_LIVE_ENABLE=1
2. CLI flag --live (or --network without --testnet)

This prevents accidental live trading.
"""

import os
from tools.obs import metrics


class LiveModeNotEnabledError(Exception):
    """Raised when live mode is attempted without proper authorization."""
    pass


def confirm_live_enable(
    network_enabled: bool,
    testnet: bool,
    env_live_enable: str | None = None,
) -> None:
    """
    Confirm that live mode is properly enabled with dual consent.
    
    Args:
        network_enabled: Whether network calls are enabled
        testnet: Whether in testnet mode
        env_live_enable: Value of MM_LIVE_ENABLE env var (None = read from os.environ)
    
    Raises:
        LiveModeNotEnabledError: If live mode is attempted without dual consent
    """
    # Shadow or testnet modes are always safe
    if not network_enabled or testnet:
        metrics.LIVE_ENABLE.set(0)
        return
    
    # Live mode requires dual consent
    if env_live_enable is None:
        env_live_enable = os.getenv("MM_LIVE_ENABLE", "0")
    
    if env_live_enable != "1":
        metrics.LIVE_ENABLE.set(0)
        raise LiveModeNotEnabledError(
            "Live mode requires MM_LIVE_ENABLE=1 environment variable. "
            "This is a safety check to prevent accidental live trading. "
            f"Current value: MM_LIVE_ENABLE={env_live_enable}"
        )
    
    # Both conditions met - live mode enabled
    metrics.LIVE_ENABLE.set(1)


def get_mode_description(network_enabled: bool, testnet: bool) -> str:
    """
    Get human-readable description of current mode.
    
    Args:
        network_enabled: Whether network calls are enabled
        testnet: Whether in testnet mode
    
    Returns:
        Mode description string
    """
    if not network_enabled:
        return "shadow (no-network, dry-run)"
    elif testnet:
        return "testnet (network enabled, testnet endpoints)"
    else:
        return "LIVE (network enabled, production endpoints)"

