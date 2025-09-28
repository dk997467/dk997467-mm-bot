import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.metrics.exporter import Metrics
from src.common.di import AppContext


def test_unified_payload_structure():
    """Test unified payload has correct structure and key order."""
    ctx = SimpleNamespace()
    ctx.cfg = SimpleNamespace()
    
    metrics = Metrics(ctx)
    payload = metrics.build_unified_artifacts_payload()
    
    # Check top-level keys are alphabetical
    keys = list(payload.keys())
    assert keys == sorted(keys), f"Keys not alphabetical: {keys}"
    
    # Check required sections
    assert "fees" in payload
    assert "intraday_caps" in payload
    assert "position_skew" in payload
    assert "runtime" in payload
    
    # Check runtime structure
    runtime = payload["runtime"]
    assert "utc" in runtime
    assert "version" in runtime
    assert "git_sha" in runtime
    assert "mode" in runtime
    assert "env" in runtime
    
    # Check UTC format
    utc_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
    assert re.match(utc_pattern, runtime["utc"]), f"Invalid UTC format: {runtime['utc']}"


def test_artifacts_file_format():
    """Test artifacts file has correct format and termination."""
    with TemporaryDirectory() as tmp_dir:
        ctx = SimpleNamespace()
        ctx.cfg = SimpleNamespace()
        
        metrics = Metrics(ctx)
        output_path = Path(tmp_dir) / "test_metrics.json"
        
        metrics.export_unified_artifacts(str(output_path))
        
        # Check file exists and ends with newline
        assert output_path.exists()
        content_bytes = output_path.read_bytes()
        assert content_bytes.endswith(b'\n'), "File should end with newline"
        
        # Check JSON is valid and keys are sorted
        content_text = content_bytes.decode('ascii')
        data = json.loads(content_text)
        
        # Verify keys are alphabetical at top level
        keys = list(data.keys())
        assert keys == sorted(keys)


def test_missing_sections_handling():
    """Test that missing sections are handled gracefully."""
    ctx = SimpleNamespace()
    ctx.cfg = SimpleNamespace()
    
    metrics = Metrics(ctx)
    payload = metrics.build_unified_artifacts_payload()
    
    # All sections should be present (even if empty)
    assert isinstance(payload.get("fees"), dict)
    assert isinstance(payload.get("intraday_caps"), dict)
    assert isinstance(payload.get("position_skew"), dict)
    assert isinstance(payload.get("runtime"), dict)
    
    # Runtime should never be empty
    assert len(payload["runtime"]) > 0
