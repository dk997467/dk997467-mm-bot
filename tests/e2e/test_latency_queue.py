import json
from pathlib import Path

from src.exchange.throttle import ReplaceThrottle, TailBatchCanceller


def percentile(values, p):
    vs = sorted(values)
    if not vs:
        return 0.0
    k = (len(vs) - 1) * p
    f = int(k)
    c = min(f + 1, len(vs) - 1)
    if c == f:
        return float(vs[f])
    w = k - f
    return float(vs[f] * (1 - w) + vs[c] * w)


def _load_events(fp: str):
    events = []
    with open(fp, "r", encoding="ascii", newline="\n") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _simulate(events, use_latency_boost: bool):
    active = {}  # cl_id -> (created_ms, symbol)
    replace_attempts = 0
    replace_allowed = 0
    batch_cancels = 0
    places = 0
    settles = 0
    ages_sample = []

    throttle = ReplaceThrottle(max_concurrent=2, min_interval_ms=60) if use_latency_boost else None
    canceller = TailBatchCanceller(tail_age_ms=800, max_batch=10, jitter_ms=0) if use_latency_boost else None

    for ev in events:
        t = int(ev.get("ts_ms", 0))
        typ = ev.get("type")
        sym = ev.get("symbol")
        cid = ev.get("cl_id")

        if typ == "place":
            active[cid] = (t, sym)
            places += 1
        elif typ == "replace":
            replace_attempts += 1
            if use_latency_boost and throttle:
                if throttle.allow(sym, t):
                    replace_allowed += 1
                else:
                    pass
            else:
                replace_allowed += 1
        elif typ == "settle":
            settles += 1
            if use_latency_boost and throttle:
                throttle.settle(sym)
            # order considered settled; keep active map unchanged for age sampling which happens on tick
            # (we want deterministic sampling point only at tick)
        elif typ == "tick":
            if use_latency_boost and canceller:
                # cancel tails before measuring ages
                sel = canceller.select(active, t)
                for cl, _s in sel:
                    if cl in active:
                        del active[cl]
                batch_cancels += len(sel)
            # sample ages at tick
            for _cl, (ts0, _s) in active.items():
                ages_sample.append(t - ts0)

    p95 = percentile(ages_sample, 0.95)
    fill_rate = float(settles) / float(places or 1)
    return {
        "P95": p95,
        "FILL_RATE": fill_rate,
        "REPLACE_ATTEMPTS": replace_attempts,
        "REPLACE_ALLOWED": replace_allowed,
        "BATCH_CANCELS": batch_cancels,
    }


def _format_snapshot(stats_before, stats_after) -> str:
    lines = []
    lines.append(f"P95_BEFORE={stats_before['P95']:.2f}")
    lines.append(f"P95_AFTER={stats_after['P95']:.2f}")
    lines.append(f"FILL_RATE_BEFORE={stats_before['FILL_RATE']:.6f}")
    lines.append(f"FILL_RATE_AFTER={stats_after['FILL_RATE']:.6f}")
    lines.append(f"REPLACE_ATTEMPTS={int(stats_after['REPLACE_ATTEMPTS'])}")
    lines.append(f"REPLACE_ALLOWED={int(stats_after['REPLACE_ALLOWED'])}")
    lines.append(f"BATCH_CANCELS={int(stats_after['BATCH_CANCELS'])}")
    return "\n".join(lines) + "\n"


def test_latency_queue_case1(tmp_path):
    events = _load_events("tests/fixtures/latency_events_case1.jsonl")
    before = _simulate(events, use_latency_boost=False)
    after = _simulate(events, use_latency_boost=True)

    # Hard constraints
    assert after["P95"] <= 350.0
    assert after["P95"] <= before["P95"]
    assert after["FILL_RATE"] >= before["FILL_RATE"]
    assert after["REPLACE_ALLOWED"] < after["REPLACE_ATTEMPTS"]

    snap = _format_snapshot(before, after)
    gold = Path("tests/golden/latency_queue_case1.out").read_text(encoding="ascii")
    assert snap == gold


