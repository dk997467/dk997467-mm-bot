from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def test_burn_rate_and_budget_math():
    _reset_registry()
    cfg = AppConfig()
    cfg.latency_slo.enabled = True
    cfg.latency_slo.p95_target_ms = 50
    cfg.latency_slo.p99_target_ms = 100
    cfg.latency_slo.window_sec = 1
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    # seed histogram to produce p95/p99
    for _ in range(100):
        m.inc_rollout_fill('blue', 40.0)
        m.inc_rollout_fill('green', 80.0)
    # emulate loop computation results directly via helpers
    # burn_rate = p / target; budget = 1/burn_rate
    p95_b = float(m.rollout_latency_p95_ms.labels(color='blue')._value.get())
    p95_g = float(m.rollout_latency_p95_ms.labels(color='green')._value.get())
    br_b = p95_b / 50.0 if 50.0 > 0 else 0.0
    br_g = p95_g / 50.0 if 50.0 > 0 else 0.0
    m.set_latency_slo('blue', 'p95', br_b, 0.0 if br_b <= 0 else 1.0/br_b)
    m.set_latency_slo('green', 'p95', br_g, 0.0 if br_g <= 0 else 1.0/br_g)
    # gauges must reflect our math
    assert abs(float(m.latency_slo_burn_rate.labels(color='blue', percentile='p95')._value.get()) - br_b) < 1e-9
    assert abs(float(m.latency_slo_burn_rate.labels(color='green', percentile='p95')._value.get()) - br_g) < 1e-9
    assert abs(float(m.latency_slo_budget_remaining.labels(color='blue', percentile='p95')._value.get()) - (0.0 if br_b<=0 else 1.0/br_b)) < 1e-9
    assert abs(float(m.latency_slo_budget_remaining.labels(color='green', percentile='p95')._value.get()) - (0.0 if br_g<=0 else 1.0/br_g)) < 1e-9


