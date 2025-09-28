"""
FakeClock for deterministic time in tests.
"""


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start: float = 0.0):
        self.t = float(start)
    
    def time(self) -> float:
        """Return current fake time."""
        return self.t
    
    def tick(self, dt: float) -> None:
        """Advance fake time by dt seconds."""
        self.t += float(dt)
    
    def set(self, t: float) -> None:
        """Set fake time to specific value."""
        self.t = float(t)
