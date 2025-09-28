import os


def test_snapshot_dir_fsync(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    calls = {"replace": 0, "fsync_dir": 0}

    def fake_replace(a,b):
        calls["replace"] += 1
    def fake_open_dir(p, flags):
        class F:
            def __init__(self): self.fd = 3
        return 3
    def fake_fsync(fd):
        if isinstance(fd, int):
            calls["fsync_dir"] += 1
    monkeypatch.setattr(os, 'replace', fake_replace)
    monkeypatch.setattr(os, 'open', fake_open_dir)
    monkeypatch.setattr(os, 'fsync', fake_fsync)
    # write via helper and ensure replace/fsync(dir)
    bot._atomic_json_write(str(tmp_path/"x.json"), {"a":1})
    # simulate rollout_state writer using helper too
    bot._rollout_state_snapshot_path = str(tmp_path/"state.json")
    bot._atomic_json_write(bot._rollout_state_snapshot_path, {"version":1})
    assert calls["replace"] >= 1
    assert calls["fsync_dir"] >= 1

