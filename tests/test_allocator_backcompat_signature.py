from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def _ctx():
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
        'budget': SimpleNamespace(pnl_sensitivity=0.5, drawdown_soft_cap=0.1, budget_min_usd=0.0),
    }
    cfg = SimpleNamespace(portfolio=SimpleNamespace(**po))
    return SimpleNamespace(cfg=cfg, metrics=None)


def test_targets_from_weights_backcompat_signature():
    ctx = _ctx()
    alloc = PortfolioAllocator(ctx)
    w = {'A': 0.5, 'B': 0.5}
    # old signature: no kwargs
    t_old = alloc.targets_from_weights(w)
    assert t_old['A'].target_usd == 500.0 and t_old['B'].target_usd == 500.0
    # new signature with kwargs: avail=600, dd=0 -> soft=1 -> 300 each
    t_new = alloc.targets_from_weights(w, equity_usd=1000.0, budget_available_usd=600.0)
    assert t_new['A'].target_usd == 300.0 and t_new['B'].target_usd == 300.0


