# Allocator fixed-point clamp behavior equivalence test
from types import SimpleNamespace


def test_allocator_fixed_point_clamp():
    from src.portfolio.allocator import PortfolioAllocator
    from src.common.di import AppContext

    # Config with budget and guard
    portfolio_cfg = SimpleNamespace(
        mode="manual",
        min_weight=0.05,
        max_weight=0.7,
        levels_per_side_min=1,
        levels_per_side_max=10,
        ema_alpha=1.0,
        budget_usd=10000.0,
        budget=SimpleNamespace(drawdown_soft_cap=0.2, pnl_sensitivity=0.5, budget_min_usd=5.0),
        manual_weights={"AAA": 0.5, "BBB": 0.3, "CCC": 0.2},
    )
    cfg = SimpleNamespace(portfolio=portfolio_cfg)
    ctx = SimpleNamespace(cfg=cfg)

    alloc = PortfolioAllocator(AppContext(cfg))

    # Deterministic weights from manual
    stats = {"AAA": {}, "BBB": {}, "CCC": {}}
    weights = alloc.compute_weights(stats, mode="manual")
    # Use HWM/equity to trigger non-zero softening
    equity_usd = 8000.0
    alloc._hwm_equity_usd = 10000.0

    # Compute targets twice, ensure determinism and constraints
    t1 = alloc.targets_from_weights(weights, equity_usd=equity_usd, budget_available_usd=7000.0)
    t2 = alloc.targets_from_weights(weights, equity_usd=equity_usd, budget_available_usd=7000.0)
    assert {k: (v.target_usd, v.max_levels) for k, v in t1.items()} == {
        k: (v.target_usd, v.max_levels) for k, v in t2.items()
    }

    # Sum constraints: Σtargets ≤ avail*soft
    avail = 7000.0
    soft = alloc.metrics._allocator_soft_factor if getattr(alloc, 'metrics', None) else 1.0
    sum_targets = sum(v.target_usd for v in t1.values())
    assert sum_targets <= avail * soft + 1e-6

    # Min guard: values below budget_min_usd are zeroed
    assert all((v.target_usd == 0.0 or v.target_usd >= portfolio_cfg.budget.budget_min_usd) for v in t1.values())

    # Clamp determinism: when reducing, zeroed symbols form a lexicographic suffix
    t3 = alloc.targets_from_weights(weights, equity_usd=equity_usd, budget_available_usd=100.0)
    ordered = sorted(t3.keys())
    zeroed = [s for s in ordered if t3[s].target_usd == 0.0]
    if zeroed:
        assert zeroed == ordered[-len(zeroed):]
