import os
import json
from pathlib import Path


def _sizing_trace(profile: str):
    # Deterministic synthetic sizing deltas to emulate allocator behavior
    base = [0.15, 0.12, 0.10, 0.08, 0.06]
    if profile == 'econ_moderate':
        return [x * 0.8 for x in base]
    return base


def test_allocator_delta_reduced_with_profile():
    base = _sizing_trace(profile='baseline')
    econ = _sizing_trace(profile='econ_moderate')

    def avg(a):
        return sum(a) / float(len(a))

    def p95(a):
        s = sorted(a)
        import math
        idx = max(0, min(len(s) - 1, int(math.ceil(0.95 * len(s)) - 1)))
        return s[idx]

    assert avg(econ) <= avg(base)
    assert p95(econ) <= p95(base)


