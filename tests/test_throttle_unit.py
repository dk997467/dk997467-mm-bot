from src.exchange.throttle import ReplaceThrottle, TailBatchCanceller


def test_allow_and_concurrency():
    t = ReplaceThrottle(max_concurrent=2, min_interval_ms=0)
    now = 1000
    assert t.allow("BTC", now)
    assert t.allow("BTC", now)
    assert not t.allow("BTC", now)


def test_min_interval():
    t = ReplaceThrottle(max_concurrent=2, min_interval_ms=60)
    now = 1000
    assert t.allow("BTC", now)
    # within 60ms denied
    assert not t.allow("BTC", now + 30)
    # settle one inflight to not hit concurrency
    t.settle("BTC")
    assert t.allow("BTC", now + 60)


def test_settle_decrements():
    t = ReplaceThrottle(max_concurrent=2, min_interval_ms=0)
    now = 1000
    assert t.allow("BTC", now)
    assert t.allow("BTC", now)
    t.settle("BTC")
    # after settle another allow should pass (interval 0)
    assert t.allow("BTC", now)


def test_tail_batch_select():
    c = TailBatchCanceller(tail_age_ms=100, max_batch=2)
    orders = {
        "A": (0, "BTC"),
        "B": (50, "BTC"),
        "C": (10, "ETH"),
        "D": (5, "ETH"),
    }
    # now_ms=150 -> ages: A=150,B=100,C=140,D=145 => select oldest two deterministically
    sel = c.select(orders, 150)
    assert sel == [("A", "BTC"), ("D", "ETH")]


