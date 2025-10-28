"""Unit tests for kill_switch.py - dual consent for live mode."""

import pytest

from tools.live.kill_switch import (
    confirm_live_enable,
    get_mode_description,
    LiveModeNotEnabledError,
)


def test_confirm_live_shadow_mode():
    """Test kill-switch allows shadow mode (no network)."""
    # Shadow mode: network_enabled=False → always safe
    confirm_live_enable(
        network_enabled=False,
        testnet=False,
        env_live_enable="0",
    )
    # Should not raise


def test_confirm_live_testnet_mode():
    """Test kill-switch allows testnet mode without MM_LIVE_ENABLE."""
    # Testnet mode: network_enabled=True, testnet=True → safe
    confirm_live_enable(
        network_enabled=True,
        testnet=True,
        env_live_enable="0",
    )
    # Should not raise


def test_confirm_live_mode_without_env():
    """Test kill-switch blocks live mode without MM_LIVE_ENABLE=1."""
    # Live mode without env var → should raise
    with pytest.raises(LiveModeNotEnabledError) as exc_info:
        confirm_live_enable(
            network_enabled=True,
            testnet=False,
            env_live_enable="0",
        )
    
    assert "MM_LIVE_ENABLE=1" in str(exc_info.value)
    assert "safety check" in str(exc_info.value).lower()


def test_confirm_live_mode_with_env():
    """Test kill-switch allows live mode with MM_LIVE_ENABLE=1."""
    # Live mode with env var set → should allow
    confirm_live_enable(
        network_enabled=True,
        testnet=False,
        env_live_enable="1",
    )
    # Should not raise


def test_confirm_live_mode_env_missing():
    """Test kill-switch blocks live mode with missing env var."""
    # Live mode with missing env var (None) → should raise
    with pytest.raises(LiveModeNotEnabledError):
        confirm_live_enable(
            network_enabled=True,
            testnet=False,
            env_live_enable=None,  # Will read from os.environ (default "0")
        )


def test_confirm_live_mode_env_wrong_value():
    """Test kill-switch blocks live mode with wrong env var value."""
    # Live mode with wrong env var value → should raise
    with pytest.raises(LiveModeNotEnabledError):
        confirm_live_enable(
            network_enabled=True,
            testnet=False,
            env_live_enable="yes",  # Must be exactly "1"
        )


def test_get_mode_description_shadow():
    """Test mode description for shadow mode."""
    desc = get_mode_description(network_enabled=False, testnet=False)
    assert "shadow" in desc.lower()
    assert "no-network" in desc.lower()


def test_get_mode_description_testnet():
    """Test mode description for testnet mode."""
    desc = get_mode_description(network_enabled=True, testnet=True)
    assert "testnet" in desc.lower()
    assert "network enabled" in desc.lower()


def test_get_mode_description_live():
    """Test mode description for live mode."""
    desc = get_mode_description(network_enabled=True, testnet=False)
    assert "LIVE" in desc
    assert "production" in desc.lower()


def test_matrix_all_modes():
    """Test all mode combinations systematically."""
    # Matrix of (network_enabled, testnet, env_var) -> should_raise
    test_cases = [
        (False, False, "0", False),  # Shadow: always safe
        (False, False, "1", False),  # Shadow: always safe
        (False, True, "0", False),   # Shadow with testnet flag: safe (network_enabled=False dominates)
        (True, True, "0", False),    # Testnet: safe
        (True, True, "1", False),    # Testnet: safe
        (True, False, "0", True),    # Live without env: blocked
        (True, False, "1", False),   # Live with env: allowed
    ]
    
    for network, testnet, env_var, should_raise in test_cases:
        if should_raise:
            with pytest.raises(LiveModeNotEnabledError):
                confirm_live_enable(network, testnet, env_var)
        else:
            confirm_live_enable(network, testnet, env_var)

