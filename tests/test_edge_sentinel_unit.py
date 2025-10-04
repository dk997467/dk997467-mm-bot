from tools.edge_sentinel.analyze import analyze


def test_analyze_bucket_and_ranking(tmp_path, test_paths):
    root = tmp_path
    trades = root / 'trades.jsonl'
    quotes = root / 'quotes.jsonl'
    # copy fixtures using universal fixture
    trades.write_text((test_paths.fixtures_dir / 'edge_sentinel' / 'trades.jsonl').read_text(encoding='ascii'), encoding='ascii')
    quotes.write_text((test_paths.fixtures_dir / 'edge_sentinel' / 'quotes.jsonl').read_text(encoding='ascii'), encoding='ascii')

    rep = analyze(str(trades), str(quotes), 15)
    assert 'summary' in rep and 'top' in rep and 'advice' in rep
    assert len(rep['top']['top_symbols_by_net_drop']) <= 5
    assert len(rep['advice']) >= 1


