from src.sim.fill_models import fill_conservative, fill_queue_aware


def test_conservative_bid_ask_fill_and_fees():
    # Buy at ask -> fill
    order = {"side": "buy", "price": 101.0, "size": 1.0}
    book = {"bid": 100.0, "ask": 101.0}
    filled, fees_bps = fill_conservative(order, book)
    assert filled == 1.0
    assert fees_bps == 5.0
    # Sell at bid -> fill
    order = {"side": "sell", "price": 100.0, "size": 2.0}
    book = {"bid": 100.0, "ask": 101.0}
    filled, fees_bps = fill_conservative(order, book)
    assert filled == 2.0
    assert fees_bps == 5.0
    # Outside -> no fill
    order = {"side": "buy", "price": 100.5, "size": 1.0}
    filled, fees_bps = fill_conservative(order, book)
    assert filled == 0.0
    assert fees_bps == 0.0


def test_queue_aware_partial_and_penalty():
    order = {"side": "buy", "price": 101.0, "size": 2.0}
    book = {"bid": 100.0, "ask": 101.0}
    filled, qn, fees_bps = fill_queue_aware(order, book, qpos=0.75, params={"queue_penalty_bps": 0.8})
    # frac = 1 - 0.75 = 0.25 -> partial
    assert abs(filled - 0.5) < 1e-9
    assert qn == 0.0
    assert abs(fees_bps - (5.0 + 0.8)) < 1e-9


