import json
import subprocess
import sys
from pathlib import Path


def run_bench(profile: str, out_path: Path):
    root = Path(__file__).resolve().parents[2]
    subprocess.check_call([
        sys.executable, '-m', 'tools.perf.bench_queue',
        '--scenario', str(root / 'tests' / 'fixtures' / 'perf_scenario_case1.json'),
        '--profile', profile,
        '--out', str(out_path),
    ])


def test_perf_latency_distribution(tmp_path):
    out_b = tmp_path / 'PERF_baseline.json'
    out_t = tmp_path / 'PERF_tuned.json'
    run_bench('baseline', out_b)
    run_bench('tuned', out_t)

    b1 = out_b.read_bytes()
    b2 = (tmp_path / 'PERF_baseline_2.json'); run_bench('baseline', b2)
    assert b1 == b2.read_bytes()
    assert b1.endswith(b'\n')

    t1 = out_t.read_bytes()
    t2 = (tmp_path / 'PERF_tuned_2.json'); run_bench('tuned', t2)
    assert t1 == t2.read_bytes()
    assert t1.endswith(b'\n')

    root = Path(__file__).resolve().parents[2]
    g = root / 'tests' / 'golden'
    assert b1 == (g / 'perf_latency_baseline.json').read_bytes()
    assert t1 == (g / 'perf_latency_tuned.json').read_bytes()

    base = json.loads(b1.decode('ascii'))
    tuned = json.loads(t1.decode('ascii'))
    assert tuned['order_age_p95_ms'] <= base['order_age_p95_ms']
    assert tuned['order_age_p99_ms'] <= base['order_age_p99_ms']
    assert tuned['fill_rate'] >= base['fill_rate'] * 0.80
    # Prefer tuned replace rate <= baseline
    assert tuned['replace_rate_per_min'] <= base['replace_rate_per_min']


