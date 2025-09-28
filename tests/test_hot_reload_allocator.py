"""
Hot-reload of portfolio parameters forces immediate rebalance on next loop tick.
"""

import asyncio
from types import SimpleNamespace

from src.portfolio.allocator import PortfolioAllocator


def test_compute_weights_override_mode_arg():
    # Minimal smoke: ensure mode arg is respected for determinism in tests
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(
        budget_usd=1000.0, mode="manual", manual_weights={}, min_weight=0.1, max_weight=0.9, ema_alpha=0.3,
        levels_per_side_min=1, levels_per_side_max=10
    )))
    alloc = PortfolioAllocator(ctx)  # type: ignore[arg-type]
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    w_inv = alloc.compute_weights(stats, mode="inverse_vol")
    assert abs(sum(w_inv.values()) - 1.0) <= 1e-9
    assert set(w_inv.keys()) == set(stats.keys())


