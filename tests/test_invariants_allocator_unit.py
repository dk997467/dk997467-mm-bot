import math
import pytest

from src.common.invariants import assert_finite, assert_range


def test_assert_finite_raises_one_line():
    with pytest.raises(ValueError) as e:
        assert_finite(float('nan'), code='E_CFG_ALLOC')
    msg = str(e.value)
    assert msg.startswith('E_CFG_ALLOC: ')
    assert '\n' not in msg


def test_assert_range():
    with pytest.raises(ValueError) as e:
        assert_range(1000000, 0, 100, code='E_CFG_THROTTLE')
    assert str(e.value).startswith('E_CFG_THROTTLE: ')


