from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest

from src.common.config import ConfigLoader


def _load_cfg(yaml_text: str):
    with TemporaryDirectory() as td:
        p = Path(td) / 'config.yaml'
        p.write_text(yaml_text, encoding='utf-8')
        return ConfigLoader(config_path=str(p)).load()


def test_fee_bias_cap_ratio_ok():
    cfg = _load_cfg("allocator:\n  smoothing:\n    fee_bias_cap: 0.05\n")
    assert cfg.allocator.smoothing.fee_bias_cap == 0.05


# Legacy alias behaviors would need dedicated loader support; placeholder test asserts current behavior is float
def test_fee_bias_cap_legacy_type_ok():
    cfg = _load_cfg("allocator:\n  smoothing:\n    fee_bias_cap: 0.08\n")
    assert cfg.allocator.smoothing.fee_bias_cap == 0.08


