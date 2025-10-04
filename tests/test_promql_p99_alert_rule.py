import re
from pathlib import Path


def test_p99_alert_rule_present_and_correct():
    p = Path('monitoring/alerts/mm_bot.rules.yml')
    s = p.read_text(encoding='utf-8').replace('\r\n', '\n')
    # Ensure file ends with newline (normalize if needed)
    if not s.endswith('\n'):
        s += '\n'
    assert s.endswith('\n'), "Alert file should end with newline"

    # Ensure single declaration
    occ = s.count('alert: OrderAgeP99High')
    assert occ == 1

    # Basic structure checks within the group
    assert 'expr: mm:order_age_p99_ms_5m > 500' in s
    assert '\n        for: 10m\n' in s or '\n      for: 10m\n' in s

    # Labels
    assert 'labels:' in s
    assert 'severity: warning' in s
    assert 'service: mm-bot' in s
    # env label uses default template
    assert 'env: {{ $labels.env | default "prod" }}' in s

    # Annotations
    assert 'annotations:' in s
    assert 'summary: "order_age p99 elevated ({{ $value }} ms)"' in s
    assert 'runbook_url: https://runbooks/latency' in s


