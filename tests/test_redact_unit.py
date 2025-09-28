from src.common.redact import redact, DEFAULT_PATTERNS


def test_redact_masks_tokens_and_kv():
    s = (
        "api_secret=SeCrEt12345678901234567890\n"
        "AKIAABCDEFGHIJKLMNOP\n"
        "hex: DEADBEEFDEADBEEFDEADBEEFDEADBEEF\n"
    )
    out = redact(s, DEFAULT_PATTERNS)
    # kv masked
    assert 'api_secret=****' in out or 'api_secret="****"' in out
    # AWS key masked
    assert 'AKIA' not in out
    # long hex masked
    assert 'DEADBEEFDEADBEEFDEADBEEFDEADBEEF' not in out
    # LF preserved
    assert out.endswith('\n')


