from cli.run_bot import MarketMakerBot


def _compute_delay(bot, base):
    import hmac
    seed = str(bot._allocator_snapshot_path)
    j = (int(hmac.new(seed.encode('utf-8'), b'alloc', 'sha1').hexdigest()[:8], 16) % 2001) - 1000
    frac = (j / 10000.0) * (2 * bot._allocator_jitter_frac)
    return max(1.0, base * (1.0 + frac))


def test_snapshot_jitter_deterministic(tmp_path):
    bot = MarketMakerBot(config_path=str(tmp_path / 'cfg.yaml'), recorder=None, dry_run=True)
    bot._allocator_snapshot_path = str(tmp_path / 'hwm.json')
    base = 60
    d1 = _compute_delay(bot, base)
    d2 = _compute_delay(bot, base)
    assert abs(d1 - d2) < 1e-9
    assert d1 >= base * 0.9 and d1 <= base * 1.1


