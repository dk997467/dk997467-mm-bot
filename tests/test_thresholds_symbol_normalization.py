from src.deploy.thresholds import THROTTLE_GLOBAL, THROTTLE_PER_SYMBOL, get_throttle_thresholds


def test_thresholds_symbol_normalization():
    THROTTLE_GLOBAL.clear()
    THROTTLE_GLOBAL.update({"max_throttle_backoff_ms": 2000, "max_throttle_events_in_window_total": 100})
    THROTTLE_PER_SYMBOL.clear()
    THROTTLE_PER_SYMBOL.update({"btcusdt": {"max_throttle_backoff_ms": 123, "max_throttle_events_in_window_total": 7}})

    a = get_throttle_thresholds("BTCUSDT")
    b = get_throttle_thresholds("btcusdt")

    assert a == b
    assert a["max_throttle_backoff_ms"] == 123
    assert a["max_throttle_events_in_window_total"] == 7

