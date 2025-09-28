import json


def test_yaml_like_parser_fuzz(tmp_path):
    from src.deploy.thresholds import load_thresholds_from_yaml
    # almost valid YAMLs that should fail with ValueError
    bad_cases = [
        "",  # empty
        "# only comment\n# still comment\n",
        "throttle:\n  global:\n    max_throttle_backoff_ms: not_a_number\n",
        "canary_gate:\n  max_latency_delta_ms: -5\n",  # negative later filtered, but presence alone ok; parser returns dict -> refresh will validate
        "\tindent_with_tab: 1\n",  # non-space indents should be tolerated but we keep simple -> skip/no keys
    ]
    for i, txt in enumerate(bad_cases):
        p = tmp_path / f"bad_{i}.yaml"
        p.write_text(txt, encoding='utf-8')
        try:
            load_thresholds_from_yaml(str(p))
            # if parsed, require at least recognized top-level key
            # our cases either empty or invalid structure, expect failure
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_yaml_like_parser_non_ascii(tmp_path):
    from src.deploy.thresholds import load_thresholds_from_yaml
    p = tmp_path / "non_ascii.yaml"
    p.write_bytes("throttle:\n  global:\n    k: \u044f\n".encode("utf-8"))
    try:
        load_thresholds_from_yaml(str(p))
        assert False, "expected ValueError for non-ascii"
    except ValueError as e:
        # error message contains failed_to_parse_yaml non_ascii
        s = str(e)
        assert "non_ascii" in s


