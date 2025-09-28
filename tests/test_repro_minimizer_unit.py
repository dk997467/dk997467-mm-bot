from tools.debug.repro_minimizer import minimize
from tools.debug.repro_runner import run_case


def test_minimize_preserves_trigger(tmp_path):
    src = (
        '{"ts_ms":0,"type":"quote","symbol":"BTCUSDT"}\n'
        '{"ts_ms":1000,"type":"trade","symbol":"BTCUSDT"}\n'
        '{"ts_ms":2000,"type":"guard","reason":"DRIFT_EDGE"}\n'
        '{"ts_ms":3000,"type":"trade","symbol":"ETHUSDT"}\n'
        '{"ts_ms":4000,"type":"cancel","symbol":"ETHUSDT"}\n'
    )
    path = tmp_path / 'case.jsonl'
    path.write_text(src, encoding='ascii')
    minimal, steps = minimize(str(path))
    # minimal should still fail with DRIFT
    tmp = tmp_path / 'min.jsonl'
    from tools.debug.repro_minimizer import _write_jsonl_atomic
    _write_jsonl_atomic(str(tmp), minimal)
    r = run_case(str(tmp))
    assert r['fail'] and r['reason'] == 'DRIFT'
    # size reduced
    assert len(minimal) <= 3


