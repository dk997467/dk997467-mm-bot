"""
Ramp snapshot cycle test.
"""
import json
import asyncio
from types import SimpleNamespace
from pathlib import Path


def test_rollout_ramp_snapshot_cycle(tmp_path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot(config_path="config.yaml", recorder=None, dry_run=True)
    bot._ramp_state = {
        'enabled': True,
        'step_idx': 2,
        'last': {'fills': {'blue': 10, 'green': 12}, 'rejects': {'blue': 1, 'green': 2}},
        'updated_ts': 123.0,
        'frozen': False,
    }
    snap = bot._to_ramp_snapshot()
    p = tmp_path / "ramp.json"
    p.write_text(json.dumps(snap, sort_keys=True, separators=(",", ":")), encoding='utf-8')

    bot2 = MarketMakerBot(config_path="config.yaml", recorder=None, dry_run=True)
    data = json.loads(p.read_text(encoding='utf-8'))
    bot2._load_ramp_snapshot(data)
    snap2 = bot2._to_ramp_snapshot()
    assert snap2['enabled'] is True
    assert snap2['step_idx'] == 2
    assert snap2['last']['fills']['blue'] == 10
    assert snap2['last']['rejects']['green'] == 2


