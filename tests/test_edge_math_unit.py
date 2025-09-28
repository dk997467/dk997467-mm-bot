from tools.edge_audit import _finite, _index_quotes, _agg_symbols


def test_edge_math_single_symbol():
    trades = [
        {"symbol":"BTCUSDT","ts_ms":1000,"side":"B","price":100.0,"qty":1.0,"mid_before":100.0,"mid_after_1s":100.2,"fee_bps":0.1},
        {"symbol":"BTCUSDT","ts_ms":2000,"side":"S","price":99.8,"qty":2.0,"mid_before":100.0,"mid_after_1s":99.7,"fee_bps":0.2},
        {"symbol":"BTCUSDT","ts_ms":3000,"side":"B","price":100.1,"qty":1.5,"mid_before":100.0,"mid_after_1s":100.0},
    ]
    quotes = [
        {"symbol":"BTCUSDT","ts_ms":1000,"best_bid":99.9,"best_ask":100.1},
        {"symbol":"BTCUSDT","ts_ms":2000,"best_bid":99.8,"best_ask":100.2},
        {"symbol":"BTCUSDT","ts_ms":3000,"best_bid":100.0,"best_ask":100.2},
    ]

    qidx = _index_quotes(quotes)
    sym = _agg_symbols(trades, qidx)
    m = sym['BTCUSDT']

    # Manually compute per-trade components and average
    # gross bps
    g1 = (100.0 - 100.0)/100.0*1e4
    g2 = -1*(99.8 - 100.0)/100.0*1e4
    g3 = (100.1 - 100.0)/100.0*1e4
    gross = (g1+g2+g3)/3.0

    # fees
    f1, f2, f3 = 0.1, 0.2, 0.0
    fees = (f1+f2+f3)/3.0

    # adverse
    a1 = (100.2 - 100.0)/100.0*1e4
    a2 = -1*(99.7 - 100.0)/100.0*1e4
    a3 = (100.0 - 100.0)/100.0*1e4
    adverse = (a1+a2+a3)/3.0

    # slippage
    s1 = (100.0 - 100.1)/100.1*1e4
    s2 = -1*(99.8 - 99.8)/99.8*1e4
    s3 = (100.1 - 100.2)/100.2*1e4
    slippage = (s1+s2+s3)/3.0

    # inventory proxy
    notional = [100.0*1.0, 99.8*2.0, 100.1*1.5]
    inv = [1.0, 2.0, 1.5]
    inv_bps = (sum(inv)/3.0) / (sum(notional)/3.0)

    assert abs(m['gross_bps'] - gross) <= 1e-12
    assert abs(m['fees_eff_bps'] - fees) <= 1e-12
    assert abs(m['adverse_bps'] - adverse) <= 1e-12
    assert abs(m['slippage_bps'] - slippage) <= 1e-12
    assert abs(m['inventory_bps'] - inv_bps) <= 1e-12
    assert abs(m['net_bps'] - (gross - fees - adverse - slippage - inv_bps)) <= 1e-12
    assert m['fills'] == 3.0
    assert m['turnover_usd'] > 0.0


