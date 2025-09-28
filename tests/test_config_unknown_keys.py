import io
import yaml
import pytest

from src.common.config import ConfigLoader


def test_unknown_key_detection(tmp_path):
    data = {
        "strategy": {"min_spread_bps": 2, "foo": 1},  # unknown key 'foo'
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data))

    loader = ConfigLoader(str(p))
    with pytest.raises(ValueError) as ei:
        loader.load()
    assert "strategy.foo" in str(ei.value)

