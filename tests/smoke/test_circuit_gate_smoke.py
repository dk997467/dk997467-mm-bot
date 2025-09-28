import time
from src.guards.circuit_gate import CircuitGate, CircuitParams, STATE_TO_INT
import re


def test_ok_window():
    p = CircuitParams(max_err_rate=0.5, window_sec=60, min_closed_sec=10, half_open_probe=3)
    g = CircuitGate(p)
    # mostly successes
    for _ in range(20):
        st = g.record(False)
        assert st == 'OPEN'
    # a few errors but below threshold
    for _ in range(4):
        st = g.record(True)
        assert st in ('OPEN', 'TRIPPED')
        if st == 'TRIPPED':
            # if unexpectedly tripped, break to fail later
            break
    assert g.state() == 'OPEN'


def test_trip_on_errors():
    metrics = {"state": [], "transitions": [], "err_rate": []}
    def metrics_cb(name, labels):
        if name == 'circuit_state':
            metrics["state"].append(labels["value"])  # int
        elif name == 'transitions_total':
            metrics["transitions"].append((labels.get('from'), labels.get('to')))
        elif name == 'err_rate_window':
            metrics["err_rate"].append(labels["value"])  # float
    p = CircuitParams(max_err_rate=0.15, window_sec=30, min_closed_sec=2, half_open_probe=3)
    g = CircuitGate(p, metrics_cb=metrics_cb)
    # flood errors to cross threshold
    for _ in range(10):
        st = g.record(True)
    assert g.state() == 'TRIPPED'
    # while within min_closed_sec, remains TRIPPED even with successes
    st0 = time.monotonic()
    while time.monotonic() - st0 < 1.0:
        g.record(False)
        assert g.state() == 'TRIPPED'
    # transitions counter must include at least one OPEN->TRIPPED
    assert ('OPEN','TRIPPED') in metrics["transitions"]
    # state gauge must be valid enum
    assert metrics["state"] and metrics["state"][-1] in (0,1,2)


def test_reopen_after_min_closed():
    # Fake time function for deterministic advance
    t = [0.0]
    def fake_now():
        return t[0]
    p = CircuitParams(max_err_rate=0.15, window_sec=30, min_closed_sec=1, half_open_probe=2)
    g = CircuitGate(p, time_fn=fake_now, thread_safe=True)
    # trip
    for _ in range(10):
        g.record(True)
    assert g.state() == 'TRIPPED'
    # advance time instead of sleep
    t[0] += 1.1
    # next record should move to HALF_OPEN
    st = g.record(False)
    assert st == 'HALF_OPEN'
    # provide successful probes
    st = g.record(False)
    st = g.record(False)
    assert g.state() == 'OPEN'


def test_snapshot_and_state_helpers():
    p = CircuitParams(max_err_rate=1.0, window_sec=10, min_closed_sec=1, half_open_probe=1)
    g = CircuitGate(p)
    g.record(False)
    snap = g.snapshot()
    assert set(snap.keys()) == {"state","err_rate","window_len","last_transition_ts"}
    assert snap["state"] in ("OPEN","TRIPPED","HALF_OPEN")
    # name <-> int mapping
    assert g.from_str('open') in (0,1,2)
    assert STATE_TO_INT[g.state_name()] in (0,1,2)


def test_idempotent_transition():
    # Force trip, then repeat errors within TRIPPED should not duplicate transition log
    metrics = {"transitions": 0}
    def metrics_cb(name, labels):
        if name == 'transitions_total':
            metrics["transitions"] += 1
    p = CircuitParams(max_err_rate=0.0, window_sec=10, min_closed_sec=5, half_open_probe=1)
    g = CircuitGate(p, metrics_cb=metrics_cb)
    g.record(True)  # trip
    assert metrics["transitions"] >= 1
    before = metrics["transitions"]
    # Still TRIPPED: more errors shouldn't add transitions until state actually changes
    for _ in range(5):
        g.record(True)
    assert metrics["transitions"] == before


def test_log_order_is_fixed(capfd):
    p = CircuitParams(max_err_rate=0.0, window_sec=10, min_closed_sec=5, half_open_probe=1)
    g = CircuitGate(p)
    g.record(True)  # triggers OPEN->TRIPPED
    out = capfd.readouterr().out.strip().splitlines()
    # At least one transition log line
    assert any(l.startswith('event=circuit_transition') for l in out)
    last = [l for l in out if l.startswith('event=circuit_transition')][-1]
    pattern = r"^event=circuit_transition state_from=\S+ state_to=\S+ err_rate=\d+\.\d{6} window_len=\d+ now=\d+ reason=\S+$"
    assert re.match(pattern, last) is not None


def test_deque_has_maxlen():
    # Explicitly set events_maxlen=15 and avoid time-window pruning via large window_sec
    p = CircuitParams(max_err_rate=1.0, window_sec=1000, min_closed_sec=1, half_open_probe=1)
    t = [0.0]
    def fake_now():
        return t[0]
    g = CircuitGate(p, events_maxlen=15, events_per_sec_hint=3, time_fn=fake_now)
    # push 30 bins (advance 1 sec per event)
    for i in range(30):
        t[0] = float(i)
        g.record(False)
    snap = g.snapshot()
    assert snap['window_len'] == 15


def test_coalescing_in_same_second():
    # fixed time function returning constant ts_sec
    t = [1000.0]
    def fake_now():
        return t[0]
    p = CircuitParams(max_err_rate=1.0, window_sec=10, min_closed_sec=1, half_open_probe=1)
    metrics = {"coalesced": 0}
    def metrics_cb(name, labels):
        if name == 'flood_coalesced_total':
            metrics["coalesced"] += labels.get('add', 0)
    g = CircuitGate(p, time_fn=fake_now, metrics_cb=metrics_cb)
    for _ in range(100):
        g.on_error()
    snap = g.snapshot()
    # only one bin stored
    assert snap['window_len'] == 1
    # coalesced counter > 0
    assert metrics["coalesced"] > 0


def test_window_err_rate_with_bins():
    # two seconds with controlled ok/err counts
    t = [2000.0]
    def fake_now():
        return t[0]
    p = CircuitParams(max_err_rate=1.0, window_sec=10, min_closed_sec=1, half_open_probe=1)
    g = CircuitGate(p, time_fn=fake_now)
    # sec 2000: 3 ok, 1 err
    for _ in range(3):
        g.on_ok()
    g.on_error()
    # next second 2001: 1 ok, 3 err
    t[0] = 2001.0
    g.on_ok()
    for _ in range(3):
        g.on_error()
    # err_rate = (1+3)/( (3+1) + (1+3) ) = 4/8 = 0.5
    snap = g.snapshot()
    assert abs(snap['err_rate'] - 0.5) < 1e-9


def test_log_rate_limit(capfd):
    # limit logs per sec to 1
    p = CircuitParams(max_err_rate=0.0, window_sec=10, min_closed_sec=1, half_open_probe=1)
    g = CircuitGate(p)
    # first error triggers transition log
    g.on_error()
    # more errors in same second shouldn't produce more transition logs
    for _ in range(5):
        g.on_error()
    out = capfd.readouterr().out
    cnt = sum(1 for l in out.splitlines() if l.startswith('event=circuit_transition'))
    assert cnt <= 1


def test_no_regression_trip_logic():
    p = CircuitParams(max_err_rate=0.15, window_sec=30, min_closed_sec=2, half_open_probe=3)
    g = CircuitGate(p)
    # burst errors should trip as before
    for _ in range(20):
        g.on_error()
    assert g.state() == 'TRIPPED'


def test_state_enum_export():
    from src.guards.circuit_gate import STATE_OPEN, STATE_TRIPPED, STATE_HALF_OPEN, STATE_TO_NAME, NAME_TO_STATE
    assert STATE_TO_NAME[STATE_OPEN] == 'OPEN'
    assert STATE_TO_NAME[STATE_TRIPPED] == 'TRIPPED'
    assert STATE_TO_NAME[STATE_HALF_OPEN] == 'HALF_OPEN'
    assert NAME_TO_STATE['OPEN'] == STATE_OPEN
    assert NAME_TO_STATE['TRIPPED'] == STATE_TRIPPED
    assert NAME_TO_STATE['HALF_OPEN'] == STATE_HALF_OPEN


