#!/usr/bin/env python3
"""
Test suite for lint_ascii_logs.py

Verifies:
1. Streaming read works correctly
2. Memory usage stays constant (no f.read())
3. Non-ASCII detection works
4. Line numbers are reported correctly
5. Large files are handled safely
"""

import sys
import tempfile
import os
from pathlib import Path


def create_test_file(content: str) -> Path:
    """Create temporary test file."""
    fd, path = tempfile.mkstemp(suffix='.py', prefix='test_ascii_lint_')
    with open(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return Path(path)


def test_basic_ascii():
    """Test 1: Basic ASCII content should pass."""
    content = '''
import os

def main():
    print("Hello World")
    print("This is ASCII only")
    return 0
'''
    test_file = create_test_file(content)
    
    # Import and test
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    test_file.unlink()
    
    assert len(violations) == 0, f"Expected 0 violations, got {len(violations)}"
    print("✅ Test 1 PASSED: Basic ASCII content")


def test_non_ascii_in_print():
    """Test 2: Non-ASCII in print() should be detected."""
    content = '''
import os

def main():
    print("Привет мир")  # Russian text
    print("Hello World")
    return 0
'''
    test_file = create_test_file(content)
    
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    test_file.unlink()
    
    assert len(violations) > 0, f"Expected violations, got none"
    assert any('non-ascii' in msg for _, msg in violations), "Expected 'non-ascii' in violation message"
    
    # Check line number is correct (should be line 4)
    line_no, msg = violations[0]
    assert line_no == 4, f"Expected line 4, got line {line_no}"
    
    print("✅ Test 2 PASSED: Non-ASCII detection with correct line number")


def test_large_file():
    """Test 3: Large file (1MB) should be handled without memory issues."""
    # Create 1MB file with 10,000 lines
    lines = []
    for i in range(10_000):
        lines.append(f'    x = {i}  # Line {i}\n')
    
    # Add one violation at line 5000
    lines[4999] = '    print("Ошибка")  # Non-ASCII\n'
    
    content = 'def test():\n' + ''.join(lines) + '    return 0\n'
    test_file = create_test_file(content)
    
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    test_file.unlink()
    
    # Should detect exactly 1 violation at line 5000
    assert len(violations) == 1, f"Expected 1 violation, got {len(violations)}"
    line_no, msg = violations[0]
    assert line_no == 5000, f"Expected line 5000, got line {line_no}"
    
    print("✅ Test 3 PASSED: Large file (1MB) handled correctly")


def test_extremely_long_line():
    """Test 4: Extremely long line (>10KB) should be skipped safely."""
    # Create line with 20KB of content
    long_line = 'x = "' + ('A' * 20_000) + '"\n'
    content = f'''
def test():
    print("Before")
{long_line}
    print("After")
'''
    test_file = create_test_file(content)
    
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    test_file.unlink()
    
    # Should report "line too long"
    assert len(violations) == 1, f"Expected 1 violation (line too long), got {len(violations)}"
    _, msg = violations[0]
    assert 'line too long' in msg, f"Expected 'line too long', got: {msg}"
    
    print("✅ Test 4 PASSED: Extremely long line handled safely")


def test_non_ascii_outside_print():
    """Test 5: Non-ASCII outside print() should be ignored."""
    content = '''
# Этот комментарий содержит русский текст
def функция():  # Non-ASCII function name
    x = "Строка"  # Non-ASCII string
    y = "ASCII string"
    return x + y
'''
    test_file = create_test_file(content)
    
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    test_file.unlink()
    
    # Should have 0 violations (non-ASCII is not in print())
    assert len(violations) == 0, f"Expected 0 violations, got {len(violations)}"
    
    print("✅ Test 5 PASSED: Non-ASCII outside print() ignored")


def test_memory_efficiency():
    """Test 6: Verify memory usage is O(1) per file."""
    # Create 10MB file (should not load into memory all at once)
    lines = []
    for i in range(100_000):
        lines.append(f'    # Comment line {i}\n')
    
    content = 'def test():\n' + ''.join(lines) + '    return 0\n'
    test_file = create_test_file(content)
    
    # Measure memory before
    import psutil
    process = psutil.Process(os.getpid())
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    
    sys.path.insert(0, str(Path(__file__).parent))
    from lint_ascii_logs import check_file_for_non_ascii
    
    violations = check_file_for_non_ascii(str(test_file))
    
    # Measure memory after
    mem_after = process.memory_info().rss / 1024 / 1024  # MB
    mem_increase = mem_after - mem_before
    
    test_file.unlink()
    
    # Memory increase should be minimal (<5MB for 10MB file)
    # Old version would load entire 10MB into memory
    assert mem_increase < 5, f"Memory increase too high: {mem_increase:.1f} MB (file was 10MB)"
    
    print(f"✅ Test 6 PASSED: Memory efficient (increase: {mem_increase:.1f} MB for 10MB file)")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing lint_ascii_logs.py (streaming read version)")
    print("=" * 60)
    print()
    
    try:
        test_basic_ascii()
        test_non_ascii_in_print()
        test_large_file()
        test_extremely_long_line()
        test_non_ascii_outside_print()
        
        # Test 6 requires psutil
        try:
            import psutil
            test_memory_efficiency()
        except ImportError:
            print("⚠️  Test 6 SKIPPED: psutil not installed (pip install psutil)")
        
        print()
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    sys.exit(main())

