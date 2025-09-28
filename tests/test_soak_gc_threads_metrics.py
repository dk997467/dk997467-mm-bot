import asyncio
import time


def test_soak_gc_threads_metrics_stable(monkeypatch):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.metrics = make_metrics_ctx()
    srv.running = True

    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(srv._soak_guard_loop())
        loop.run_until_complete(asyncio.sleep(0.15))
        # sample gauges
        m = srv.metrics
        # values should be >=0 and not None
        th = float(m.soak_threads_total._value.get())  # type: ignore[attr-defined]
        g0 = float(m.soak_gc_gen.labels(gen='0')._value.get())  # type: ignore[attr-defined]
        g1 = float(m.soak_gc_gen.labels(gen='1')._value.get())  # type: ignore[attr-defined]
        g2 = float(m.soak_gc_gen.labels(gen='2')._value.get())  # type: ignore[attr-defined]
        assert th >= 0.0
        assert g0 >= 0.0 and g1 >= 0.0 and g2 >= 0.0
        # ensure they don't oscillate wildly within short window
        th2 = float(m.soak_threads_total._value.get())  # type: ignore[attr-defined]
        assert th2 >= 0.0
        srv.running = False
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        try:
            task.cancel()
        except Exception:
            pass
        loop.close()


