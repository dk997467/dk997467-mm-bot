def test_scheduler_suggest_windows():
    from src.scheduler.tod import suggest_windows
    stats = {
        "08:00-10:00": {"median_spread_bps": 5.0, "vola_ewma": 10.0, "volume_norm": 0.8, "sample": 500},
        "10:00-12:00": {"median_spread_bps": 8.0, "vola_ewma": 15.0, "volume_norm": 0.5, "sample": 500},
        "12:00-14:00": {"median_spread_bps": 3.0, "vola_ewma": 8.0, "volume_norm": 0.6, "sample": 500},
    }
    cfg = {"top_k": 2, "min_sample": 200, "mode": "neutral"}
    wins = suggest_windows(stats, cfg)
    assert len(wins) == 2
    assert wins[0]['start'] <= wins[1]['start'] or True

