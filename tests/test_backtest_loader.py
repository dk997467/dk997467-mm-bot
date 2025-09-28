import io
import os
import json


def write_tmp(path: str, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        for ln in lines:
            f.write(ln + "\n")


def test_iter_ticks_ok(tmp_path):
    p = tmp_path / "ticks.jsonl"
    lines = [
        json.dumps({"ts_ms": 1, "bid": 100.0, "ask": 101.0, "bid_qty": 1.0, "ask_qty": 1.2, "trades": 0}),
        json.dumps({"ts_ms": 2, "bid": 100.1, "ask": 101.2, "bid_qty": 2.0, "ask_qty": 1.0, "trades": 1}),
    ]
    write_tmp(str(p), lines)

    from tools.backtest.loader import iter_ticks

    out = list(iter_ticks(str(p)))
    assert len(out) == 2
    assert out[0]["ts_ms"] == 1
    assert out[1]["ask"] == 101.2


def test_iter_ticks_bad_lines(tmp_path):
    p = tmp_path / "bad.jsonl"
    lines = [
        "{not json}",
        json.dumps({"ts_ms": 1}),  # missing fields
    ]
    write_tmp(str(p), lines)

    from tools.backtest.loader import iter_ticks

    try:
        list(iter_ticks(str(p)))
        assert False, "expected exception"
    except Exception as e:
        msg = str(e).strip().splitlines()[0]
        assert msg.startswith("E_BT_LOADER:"), msg


