from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def _ctx(ps=0.5, cap=0.1, min_usd=100.0):
    po = {
        'budget_usd': 1000.0,
        'mode': 'manual',
        'manual_weights': {},
        'min_weight': 0.0,
        'max_weight': 1.0,
        'levels_per_side_min': 1,
        'levels_per_side_max': 10,
        'rebalance_minutes': 5,
        'ema_alpha': 0.0,
        'risk_parity_max_iterations': 50,
        'risk_parity_tolerance': 1e-6,
        'vol_eps': 1e-9,
        'budget': SimpleNamespace(pnl_sensitivity=ps, drawdown_soft_cap=cap, budget_min_usd=min_usd),
    }
    cfg = SimpleNamespace(portfolio=SimpleNamespace(**po))
    return SimpleNamespace(cfg=cfg, metrics=None)


def test_soft_factor_shape_and_min_guard():
    ctx = _ctx(ps=0.5, cap=0.2, min_usd=100.0)
    alloc = PortfolioAllocator(ctx)
    w = {'X': 0.5, 'Y': 0.5}
    # dd=0 -> soft=1
    t0 = alloc.targets_from_weights(w, equity_usd=1000.0, budget_available_usd=1000.0)
    assert t0['X'].target_usd == 500.0 and t0['Y'].target_usd == 500.0
    # dd = soft_cap -> x=1 -> soft = 1 - ps = 0.5
    # set HWM
    alloc.targets_from_weights(w, equity_usd=1000.0, budget_available_usd=1000.0)
    t1 = alloc.targets_from_weights(w, equity_usd=800.0, budget_available_usd=1000.0)
    assert abs(t1['X'].target_usd - 250.0) < 1e-9
    # monotonic: dd between 0 and soft_cap => soft in [1, 1-ps]
    alloc.targets_from_weights(w, equity_usd=900.0, budget_available_usd=1000.0)
    t_mid = alloc.targets_from_weights(w, equity_usd=860.0, budget_available_usd=1000.0)
    assert 250.0 <= t_mid['X'].target_usd <= 500.0
    # min guard: if t < min_usd -> 0
    ctx2 = _ctx(ps=0.5, cap=0.2, min_usd=100.0)
    alloc2 = PortfolioAllocator(ctx2)
    w2 = {'Z': 0.05, 'W': 0.95}
    # hwm and then strong dd & low avail to push Z below 100
    alloc2.targets_from_weights(w2, equity_usd=1000.0, budget_available_usd=200.0)
    t2 = alloc2.targets_from_weights(w2, equity_usd=700.0, budget_available_usd=200.0)
    assert t2['Z'].target_usd == 0.0


