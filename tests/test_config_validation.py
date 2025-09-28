from pathlib import Path
from tempfile import TemporaryDirectory
import re

from src.common.config import ConfigLoader


def _load_cfg_text(yaml_text: str):
    with TemporaryDirectory() as td:
        p = Path(td) / 'config.yaml'
        p.write_text(yaml_text, encoding='utf-8')
        return ConfigLoader(config_path=str(p)).load()


def test_fee_bias_cap_ratio_ok():
    cfg = _load_cfg_text("allocator:\n  smoothing:\n    fee_bias_cap_ratio: 0.08\n")
    assert abs(cfg.allocator.smoothing.fee_bias_cap - 0.08) <= 1e-12


def test_fee_bias_cap_alias_ratio():
    # legacy fee_bias_cap -> fee_bias_cap_ratio
    cfg = _load_cfg_text("allocator:\n  smoothing:\n    fee_bias_cap: 0.08\n")
    assert abs(cfg.allocator.smoothing.fee_bias_cap - 0.08) <= 1e-12


def test_fee_bias_cap_alias_bps():
    cfg = _load_cfg_text("allocator:\n  smoothing:\n    fee_bias_cap_bps: 800\n")
    assert abs(cfg.allocator.smoothing.fee_bias_cap - 0.08) <= 1e-12


def test_bias_cap_alias_ratio():
    cfg = _load_cfg_text("allocator:\n  smoothing:\n    bias_cap: 0.2\n")
    assert abs(cfg.allocator.smoothing.bias_cap - 0.2) <= 1e-12


def test_fee_bias_cap_ratio_range_negative():
    try:
        _load_cfg_text("allocator:\n  smoothing:\n    fee_bias_cap_ratio: -0.01\n")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert str(e) == "E_CFG_RANGE:allocator.smoothing.fee_bias_cap_ratio must be in [0.0,1.0]"


def test_fee_bias_cap_bps_overflow():
    try:
        _load_cfg_text("allocator:\n  smoothing:\n    fee_bias_cap_bps: 20000\n")
        assert False, "Expected ValueError"
    except ValueError as e:
        # After conversion, >1.0 should fail ratio range
        assert str(e) == "E_CFG_RANGE:allocator.smoothing.fee_bias_cap_ratio must be in [0.0,1.0]"


def test_backoff_steps_invalid():
    try:
        _load_cfg_text("allocator:\n  smoothing:\n    backoff_steps: [1.2]\n")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "E_CFG_RANGE:allocator.smoothing.backoff_steps values must be in (0.0,1.0]" == str(e)


