"""
Tests for parameter tuner bounds and validation.

Updated to align with WalkForwardTuner API:
- random generation via _generate_random_params(param_space)
- grid generation via _generate_grid_params(param_space)
"""

import pytest

from src.strategy.tuner import WalkForwardTuner


# Parameter spaces for tests
PARAM_SPACE_RANDOM = {
    "k_vola_spread": {"min": 0.6, "max": 1.4},
    "skew_coeff": {"min": 0.1, "max": 0.6},
    "levels_per_side": {"type": "int", "min": 2, "max": 4},
    "level_spacing_coeff": {"min": 0.2, "max": 0.6},
    "min_time_in_book_ms": {"type": "int", "min": 300, "max": 800},
    "replace_threshold_bps": {"min": 0.0, "max": 6.0},
    "imbalance_cutoff": {"min": 0.55, "max": 0.75},
}

PARAM_SPACE_GRID = {
    "k_vola_spread": [0.6, 1.0, 1.4],
    "skew_coeff": [0.1, 0.35, 0.6],
    "levels_per_side": [2, 3, 4],
    "level_spacing_coeff": [0.2, 0.4, 0.6],
    "min_time_in_book_ms": [300, 550, 800],
    "replace_threshold_bps": [0.0, 3.0, 6.0],
    "imbalance_cutoff": [0.55, 0.65, 0.75],
}


class TestTunerBounds:
    def setup_method(self):
        self.tuner = WalkForwardTuner(seed=42)
    
    def test_random_parameter_generation(self):
        for _ in range(10):
            params = self.tuner._generate_random_params(PARAM_SPACE_RANDOM)

            assert set(params.keys()) == set(PARAM_SPACE_RANDOM.keys())

            assert isinstance(params["levels_per_side"], int)
            assert 2 <= params["levels_per_side"] <= 4

            assert isinstance(params["k_vola_spread"], float)
            assert 0.6 <= params["k_vola_spread"] <= 1.4

            assert isinstance(params["skew_coeff"], float)
            assert 0.1 <= params["skew_coeff"] <= 0.6

            assert isinstance(params["level_spacing_coeff"], float)
            assert 0.2 <= params["level_spacing_coeff"] <= 0.6

            assert isinstance(params["min_time_in_book_ms"], int)
            assert 300 <= params["min_time_in_book_ms"] <= 800

            assert isinstance(params["replace_threshold_bps"], float)
            assert 0.0 <= params["replace_threshold_bps"] <= 6.0

            assert isinstance(params["imbalance_cutoff"], float)
            assert 0.55 <= params["imbalance_cutoff"] <= 0.75
    
    def test_grid_parameter_generation(self):
        grid_points = self.tuner._generate_grid_params(PARAM_SPACE_GRID)
        assert len(grid_points) == (3 ** 7)
        for params in grid_points[:5]:
            assert set(params.keys()) == set(PARAM_SPACE_GRID.keys())
    
    def test_grid_parameter_values(self):
        grid_points = self.tuner._generate_grid_params(PARAM_SPACE_GRID)
        levels_values = [p["levels_per_side"] for p in grid_points]
        assert set(levels_values) == {2, 3, 4}
        
        k_vola_values = [p["k_vola_spread"] for p in grid_points]
        assert len(set(k_vola_values)) == 3
        for v in k_vola_values:
            assert 0.6 <= v <= 1.4
    
    def test_parameter_combinations_uniqueness(self):
        grid_points = self.tuner._generate_grid_params(PARAM_SPACE_GRID)
        tuples = [tuple(sorted(p.items())) for p in grid_points]
        assert len(tuples) == len(set(tuples))
    
    def test_parameter_bounds_edge_cases(self):
        min_params = {k: min(v) for k, v in PARAM_SPACE_GRID.items()}
        max_params = {k: max(v) for k, v in PARAM_SPACE_GRID.items()}

        assert set(min_params.keys()) == set(PARAM_SPACE_GRID.keys())
        assert set(max_params.keys()) == set(PARAM_SPACE_GRID.keys())

        assert min_params["levels_per_side"] == 2
        assert max_params["levels_per_side"] == 4
        assert 0.6 <= min_params["k_vola_spread"] <= 1.4
        assert 0.6 <= max_params["k_vola_spread"] <= 1.4
