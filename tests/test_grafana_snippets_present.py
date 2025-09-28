def test_readme_contains_l6_dashboards_snippets():
    import re
    with open('README.md', 'r', encoding='utf-8') as f:
        txt = f.read()
    assert '### L6 dashboards' in txt
    assert 'cost_fillrate_ewma{symbol}' in txt
    assert 'allocator_fillrate_attenuation{symbol}' in txt
    assert 'allocator_estimated_cost_bps{symbol}' in txt
    # panels names present
    assert 'Fill-rate & attenuation' in txt
    assert 'Estimated cost (bps)' in txt


