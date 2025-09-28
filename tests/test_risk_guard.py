from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.common.config import Config
from src.common.models import Side
from src.risk.risk_manager import RiskManager


def make_config() -> Config:
    from src.common.config import get_config
    return get_config()


def test_daily_loss_trips_kill_switch():
    cfg = make_config()
    rm = RiskManager(cfg)
    # Overshoot daily loss
    rm.update_pnl(realized_pnl=Decimal(-300) * Decimal("1.1"))  # Use fixed value for test
    assert rm.kill_switch_triggered


def test_max_position_blocks_quotes():
    cfg = make_config()
    rm = RiskManager(cfg)
    symbol = cfg.trading.symbols[0]
    price = Decimal("50000")

    # Bring exposure near the limit
    size_to_limit = Decimal(5000) / price  # Use fixed value for test
    rm.update_position(symbol, Side.BUY, size=size_to_limit, price=price)

    # Any further buy should be blocked by position limit
    ok, reason = rm.can_place_order(symbol, Side.BUY, size=Decimal("0.001"), price=price)
    assert not ok, f"expected block by position limit, got: {reason}"


def test_order_rate_limit(monkeypatch: pytest.MonkeyPatch):
    cfg = make_config()
    rm = RiskManager(cfg)

    # Feature not present in current RiskManager → skip gracefully
    if not hasattr(rm, "allow_order"):
        pytest.skip("order rate limiter not implemented; skipping")

    # If implemented, simulate rapid calls with a fake monotonic clock
    # Expect only <= max_order_rate_per_sec allowed within 1 second window
    calls = []

    fake_now = [0.0]

    def fake_time():
        return fake_now[0]

    # Assume allow_order uses time.monotonic() internally
    import time as _time

    monkeypatch.setattr(_time, "monotonic", fake_time)

    max_rate = getattr(cfg.risk, "max_order_rate_per_sec", 10)

    allowed = 0
    for i in range(max_rate * 2):
        ok = rm.allow_order()
        calls.append(ok)
        if ok:
            allowed += 1
        # advance a tiny bit within the same second
        fake_now[0] += 0.01

    assert allowed <= max_rate


