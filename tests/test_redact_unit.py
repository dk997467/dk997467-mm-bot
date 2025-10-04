from src.common.redact import redact, DEFAULT_PATTERNS


def test_redact_masks_tokens_and_kv():
    s = (
        "api_secret=SeCrEt12345678901234567890\n"
        "AKIAABCDEFGHIJKLMNOP\n"
        "hex: DEADBEEFDEADBEEFDEADBEEFDEADBEEF\n"
    )
    out = redact(s)  # Uses DEFAULT_PATTERNS by default
    # kv masked (redact keeps prefix but masks rest)
    assert 'SeCrEt12345678901234567890' not in out, "Secret should be masked"
    assert 'api_secret=' in out, "Key should be preserved"
    # AWS key masked
    assert 'AKIAABCDEFGHIJKLMNOP' not in out, "AWS key should be masked"
    # long hex masked
    assert 'DEADBEEFDEADBEEFDEADBEEFDEADBEEF' not in out, "Hex should be masked"
    # LF preserved
    assert out.endswith('\n')


