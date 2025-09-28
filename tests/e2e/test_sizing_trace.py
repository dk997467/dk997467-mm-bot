from pathlib import Path
from types import SimpleNamespace

from src.portfolio.allocator import PortfolioAllocator


def _std(vals):
    n = len(vals)
    if n == 0:
        return 0.0
    mean = sum(vals) / n
    var = sum((v - mean) * (v - mean) for v in vals) / n
    return var ** 0.5


def test_sizing_trace_case1(tmp_path):
    # load fixture
    fx = Path('tests/fixtures/sizing_trace_case1.jsonl')
    lines = fx.read_text(encoding='ascii').splitlines()
    ctx = SimpleNamespace()
    cfg = SimpleNamespace(
        portfolio=SimpleNamespace(
            min_weight=0.0,
            max_weight=1.0,
            ema_alpha=1.0,
            budget_usd=1000.0,
            levels_per_side_min=1,
            levels_per_side_max=3,
        ),
        allocator=SimpleNamespace(smoothing=SimpleNamespace(
            max_delta_ratio=0.15,
            max_delta_abs_base_units=0.0,
            backoff_steps=[1.0, 0.7, 0.5],
            bias_cap=0.10,
            fee_bias_cap=0.05,
        )),
        guards=SimpleNamespace(pos_skew=SimpleNamespace(per_symbol_abs_limit=0.0, per_color_abs_limit=0.0)),
    )
    ctx.cfg = cfg
    ctx.state = SimpleNamespace(positions_by_symbol={}, color_by_symbol={})
    alloc = PortfolioAllocator(ctx)
    deltas_raw = []
    deltas_cap = []
    snapshot_lines = []
    for ln in lines:
        import json
        j = json.loads(ln)
        symbol = j['symbol']
        current = float(j['current'])
        desired = float(j['desired'])
        breach = bool(j.get('breach', False))
        # seed prev
        alloc.prev_targets_usd[symbol] = current
        weights = {symbol: 1.0}
        # emulate breach effect by setting guards limits to provoke color breach
        if breach:
            ctx.cfg.guards.pos_skew.per_color_abs_limit = 0.1
            ctx.state.positions_by_symbol = {symbol: desired}
            ctx.state.color_by_symbol = {symbol: 'blue'}
        else:
            ctx.cfg.guards.pos_skew.per_color_abs_limit = 0.0
            ctx.state.positions_by_symbol = {symbol: 0.0}
            ctx.state.color_by_symbol = {symbol: 'blue'}
        out = alloc.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=desired)
        nxt = out[symbol].target_usd
        delta_raw = desired - current
        delta_cap = nxt - current
        deltas_raw.append(abs(delta_raw))
        deltas_cap.append(abs(delta_cap))
        def fmt6(x: float) -> str:
            from src.portfolio.allocator import PortfolioAllocator
            return PortfolioAllocator._fmt6(x)
        cap = max(abs(current) * 0.15, 0.0)
        snapshot_lines.append(f"{j['ts']} {symbol} {fmt6(current)} {fmt6(desired)} {fmt6(delta_raw)} {fmt6(cap)} {alloc._backoff_level.get(symbol,0)} {fmt6(delta_cap)} {fmt6(nxt)}")
    # compare with golden
    golden = Path('tests/golden/sizing_trace_case1.out').read_text(encoding='ascii')
    got = "\n".join(snapshot_lines) + "\n"
    assert got == golden
    # format regex check for numeric fields
    import re
    r = re.compile(r"^-?\d+\.\d{6}$")
    for line in got.strip().splitlines():
        parts = line.split()
        # ts, symbol, cur, des, d_raw, cap, lvl, d_cap, nxt
        assert r.match(parts[2])
        assert r.match(parts[3])
        assert r.match(parts[4])
        assert r.match(parts[5])
        assert parts[6].isdigit() or (parts[6].startswith('-') and parts[6][1:].isdigit())
        assert r.match(parts[7])
        assert r.match(parts[8])
    # smoothing criterion
    assert _std(deltas_cap) < _std(deltas_raw)


