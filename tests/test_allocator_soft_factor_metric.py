from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


class _MetricsStub:
    def __init__(self):
        self.v = {}
    def set_portfolio_budget_available_usd(self, v): self.v['avail'] = float(v)
    def set_portfolio_drawdown_pct(self, v): self.v['dd'] = float(v)
    def set_allocator_soft_factor(self, v): self.v['soft'] = float(v)


def _ctx(ps=0.25, cap=0.1):
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
        'budget': SimpleNamespace(pnl_sensitivity=ps, drawdown_soft_cap=cap, budget_min_usd=0.0),
    }
    cfg = SimpleNamespace(portfolio=SimpleNamespace(**po))
    return SimpleNamespace(cfg=cfg, metrics=_MetricsStub())


def test_soft_factor_metric_values():
    ctx = _ctx(ps=0.25, cap=0.1)
    alloc = PortfolioAllocator(ctx)
    w = {'A': 1.0}
    # dd=0 -> soft=1.0
    alloc.targets_from_weights(w, equity_usd=1000.0, budget_available_usd=1000.0)
    assert abs(ctx.metrics.v.get('soft', 0.0) - 1.0) < 1e-9
    # dd>=soft_cap -> x=1 -> soft=1-ps=0.75
    alloc.targets_from_weights(w, equity_usd=800.0, budget_available_usd=1000.0)
    assert abs(ctx.metrics.v.get('soft', 0.0) - 0.75) < 1e-9


