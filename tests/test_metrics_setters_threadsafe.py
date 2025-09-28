import threading
from types import SimpleNamespace
from src.metrics.exporter import Metrics


def test_metrics_setters_threadsafe():
    ctx = SimpleNamespace()
    m = Metrics(ctx)  # will construct Gauges, but we only call setters

    def worker():
        for _ in range(100):
            m.set_portfolio_budget_available_usd(123.0)
            m.set_portfolio_drawdown_pct(0.33)
            m.set_allocator_soft_factor(0.77)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    snap = m.get_portfolio_metrics_snapshot()
    assert 0.0 <= snap['drawdown_pct'] <= 1.0
    assert 0.0 <= snap['soft_factor'] <= 1.0


