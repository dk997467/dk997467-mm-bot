from types import SimpleNamespace


def test_safe_load_snapshot_size_limit(tmp_path):
    from src.portfolio.allocator import PortfolioAllocator
    # create large file >1MB
    big = tmp_path / 'big.json'
    big.write_bytes(b'{' + b'"x":' + b'0'*1_050_000 + b'}')
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
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=SimpleNamespace(inc_allocator_snapshot_load=lambda ok, ts: None))
    a = PortfolioAllocator(ctx)
    try:
        a.safe_load_snapshot(str(big))
        raise AssertionError("expected size error")
    except Exception:
        pass


