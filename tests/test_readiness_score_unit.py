from tools.release.readiness_score import _section_scores


def test_sections_and_total_stability():
    reports = [
        {'edge_net_bps': 2.8, 'order_age_p95_ms': 320.0, 'taker_share_pct': 12.0, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.7, 'order_age_p95_ms': 330.0, 'taker_share_pct': 12.5, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.6, 'order_age_p95_ms': 340.0, 'taker_share_pct': 13.0, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.9, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.0, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.5, 'order_age_p95_ms': 350.0, 'taker_share_pct': 13.5, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.4, 'order_age_p95_ms': 360.0, 'taker_share_pct': 14.0, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
        {'edge_net_bps': 2.3, 'order_age_p95_ms': 370.0, 'taker_share_pct': 14.5, 'reg_guard': {'reason': 'NONE'}, 'drift': {'reason': 'NONE'}, 'chaos_result': 'OK', 'bug_bash': 'OK'},
    ]
    sections, total = _section_scores(reports)
    assert 70.0 <= total <= 100.0
    assert set(sections.keys()) == {'edge', 'latency', 'taker', 'guards', 'chaos', 'tests'}


