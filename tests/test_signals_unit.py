from src.signals.imbalance import ob_imbalance
from src.signals.microprice import microprice, micro_tilt
from src.signals.sigma_regime import sigma_band


def test_ob_imbalance_symmetry_and_clamp():
    assert ob_imbalance(10, 10) == 0.0
    assert ob_imbalance(20, 10) > 0
    assert ob_imbalance(10, 20) < 0
    assert ob_imbalance(0, 0) == 0.0
    assert ob_imbalance(float("inf"), 1.0) == 0.0
    assert ob_imbalance(float("nan"), 1.0) == 0.0
    assert ob_imbalance(1e9, 0.0) <= 1.0
    assert ob_imbalance(0.0, 1e9) >= -1.0


def test_microprice_and_tilt():
    b, a = 100.0, 100.2
    bq, aq = 2.0, 2.0
    mp = microprice(b, a, bq, aq)
    assert abs(mp - (b + a) / 2.0) < 1e-12
    # if bq>aq, microprice leans toward bid price -> mp > mid
    mp2 = microprice(b, a, 3.0, 1.0)
    assert mp2 > (b + a) / 2.0
    t = micro_tilt(b, a, 3.0, 1.0)
    assert t < 0
    # equal qty => zero tilt
    assert abs(micro_tilt(b, a, 2.0, 2.0)) < 1e-12


def test_sigma_band_boundaries():
    bands = [(0.0, 0.8, "low"), (0.8, 1.5, "mid"), (1.5, 9.99, "high")]
    assert sigma_band(0.0, bands) == "low"
    assert sigma_band(0.79, bands) == "low"
    assert sigma_band(0.8, bands) == "mid"
    assert sigma_band(1.49, bands) == "mid"
    assert sigma_band(1.5, bands) == "high"


