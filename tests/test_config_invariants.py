import pytest

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, validate_invariants


def test_invariant_min_le_max_spread():
    cfg = AppConfig()
    cfg.strategy.min_spread_bps = 5
    cfg.strategy.max_spread_bps = 2
    with pytest.raises(ValueError):
        validate_invariants(cfg)


def test_invariant_levels_per_side():
    cfg = AppConfig()
    cfg.strategy.levels_per_side = 0
    with pytest.raises(ValueError):
        validate_invariants(cfg)


def test_invariant_k_vola_spread():
    cfg = AppConfig()
    cfg.strategy.k_vola_spread = 0
    with pytest.raises(ValueError):
        validate_invariants(cfg)


def test_invariant_create_cancel_limits():
    cfg = AppConfig()
    cfg.limits.max_create_per_sec = 0
    with pytest.raises(ValueError):
        validate_invariants(cfg)
    cfg = AppConfig()
    cfg.limits.max_cancel_per_sec = 25
    with pytest.raises(ValueError):
        validate_invariants(cfg)


def test_invariant_min_time_in_book():
    cfg = AppConfig()
    cfg.strategy.min_time_in_book_ms = 50
    with pytest.raises(ValueError):
        validate_invariants(cfg)

