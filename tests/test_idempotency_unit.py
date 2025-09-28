from src.exchange.idempotency import idem_key_place, idem_key_replace, idem_key_cancel, IdemFilter


class FakeClock:
    def __init__(self):
        self._t = 0
    def time_ms(self):
        return self._t
    def tick(self, d):
        self._t += int(d)


def test_place_replace_cancel_idem():
    clk = FakeClock()
    f = IdemFilter(ttl_ms=5000, clock=clk)
    k1 = idem_key_place("BTCUSDT", "buy", 100.0, 1.0, "c1")
    assert not f.seen(k1, clk.time_ms())
    f.touch(k1, clk.time_ms())
    assert f.seen(k1, clk.time_ms())
    # replace
    k2 = idem_key_replace("c1", 101.0, 1.0)
    assert not f.seen(k2, clk.time_ms())
    f.touch(k2, clk.time_ms())
    assert f.seen(k2, clk.time_ms())
    # cancel
    k3 = idem_key_cancel("c1")
    assert not f.seen(k3, clk.time_ms())
    f.touch(k3, clk.time_ms())
    assert f.seen(k3, clk.time_ms())


def test_ttl_expiry():
    clk = FakeClock()
    f = IdemFilter(ttl_ms=1000, clock=clk)
    k = idem_key_place("ETHUSDT", "sell", 200.0, 2.0, "c2")
    f.touch(k, clk.time_ms())
    assert f.seen(k, clk.time_ms())
    clk.tick(1001)
    assert not f.seen(k, clk.time_ms())

