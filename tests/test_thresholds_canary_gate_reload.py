import textwrap
from pathlib import Path


def test_thresholds_canary_gate_reload(tmp_path):
    from src.deploy.thresholds import refresh_thresholds, current_thresholds_snapshot
    p = tmp_path / 'thr.yaml'
    p.write_text(textwrap.dedent(
        """
        canary_gate:
          max_reject_delta: 0.05
          max_latency_delta_ms: 80
          min_sample_fills: 1000
        """
    ).strip(), encoding='utf-8')
    summary = refresh_thresholds(str(p))
    snap = current_thresholds_snapshot()
    cg = snap['canary_gate']
    assert cg['max_reject_delta'] == 0.05
    assert cg['max_latency_delta_ms'] == 80
    assert cg['min_sample_fills'] == 1000

