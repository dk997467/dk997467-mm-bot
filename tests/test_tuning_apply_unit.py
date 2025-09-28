import json
from tools.tuning.apply_from_sweep import _simulate


def test_overlay_and_report_structure(tmp_path, monkeypatch):
    # Build fake sweep
    sweep = {
        'results': [{'metrics': {'net_bps': 3.0, 'order_age_p95_ms': 320.0, 'fill_rate': 0.7, 'replace_rate_per_min': 300.0}}],
        'top3_by_net_bps_safe': [
            {'params': {'max_delta_ratio': 0.12, 'impact_cap_ratio': 0.08, 'min_interval_ms': 80.0, 'tail_age_ms': 700.0}},
            {'params': {'max_delta_ratio': 0.10, 'impact_cap_ratio': 0.06, 'min_interval_ms': 100.0, 'tail_age_ms': 600.0}},
        ],
    }
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'tools' / 'tuning').mkdir(parents=True)
    (tmp_path / 'artifacts' / 'PARAM_SWEEP.json').write_text(json.dumps(sweep, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + "\n", encoding='ascii')

    import subprocess, sys
    r = subprocess.run([sys.executable, '-m', 'tools.tuning.apply_from_sweep'], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / 'artifacts' / 'TUNING_REPORT.json').read_text(encoding='ascii'))
    assert 'candidates' in rep and len(rep['candidates']) >= 1
    # YAML exists
    assert (tmp_path / 'tools' / 'tuning' / 'overlay_profile.yaml').exists()


