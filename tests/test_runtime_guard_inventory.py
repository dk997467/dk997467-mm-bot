from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_runtime_guard_inventory_reasons():
    cfg = RuntimeGuardConfig(
        enabled=True,
        consecutive_breaches_to_pause=1,
        recovery_minutes=10.0,
        max_position_notional_usd=50.0,
        max_gross_exposure_usd=80.0,
        max_position_pct_budget=10.0,
    )
    g = RuntimeGuard(cfg)
    # budget 1000, snapshot net 120, gross 200
    g.set_inventory_snapshot({"BTCUSDT": 120.0, "ETHUSDT": -80.0}, budget_usd=1000.0)
    # evaluate returns inventory reason bit set
    reason = g.evaluate()
    assert reason != 0

