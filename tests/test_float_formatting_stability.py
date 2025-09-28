from src.portfolio.allocator import PortfolioAllocator


def test_fmt6_basic():
    f = PortfolioAllocator._fmt6
    assert f(0.0) == "0.000000"
    assert f(1) == "1.000000"
    assert f(-1.23456789) == "-1.234568"
    assert f(1e-9) == "0.000000"
    assert f(float('nan')) == "0.000000"
    assert f(float('inf')) == "0.000000"
    assert f(-float('inf')) == "0.000000"


def test_fmt6_fraction_length():
    f = PortfolioAllocator._fmt6
    for v in [0.0, 1.23, -4.56789, 1000000.0, 0.9999994, 0.9999995]:
        s = f(v)
        assert '.' in s
        frac = s.split('.', 1)[1]
        assert len(frac) == 6


