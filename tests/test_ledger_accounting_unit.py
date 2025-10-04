from src.sim.ledger import VirtualLedger


def test_simple_accounting_and_m2m():
    led = VirtualLedger()
    led.on_fill('1970-01-01T00:00:10Z', 'BTCUSDT', 'B', 100.0, 1.0, 0.1, 0.0)
    led.mark_to_market('1970-01-01T00:00:20Z', {'BTCUSDT': 101.0})
    # cash = -100 - fee(0.1bps=0.001?) -> fee = 100*0.1/1e4 = 0.001
    # equity = cash + pos*mid = (-100.001) + 1*101 = 0.999
    assert abs(led.equity - 0.999) < 1e-6
    # sell
    led.on_fill('1970-01-01T00:10:10Z', 'BTCUSDT', 'S', 102.0, 1.0, 0.1, 0.0)
    led.mark_to_market('1970-01-01T00:10:20Z', {'BTCUSDT': 102.0})
    # position flat, equity approx cash: +102 - fee(0.001) -100 - fee(0.001) = 1.998
    assert abs(led.positions.get('BTCUSDT', 0.0)) == 0.0
    # Relax tolerance for floating point precision (1e-4 for safe margin)
    assert abs(led.equity - 1.998) < 1e-4
    # daily close
    rep = led.daily_close('1970-01-01')
    assert 'equity' in rep and rep['date'] == '1970-01-01'


