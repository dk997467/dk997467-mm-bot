#!/usr/bin/env python3
"""Unit tests for tools.debug.repro_minimizer pure functions."""
import pytest
from pathlib import Path
from tools.debug.repro_minimizer import minimize, _write_jsonl_atomic


class TestMinimize:
    """Tests for minimize function."""
    
    def test_empty_input(self):
        """Test with empty input."""
        lines, steps = minimize("")
        assert lines == []
        assert steps == 0
    
    def test_single_guard_line(self):
        """Test with single guard line."""
        text = '{"type":"guard","reason":"DRIFT"}'
        lines, steps = minimize(text)
        
        assert len(lines) == 1
        assert '"type":"guard"' in lines[0]
        assert steps == 0  # No lines removed if we keep all
    
    def test_preserve_guard_lines(self):
        """Test that guard lines are preserved."""
        text = '''{"type":"quote"}
{"type":"trade"}
{"type":"guard","reason":"DRIFT"}
{"type":"quote"}'''
        lines, steps = minimize(text)
        
        # Should keep: first line, line before guard, guard
        assert any('"type":"guard"' in line for line in lines)
        assert steps > 0
    
    def test_first_line_always_kept(self):
        """Test that first line is always kept."""
        text = '''{"type":"quote","symbol":"BTCUSDT"}
{"type":"trade"}
{"type":"guard","reason":"DRIFT"}'''
        lines, steps = minimize(text)
        
        # First line should be in output
        assert '"symbol":"BTCUSDT"' in lines[0] or any('"symbol":"BTCUSDT"' in l for l in lines)
    
    def test_context_before_guard(self):
        """Test that line before guard is kept for context."""
        text = '''{"type":"quote"}
{"type":"trade"}
{"type":"context_line"}
{"type":"guard","reason":"DRIFT"}'''
        lines, steps = minimize(text)
        
        # Should have context line before guard
        guard_idx = next(i for i, l in enumerate(lines) if '"type":"guard"' in l)
        if guard_idx > 0:
            assert '"type":"context_line"' in lines[guard_idx - 1] or '"type":"trade"' in lines[guard_idx - 1]
    
    def test_multiple_guards(self):
        """Test with multiple guard lines."""
        text = '''{"type":"quote"}
{"type":"trade"}
{"type":"guard","reason":"DRIFT"}
{"type":"quote"}
{"type":"guard","reason":"REG"}'''
        lines, steps = minimize(text)
        
        # Both guards should be kept
        guard_count = sum(1 for line in lines if '"type":"guard"' in line)
        assert guard_count == 2
    
    def test_guard_with_spaces(self):
        """Test guard detection with spaces in JSON."""
        text = '''{"type": "quote"}
{"type": "guard", "reason": "DRIFT"}'''
        lines, steps = minimize(text)
        
        # Should detect guard even with spaces
        assert any('"type": "guard"' in line for line in lines)
    
    def test_steps_calculation(self):
        """Test that steps_removed is correct."""
        text = '''{"type":"1"}
{"type":"2"}
{"type":"3"}
{"type":"4"}
{"type":"guard"}'''
        lines, steps = minimize(text)
        
        original_lines = text.splitlines()
        assert steps == len(original_lines) - len(lines)
    
    def test_load_from_file(self, tmp_path):
        """Test loading from file path."""
        test_file = tmp_path / "test_input.jsonl"
        test_content = '{"type":"guard","reason":"TEST"}\n'
        test_file.write_text(test_content, encoding='utf-8')
        
        lines, steps = minimize(str(test_file))
        
        assert len(lines) > 0
        assert '"type":"guard"' in lines[0]
    
    def test_no_guards(self):
        """Test with no guard lines."""
        text = '''{"type":"quote"}
{"type":"trade"}
{"type":"fill"}'''
        lines, steps = minimize(text)
        
        # Should keep at least first line
        assert len(lines) >= 1
        # Should have removed some lines
        assert steps > 0


class TestWriteJsonlAtomic:
    """Tests for _write_jsonl_atomic function."""
    
    def test_write_empty_file(self, tmp_path):
        """Test writing empty file."""
        out_file = tmp_path / "output.jsonl"
        _write_jsonl_atomic(str(out_file), [])
        
        assert out_file.exists()
        content = out_file.read_text(encoding='ascii')
        assert content == ""
    
    def test_write_single_line(self, tmp_path):
        """Test writing single line."""
        out_file = tmp_path / "output.jsonl"
        lines = ['{"type":"guard"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        assert out_file.exists()
        content = out_file.read_text(encoding='ascii')
        assert content == '{"type":"guard"}\n'
    
    def test_write_multiple_lines(self, tmp_path):
        """Test writing multiple lines."""
        out_file = tmp_path / "output.jsonl"
        lines = ['{"type":"a"}', '{"type":"b"}', '{"type":"c"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        content = out_file.read_text(encoding='ascii')
        assert content == '{"type":"a"}\n{"type":"b"}\n{"type":"c"}\n'
    
    def test_atomic_write(self, tmp_path):
        """Test that write is atomic (uses temp file)."""
        out_file = tmp_path / "output.jsonl"
        lines = ['{"type":"test"}']
        
        # Should not leave .tmp file after successful write
        _write_jsonl_atomic(str(out_file), lines)
        
        assert out_file.exists()
        tmp_file = out_file.with_suffix(out_file.suffix + ".tmp")
        assert not tmp_file.exists()
    
    def test_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created."""
        out_file = tmp_path / "subdir" / "nested" / "output.jsonl"
        lines = ['{"type":"test"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        assert out_file.exists()
        assert out_file.parent.exists()
    
    def test_trailing_newline(self, tmp_path):
        """Test that file ends with newline."""
        out_file = tmp_path / "output.jsonl"
        lines = ['{"type":"guard"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        content = out_file.read_text(encoding='ascii')
        assert content.endswith('\n')
    
    def test_no_crlf_on_windows(self, tmp_path):
        """Test that newline is LF, not CRLF (even on Windows)."""
        out_file = tmp_path / "output.jsonl"
        lines = ['{"type":"a"}', '{"type":"b"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        # Read in binary to check actual bytes
        raw_content = out_file.read_bytes()
        
        # Should have LF (\n = 0x0A), not CRLF (\r\n = 0x0D 0x0A)
        assert b'\r\n' not in raw_content
        assert b'\n' in raw_content
    
    def test_overwrite_existing_file(self, tmp_path):
        """Test overwriting existing file."""
        out_file = tmp_path / "output.jsonl"
        out_file.write_text("old content", encoding='ascii')
        
        lines = ['{"type":"new"}']
        _write_jsonl_atomic(str(out_file), lines)
        
        content = out_file.read_text(encoding='ascii')
        assert content == '{"type":"new"}\n'
        assert "old content" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

