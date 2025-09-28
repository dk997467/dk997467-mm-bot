from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def test_allocator_hwm_snapshot_cycle():
    # Init
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
    ctx1 = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=None)
    a1 = PortfolioAllocator(ctx1)
    # raise HWM via targets call
    a1.targets_from_weights({'A': 1.0}, equity_usd=1234.5, budget_available_usd=1000.0)
    snap = a1.to_snapshot()
    # Load into new allocator
    ctx2 = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=None)
    a2 = PortfolioAllocator(ctx2)
    a2.load_snapshot(snap)
    assert abs(a2.get_hwm_equity_usd() - 1234.5) < 1e-9


