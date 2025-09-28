from src.deploy import thresholds as th


def test_thresholds_strict_mode_behavior():
    th.THROTTLE_GLOBAL.clear()
    th.THROTTLE_GLOBAL.update({"max_throttle_backoff_ms": 1000, "max_throttle_events_in_window_total": 100})
    th.THROTTLE_PER_SYMBOL.clear()
    th.THROTTLE_PER_SYMBOL.update({"BAD": {"max_throttle_backoff_ms": -1}})

    th.STRICT_THRESHOLDS = True
    raised = False
    try:
        th.get_throttle_thresholds("BAD")
    except ValueError:
        raised = True
    finally:
        th.STRICT_THRESHOLDS = False
    assert raised

    # When not strict -> fallback to global without raising
    th.THROTTLE_PER_SYMBOL.clear()
    th.THROTTLE_PER_SYMBOL.update({"BAD": {"max_throttle_backoff_ms": -1}})
    th.STRICT_THRESHOLDS = False
    res = th.get_throttle_thresholds("BAD")
    assert res["max_throttle_backoff_ms"] == 1000

