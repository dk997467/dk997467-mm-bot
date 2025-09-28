import os
import tempfile

import pytest

from src.deploy import thresholds as thr


def _write_yaml(tmp_path: str, content: str) -> str:
    p = os.path.join(tmp_path, "thresholds_bad.yaml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_canary_thresholds_strict_mode_raises_value_error():
    d = tempfile.mkdtemp()
    old_strict = thr.STRICT_THRESHOLDS
    thr.STRICT_THRESHOLDS = True
    try:
        # invalid override: negative min_sample_fills and string latency
        yaml_text = (
            "canary_gate_per_symbol:\n"
            "  BTCUSDT:\n"
            "    min_sample_fills: -10\n"
            "    max_latency_delta_ms: bad\n"
        )
        path = _write_yaml(d, yaml_text)
        with pytest.raises(ValueError):
            thr.refresh_thresholds(path)
    finally:
        thr.STRICT_THRESHOLDS = old_strict
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


