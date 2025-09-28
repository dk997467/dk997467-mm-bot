def test_units_suffix_lint_example():
    # Lightweight lint: ensure numeric keys end with one of allowed suffixes
    allowed = ('_bps', '_usd', '_eur', '_base_units', '_ratio')
    sample = {
        'allocator': {
            'smoothing': {
                'max_delta_ratio': 0.15,
                'max_delta_abs_base_units': 0.0,
                'bias_cap_ratio': 0.2,
                'fee_bias_cap_ratio': 0.08,
            }
        },
        'guards': {
            'pos_skew': {
                'per_symbol_abs_limit': 100.0,
                'per_color_abs_limit': 0.0,
            }
        },
        'fees': {
            'bybit': {
                'distance_usd_threshold': 25000.0,
                'min_improvement_bps': 0.2,
            }
        }
    }

    def walk(d, path_prefix=""):
        for k, v in d.items():
            path = f"{path_prefix}.{k}" if path_prefix else k
            if isinstance(v, dict):
                walk(v, path)
            else:
                if isinstance(v, (int, float)):
                    assert any(k.endswith(suf) for suf in allowed), f"Key without units suffix: {path}"

    walk(sample)


