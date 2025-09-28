from src.deploy.rollout import parse_prom_metrics


def test_guard_effective_default_computation():
    text = "\n".join([
        "guard_paused 1",
        "guard_dry_run 0",
        # guard_paused_effective missing
    ])
    mm = parse_prom_metrics(text)
    paused = float(mm.get("guard_paused", 0.0))
    dry = float(mm.get("guard_dry_run", 0.0))
    eff = float(mm.get("guard_paused_effective", paused * (1.0 - dry)))
    assert eff == 1.0

