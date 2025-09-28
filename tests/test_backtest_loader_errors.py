import os
import math
import json
from pathlib import Path


def _write(p: Path, lines):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='ascii', newline='\n') as f:
        for ln in lines:
            f.write(ln + "\n")


def test_loader_errors_and_sanitize():
    # Use repo fixture with bad lines
    from tools.backtest.loader import iter_ticks
    p = Path(__file__).resolve().parent / "fixtures" / "backtest_ticks_badlines.jsonl"
    it = iter_ticks(str(p))
    # First ok
    t1 = next(it)
    assert t1["ts_ms"] == 1
    # Second line: NaN/Inf sanitized to 0.0
    t2 = next(it)
    assert t2["bid"] == 0.0 and t2["ask"] == 0.0
    # Third line: broken json -> error
    try:
        _ = next(it)
        assert False, "expected loader error"
    except Exception as e:
        msg = str(e).strip()
        assert "\n" not in msg
        assert msg.startswith("E_BT_LOADER:"), msg


