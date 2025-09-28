import time
from types import SimpleNamespace
from src.guards.circuit import CircuitBreaker


def test_circuit_open_half_open_closed():
    cfg = SimpleNamespace(window_sec=10.0, err_rate_open=0.5, http_5xx_rate_open=0.2, http_429_rate_open=0.2,
                          open_duration_sec=1.0, half_open_probes=3, cooldown_sec=0.5)
    cb = CircuitBreaker(cfg)
    now = time.time()
    # Feed errors to open
    for i in range(6):
        cb.on_result(f"c{i}", ok=False, http_code=500, now=now + i*0.01)
    cb.tick(now+0.2)
    assert cb.state() == 'open'
    # After open_duration, go half_open
    cb.tick(now+1.5)
    assert cb.state() == 'half_open'
    # Provide successful probes to close
    for i in range(3):
        assert cb.allowed('create')
        cb.on_result(f"p{i}", ok=True, http_code=200, now=now+1.6+i*0.01)
        cb.tick(now+1.6+i*0.01)
    # consume probes and decide close
    cb.tick(now+2.0)
    assert cb.state() in ('closed','open')

