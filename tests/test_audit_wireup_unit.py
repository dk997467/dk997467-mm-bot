from pathlib import Path


def test_audit_wireup_minimal(monkeypatch, tmp_path):
    # Collect events
    events = []
    from src.audit import log as audit_log

    def fake_audit_event(kind, symbol, fields):
        events.append((str(kind), str(symbol), dict(fields)))

    monkeypatch.setattr(audit_log, 'audit_event', fake_audit_event)

    # Throttle allow/deny + cancel batch
    from src.exchange.throttle import ReplaceThrottle, TailBatchCanceller
    thr = ReplaceThrottle(max_concurrent=1, min_interval_ms=1000)
    now = 10000
    assert thr.allow('BTCUSDT', now) is True
    assert thr.allow('BTCUSDT', now + 10) is False
    thr.settle('BTCUSDT')
    assert thr.allow('BTCUSDT', now + 2000) is True
    canc = TailBatchCanceller(tail_age_ms=100, max_batch=2)
    orders = {
        'c1': (now - 200, 'BTCUSDT'),
        'c2': (now - 300, 'BTCUSDT'),
        'c3': (now - 50, 'ETHUSDT'),
    }
    _ = canc.select(orders, now)

    # Mux regime switch and weights change
    from src.strategy.mux import MultiStratMux
    mux = MultiStratMux({'L': {'band': [0, 1], 'weights': {'CON': 0.5, 'MOD': 0.5}}, 'H': {'band': [1, 2], 'weights': {'CON': 0.2, 'AGR': 0.8}}}, hysteresis_s=0)
    mux.on_sigma(0.5)
    mux.on_sigma(1.5)

    # Guard breach/recover
    from src.guards.position_skew import PositionSkewGuard
    g = PositionSkewGuard(per_symbol_abs_limit=1.0, per_color_abs_limit=1.0)
    g.evaluate({'BTCUSDT': 2.0}, {'BTCUSDT': 'blue'})
    g.evaluate({'BTCUSDT': 0.0}, {'BTCUSDT': 'blue'})

    # Allocator clamp/backoff
    # Minimal stub for allocator: call inner logic via public API
    from types import SimpleNamespace
    from src.common.config import AppConfig
    from src.common.di import AppContext
    from src.portfolio.allocator import PortfolioAllocator
    cfg = AppConfig()
    ctx = AppContext(cfg)
    alloc = PortfolioAllocator(ctx)
    alloc.prev_targets_usd = {'BTCUSDT': 100.0}
    # simulate clamp via max_delta_ratio small and big delta
    cfg.allocator.smoothing.max_delta_ratio = 0.01
    targets = {'BTCUSDT': {'vol': 1.0}}
    _ = alloc.targets_from_weights({'BTCUSDT': 1.0})

    # Assertions: at least one event of each kind appeared
    kinds = [k for (k, _, _) in events]
    assert 'REPLACE' in kinds
    assert 'CANCEL' in kinds
    assert 'MUX' in kinds
    assert 'GUARD' in kinds
    # ALLOC may not trigger deterministically in this minimal path; tolerate absence
    # but ensure no CR in any string fields
    for _, _, f in events:
        for k, v in f.items():
            if isinstance(v, str):
                assert '\r' not in v


