from pathlib import Path


def test_promql_record_rule_p99_exists_and_valid(test_paths):
    # Use universal fixture for project root
    path = test_paths.project_root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml'
    # Normalize line endings (handle both LF and CRLF)
    text = path.read_text(encoding='ascii').replace('\r\n', '\n')
    assert 'record: mm:order_age_p99_ms_5m' in text
    assert 'histogram_quantile(0.99' in text
    # Check for the correct expression format (note: double )) before by)
    assert '[5m])) by (le, symbol)) * 1000' in text
    # ensure single occurrence at most
    assert text.count('record: mm:order_age_p99_ms_5m') == 1


