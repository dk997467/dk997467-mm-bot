import json
from pathlib import Path

import yaml

from src.cli.profile import apply_profile


def test_apply_profile_econ_moderate(tmp_path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / 'fixtures' / 'profile' / 'base_config.yaml').read_text(encoding='ascii'))
    out = apply_profile(base, 'econ_moderate')

    # Check allowed fields changed to expected values
    exp = json.loads((root / 'fixtures' / 'profile' / 'econ_expected.json').read_text(encoding='ascii'))

    # Subset compare
    def get(d, path):
        for p in path:
            d = d[p]
        return d

    assert get(out, ['allocator','smoothing','max_delta_ratio']) == exp['allocator']['smoothing']['max_delta_ratio']
    assert get(out, ['allocator','smoothing','backoff_steps']) == exp['allocator']['smoothing']['backoff_steps']
    assert get(out, ['signals','impact_cap_ratio']) == exp['signals']['impact_cap_ratio']
    assert get(out, ['latency_boost','replace','min_interval_ms']) == exp['latency_boost']['replace']['min_interval_ms']
    assert get(out, ['latency_boost','tail_batch','max_batch']) == exp['latency_boost']['tail_batch']['max_batch']
    assert get(out, ['canary','fraction']) == exp['canary']['fraction']
    assert get(out, ['logging','trace_alloc_micro']) == exp['logging']['trace_alloc_micro']

    # Unknown keys not introduced
    assert 'nonexistent' not in out

    # Simulate validator: ensure numeric ranges plausible (no E_CFG_ exceptions here)
    assert 0.0 < out['allocator']['smoothing']['max_delta_ratio'] <= 1.0


