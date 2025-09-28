from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


class _M:
    def __init__(self):
        self.hwm = 0.0
    def set_allocator_hwm_equity_usd(self, v): self.hwm = float(v)
    def set_portfolio_budget_available_usd(self, v): pass
    def set_portfolio_drawdown_pct(self, v): pass
    def set_allocator_soft_factor(self, v): pass


def test_hwm_metric_updates_on_load_and_increase():
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
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=_M())
    a = PortfolioAllocator(ctx)
    # load snapshot
    a.load_snapshot({"version": 1, "hwm_equity_usd": 500.0})
    assert ctx.metrics.hwm == 500.0
    # increase via targets call
    a.targets_from_weights({'A': 1.0}, equity_usd=1200.0, budget_available_usd=1000.0)
    assert ctx.metrics.hwm == 1200.0


