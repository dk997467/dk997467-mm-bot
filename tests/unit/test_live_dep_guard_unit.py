"""
Unit tests for live trading dependency guards.

Tests that exchange SDK imports are properly guarded and provide clear
error messages when optional dependencies are not installed.
"""

import sys
from unittest.mock import patch

import pytest


def test_bybit_sdk_guard_missing_dependency():
    """Test that missing bybit-connector raises RuntimeError with helpful message."""
    # Simulate missing bybit_connector package
    with patch.dict(sys.modules, {"bybit_connector": None}):
        from tools.live._sdk_guard import load_bybit_sdk
        
        with pytest.raises(RuntimeError) as exc_info:
            load_bybit_sdk()
        
        error_msg = str(exc_info.value)
        
        # Verify error message contains installation instructions
        assert "bybit-connector" in error_msg.lower()
        assert "pip install -e .[live]" in error_msg
        assert "requirements_live.txt" in error_msg


def test_bybit_sdk_guard_available():
    """Test that guard returns module when SDK is installed."""
    # Create a mock bybit_connector module
    mock_bybit = type("MockBybitModule", (), {"__name__": "bybit_connector"})()
    
    with patch.dict(sys.modules, {"bybit_connector": mock_bybit}):
        from tools.live._sdk_guard import load_bybit_sdk
        
        # Should not raise
        result = load_bybit_sdk()
        
        # Should return the mock module
        assert result is mock_bybit


def test_bybit_sdk_guard_import_error_chain():
    """Test that ImportError is properly chained to RuntimeError."""
    with patch.dict(sys.modules, {"bybit_connector": None}):
        from tools.live._sdk_guard import load_bybit_sdk
        
        with pytest.raises(RuntimeError) as exc_info:
            load_bybit_sdk()
        
        # Verify exception chaining
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ImportError)


def test_bybit_sdk_guard_error_message_format():
    """Test that error message is well-formatted and actionable."""
    with patch.dict(sys.modules, {"bybit_connector": None}):
        from tools.live._sdk_guard import load_bybit_sdk
        
        with pytest.raises(RuntimeError) as exc_info:
            load_bybit_sdk()
        
        error_msg = str(exc_info.value)
        
        # Verify error message structure
        assert "Bybit SDK" in error_msg
        assert "not installed" in error_msg
        assert "pip install" in error_msg
        
        # Verify both installation methods are mentioned
        assert "[live]" in error_msg
        assert "requirements_live.txt" in error_msg

