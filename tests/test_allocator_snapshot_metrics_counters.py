from types import SimpleNamespace


class _M:
    def __init__(self):
        self.w_ok = 0
        self.w_fail = 0
        self.l_ok = 0
        self.l_fail = 0
        self.w_ts = 0.0
        self.l_ts = 0.0
    # required setters used elsewhere
    def set_allocator_hwm_equity_usd(self, v): pass
    def set_portfolio_budget_available_usd(self, v): pass
    def set_portfolio_drawdown_pct(self, v): pass
    def set_allocator_soft_factor(self, v): pass
    # emulate metric helpers
    def inc_allocator_snapshot_write(self, ok: bool, ts: float):
        if ok:
            self.w_ok += 1; self.w_ts = ts
        else:
            self.w_fail += 1
    def inc_allocator_snapshot_load(self, ok: bool, ts: float):
        if ok:
            self.l_ok += 1; self.l_ts = ts
        else:
            self.l_fail += 1
    def get_portfolio_metrics_snapshot(self):
        return {"allocator_last_write_ts": self.w_ts, "allocator_last_load_ts": self.l_ts}


def test_allocator_snapshot_metrics_counters():
    from src.portfolio.allocator import PortfolioAllocator
    m = _M()
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
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=m)
    a = PortfolioAllocator(ctx)
    # Simulate load ok
    ctx.metrics.inc_allocator_snapshot_load(ok=True, ts=1.0)
    # Simulate write fail and ok
    ctx.metrics.inc_allocator_snapshot_write(ok=False, ts=2.0)
    ctx.metrics.inc_allocator_snapshot_write(ok=True, ts=3.0)
    snap = ctx.metrics.get_portfolio_metrics_snapshot()
    assert m.w_ok == 1 and m.w_fail == 1 and m.l_ok == 1
    assert snap["allocator_last_write_ts"] == 3.0 and snap["allocator_last_load_ts"] == 1.0


