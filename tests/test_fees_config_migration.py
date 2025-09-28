from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _write_yaml(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _run_dump(tmp_path: Path, yaml_text: str):
    cfg = tmp_path / "config.yaml"
    _write_yaml(cfg, yaml_text)
    code = (
        "import json;"
        "from src.common.config import ConfigLoader;"
        f"cl=ConfigLoader(config_path=r'{cfg.as_posix()}');"
        "app=cl.load();"
        "print(json.dumps(app.to_sanitized(), ensure_ascii=True, sort_keys=True, separators=(',',':')))"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return r


def test_fees_k_vola_spread_migrates_and_filters(tmp_path):
    yaml_text = """
strategy:
  min_spread_bps: 2
fees:
  k_vola_spread: 0.77
  unknown_key: 123
"""
    r = _run_dump(tmp_path, yaml_text)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert abs(float(data["strategy"]["k_vola_spread"]) - 0.77) < 1e-9
    assert isinstance(data.get("fees"), dict)
    # Only allowed keys remain (bybit may be present from defaults)
    assert set(data["fees"].keys()) <= {"bybit"}


def test_does_not_override_strategy_value(tmp_path):
    yaml_text = """
strategy:
  k_vola_spread: 0.9
fees:
  k_vola_spread: 0.5
"""
    r = _run_dump(tmp_path, yaml_text)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert abs(float(data["strategy"]["k_vola_spread"]) - 0.9) < 1e-9


