from tests.e2e._utils import make_metrics_ctx


def test_fillrate_ewma_converges_and_clamped():
    m = make_metrics_ctx()
    m.reset_cost_fillrate_for_tests()
    # half-life from config defaults (>=10) — we just check monotone approach
    # feed 100 filled=True then 100 filled=False to move r toward 0
    for _ in range(50):
        m.record_fill_event('BTCUSDT', True)
    snap = m.get_cost_fillrate_snapshot_for_tests()
    r1 = float(snap['r'].get('BTCUSDT', 0.0))
    n1 = int(snap['samples'].get('BTCUSDT', 0))
    assert n1 >= 50 and 0.0 <= r1 <= 1.0
    for _ in range(80):
        m.record_fill_event('BTCUSDT', False)
    snap2 = m.get_cost_fillrate_snapshot_for_tests()
    r2 = float(snap2['r'].get('BTCUSDT', 0.0))
    n2 = int(snap2['samples'].get('BTCUSDT', 0))
    assert n2 >= n1
    assert 0.0 <= r2 <= 1.0
    assert r2 <= r1  # moved toward 0


