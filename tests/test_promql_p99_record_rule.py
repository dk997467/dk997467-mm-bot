from pathlib import Path


def test_promql_record_rule_p99_exists_and_valid():
    root = Path(__file__).resolve().parents[1]
    path = root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml'
    data = path.read_bytes()
    # LF or single-line allowed, but no CRLF
    assert b"\r\n" not in data
    text = data.decode('ascii')
    assert 'record: mm:order_age_p99_ms_5m' in text
    assert 'histogram_quantile(0.99' in text
    assert '[5m]) by (le, symbol)) * 1000' in text
    # ensure single occurrence at most
    assert text.count('record: mm:order_age_p99_ms_5m') == 1


