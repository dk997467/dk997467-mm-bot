from prometheus_client import REGISTRY
from types import SimpleNamespace
from src.metrics.exporter import Metrics


def reset_registry() -> None:
    """Legacy registry cleanup helper.
    
    NOTE: Registry cleanup is now handled by conftest.py autouse fixture.
    This function is kept for backwards compatibility with existing e2e tests.
    """
    try:
        collectors = list(REGISTRY._collector_to_names.keys())
        for col in collectors:
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def make_metrics_ctx() -> Metrics:
    # NOTE: Registry cleanup now handled by conftest.py, but keeping explicit
    # call here for e2e tests that may run in isolation
    reset_registry()
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                levels_per_side=1,
                min_time_in_book_ms=0,
                k_vola_spread=0.0,
                skew_coeff=0.0,
                imbalance_cutoff=0.0,
            ),
            limits=SimpleNamespace(max_create_per_sec=0, max_cancel_per_sec=0),
        )
    )
    return Metrics(ctx)


def seed_latency_tail(metrics: Metrics, *, blue_profile: list[float], green_profile: list[float]) -> None:
    """Seed rollout latency buckets for BLUE/GREEN using provided samples (ms)."""
    try:
        metrics.test_reset_latency()
    except Exception:
        pass
    for v in blue_profile:
        metrics.inc_rollout_fill('blue', float(v))
    for v in green_profile:
        metrics.inc_rollout_fill('green', float(v))
import asyncio
import json
from types import SimpleNamespace


class _Req:
    def __init__(self, path: str, headers: dict, query: dict | None = None):
        self.path = path
        self.headers = headers or {}
        self.rel_url = SimpleNamespace(path=path, query=query or {})
        self.method = "GET"


async def await_next_tick(sec: float = 1.2):
    await asyncio.sleep(sec)


def seed_reject_delta_high(metrics) -> None:
    metrics.test_reset_rollout()
    metrics.test_seed_rollout_counters(
        fills_blue=2000,
        fills_green=700,
        rejects_blue=20,
        rejects_green=140,
        split_expected_pct=35,
    )
    metrics.test_seed_rollout_latency_ms(blue_ms=25.0, green_ms=150.0)


def seed_healthy(metrics) -> None:
    metrics.test_reset_rollout()
    metrics.test_seed_rollout_counters(
        fills_blue=1000,
        fills_green=1000,
        rejects_blue=10,
        rejects_green=12,
        split_expected_pct=100,
    )
    metrics.test_seed_rollout_latency_ms(blue_ms=25.0, green_ms=28.0)


def seed_drift_observed(metrics, expected_pct: int, delta_pct: int, total_orders: int = 1000) -> None:
    obs = int(expected_pct) + int(delta_pct)
    metrics.test_set_rollout_split_observed_pct(obs_pct=float(obs), sample_total=int(total_orders))


async def tail_alerts(bot, headers: dict, n: int):
    req = _Req("/admin/alerts/log", headers, {"tail": str(int(n))})
    resp = await bot._admin_alerts_log(req)
    data = json.loads(resp.body.decode())
    return data.get("items", [])


