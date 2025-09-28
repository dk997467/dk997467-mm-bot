"""
Logging utilities for the market maker bot.
"""

import time
from typing import Dict, Any


class RateLimitedLogger:
    """Rate-limited logger to prevent log spam."""
    
    def __init__(self, rate_limit_seconds: float = 60.0):
        """Initialize rate-limited logger.
        
        Args:
            rate_limit_seconds: Minimum time between identical log messages
        """
        self.rate_limit_seconds = rate_limit_seconds
        self._last_logs: Dict[str, float] = {}
    
    def _should_log(self, message: str) -> bool:
        """Check if message should be logged based on rate limiting."""
        now = time.time()
        if message not in self._last_logs:
            self._last_logs[message] = now
            return True
        
        if now - self._last_logs[message] >= self.rate_limit_seconds:
            self._last_logs[message] = now
            return True
        
        return False
    
    def warn_once(self, message: str, *args, **kwargs) -> None:
        """Log warning message only once per rate limit period."""
        if self._should_log(message):
            print(f"WARNING: {message}", *args, **kwargs)
    
    def error_once(self, message: str, *args, **kwargs) -> None:
        """Log error message only once per rate limit period."""
        if self._should_log(message):
            print(f"ERROR: {message}", *args, **kwargs)
    
    def info_once(self, message: str, *args, **kwargs) -> None:
        """Log info message only once per rate limit period."""
        if self._should_log(message):
            print(f"INFO: {message}", *args, **kwargs)
    
    def debug_once(self, message: str, *args, **kwargs) -> None:
        """Log debug message only once per rate limit period."""
        if self._should_log(message):
            print(f"DEBUG: {message}", *args, **kwargs)
