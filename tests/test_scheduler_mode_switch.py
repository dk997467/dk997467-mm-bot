def test_scheduler_mode_switch():
    from src.scheduler.tod import suggest_windows
    stats = {
        "08:00-10:00": {"median_spread_bps": 5.0, "vola_ewma": 10.0, "volume_norm": 0.2, "sample": 500},
        "10:00-12:00": {"median_spread_bps": 5.0, "vola_ewma": 10.0, "volume_norm": 0.9, "sample": 500},
    }
    neutral = suggest_windows(stats, {"top_k": 1, "min_sample": 200, "mode": "neutral"})
    aggressive = suggest_windows(stats, {"top_k": 1, "min_sample": 200, "mode": "aggressive"})
    assert neutral[0]['start'] in ("08:00","10:00")
    assert aggressive[0]['start'] in ("08:00","10:00")

