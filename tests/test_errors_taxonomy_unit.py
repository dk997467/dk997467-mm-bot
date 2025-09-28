from src.common.errors import one_line


def test_one_line_normalizes():
    s = one_line('a\n b\t c', 'E_PROFILE_APPLY')
    assert s.startswith('E_PROFILE_APPLY: ')
    assert '\n' not in s
    assert '  ' not in s


