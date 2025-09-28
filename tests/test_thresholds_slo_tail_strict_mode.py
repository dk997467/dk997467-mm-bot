import pytest
from src.deploy import thresholds as TH


def test_slo_tail_strict_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(TH, 'STRICT_THRESHOLDS', True, raising=False)
    bad = tmp_path / 'thr_bad.yaml'
    bad.write_text(
        """
canary_gate_per_symbol:
  BTCUSDT:
    slo_tail_p95_cap_ms: -5
        """.strip()+"\n",
        encoding='utf-8')
    with pytest.raises(ValueError):
        TH.refresh_thresholds(str(bad))


