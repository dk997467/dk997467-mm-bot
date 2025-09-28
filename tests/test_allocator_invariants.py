"""
Allocator invariants: sum=1, clamp [min,max], manual normalization, new symbols get min_weight.
"""

from unittest.mock import Mock

from src.common.config import PortfolioConfig
from src.portfolio.allocator import PortfolioAllocator
from src.common.di import AppContext


def _ctx(cfg: PortfolioConfig) -> AppContext:
    mock_app_config = Mock()
    mock_app_config.portfolio = cfg
    return AppContext(cfg=mock_app_config)


def test_sum_to_one_and_clamp_manual_with_missing_symbols():
    cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.7},  # missing ETHUSDT provided via stats
        budget_usd=10000.0,
        min_weight=0.1,
        max_weight=0.6,
    )
    ctx = _ctx(cfg)
    alloc = PortfolioAllocator(ctx)
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.03}}
    w = alloc.compute_weights(stats)
    assert abs(sum(w.values()) - 1.0) <= 1e-9
    for v in w.values():
        assert cfg.min_weight - 1e-12 <= v <= cfg.max_weight + 1e-12
    # Missing symbol got at least min_weight
    assert w["ETHUSDT"] >= cfg.min_weight


def test_sum_to_one_and_clamp_inverse_vol():
    cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.05,
        max_weight=0.5,
    )
    ctx = _ctx(cfg)
    alloc = PortfolioAllocator(ctx)
    stats = {"A": {"vol": 0.02}, "B": {"vol": 0.01}, "C": {"vol": 0.05}}
    w = alloc.compute_weights(stats)
    assert abs(sum(w.values()) - 1.0) <= 1e-9
    for v in w.values():
        assert cfg.min_weight - 1e-12 <= v <= cfg.max_weight + 1e-12


def test_sum_to_one_and_clamp_risk_parity():
    cfg = PortfolioConfig(
        mode="risk_parity",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
    )
    ctx = _ctx(cfg)
    alloc = PortfolioAllocator(ctx)
    stats = {"X": {"vol": 0.03}, "Y": {"vol": 0.06}}
    w = alloc.compute_weights(stats)
    assert abs(sum(w.values()) - 1.0) <= 1e-9
    for v in w.values():
        assert cfg.min_weight - 1e-12 <= v <= cfg.max_weight + 1e-12


