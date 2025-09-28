from pathlib import Path
import os
import json
from types import SimpleNamespace

from src.common.artifacts import write_json_atomic
from src.metrics.exporter import Metrics


def test_metrics_json_determinism(tmp_path):
    p = tmp_path / 'artifacts' / 'metrics.json'
    payload = {"b": 2, "a": {"y": 2, "x": 1}}
    # run 3 times
    for _ in range(3):
        write_json_atomic(str(p), payload)
    b = p.read_bytes()
    # ensure newline terminator
    assert b.endswith(b"\n")
    # ensure ascii/sorted/separators
    txt = b.decode('ascii')
    assert txt == json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    # keys order check
    d = json.loads(txt)
    assert list(d.keys()) == sorted(d.keys())


def test_unified_artifacts_determinism(tmp_path):
    """Test that unified artifacts export is byte-for-byte identical."""
    ctx = SimpleNamespace()
    ctx.cfg = SimpleNamespace()
    
    metrics = Metrics(ctx)
    output_path = tmp_path / 'unified_metrics.json'
    
    # Export 3 times with same input
    contents = []
    for _ in range(3):
        metrics.export_unified_artifacts(str(output_path))
        contents.append(output_path.read_bytes())
    
    # All should be identical
    assert contents[0] == contents[1] == contents[2]
    
    # Check format
    assert contents[0].endswith(b'\n')
    txt = contents[0].decode('ascii')
    data = json.loads(txt)
    assert list(data.keys()) == sorted(data.keys())


