from pathlib import Path
from tempfile import TemporaryDirectory

from src.common.config import ConfigLoader


def test_cfg_describe_stable_and_sorted():
    yml = """
allocator:
  smoothing:
    bias_cap_ratio: 0.2
    fee_bias_cap_ratio: 0.08
    max_delta_ratio: 0.15
    max_delta_abs_base_units: 0.0
    backoff_steps: [1.0, 0.7, 0.5]
guards:
  pos_skew:
    per_symbol_abs_limit: 100.0
    per_color_abs_limit: 0.0
"""
    with TemporaryDirectory() as td:
        p = Path(td) / 'config.yaml'
        p.write_text(yml, encoding='utf-8')
        cfg = ConfigLoader(config_path=str(p)).load()
        a = cfg.describe()
        b = cfg.describe()
        assert isinstance(a, str) and isinstance(b, str)
        assert a.endswith("\n") and b.endswith("\n")
        assert a == b
        # basics: lines sorted and floats with 6 decimals
        lines = [ln for ln in a.strip().split('\n') if ln]
        assert lines == sorted(lines)
        # check some expected keys present
        assert any(ln.startswith('allocator.smoothing.bias_cap=0.200000') for ln in lines)
        assert any(ln.startswith('allocator.smoothing.fee_bias_cap=0.080000') for ln in lines)


