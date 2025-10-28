#!/usr/bin/env python3
"""Unit tests for tools.tuning.report_tuning pure functions."""
import pytest
from tools.tuning.report_tuning import _select_candidate, _extract_candidates, _render_md


class TestSelectCandidate:
    """Tests for _select_candidate function."""
    
    def test_empty_sweep(self):
        """Test with empty sweep."""
        sweep = {}
        result = _select_candidate(sweep)
        
        assert result['verdict'] == 'HOLD'
        assert result['params'] == {}
    
    def test_from_top3_safe(self):
        """Test selection from top3_by_net_bps_safe."""
        sweep = {
            'top3_by_net_bps_safe': [
                {'params': {'a': 1}, 'verdict': 'BEST'},
                {'params': {'a': 2}, 'verdict': 'GOOD'}
            ],
            'results': [
                {'params': {'a': 3}, 'verdict': 'OK'}
            ]
        }
        result = _select_candidate(sweep)
        
        assert result['verdict'] == 'BEST'
        assert result['params']['a'] == 1
    
    def test_from_results_fallback(self):
        """Test fallback to results if no top3."""
        sweep = {
            'results': [
                {'params': {'b': 1}, 'verdict': 'OK'},
                {'params': {'b': 2}, 'verdict': 'SKIP'}
            ]
        }
        result = _select_candidate(sweep)
        
        assert result['verdict'] == 'OK'
        assert result['params']['b'] == 1
    
    def test_empty_results_fallback(self):
        """Test fallback with empty results."""
        sweep = {'results': []}
        result = _select_candidate(sweep)
        
        assert result['verdict'] == 'HOLD'
        assert result['params'] == {}


class TestExtractCandidates:
    """Tests for _extract_candidates function."""
    
    def test_empty_sweep(self):
        """Test with empty sweep."""
        sweep = {}
        result = _extract_candidates(sweep, k=3)
        
        assert result == []
    
    def test_from_top3_safe(self):
        """Test extraction from top3_by_net_bps_safe."""
        sweep = {
            'top3_by_net_bps_safe': [
                {'params': {'a': 1}, 'verdict': 'BEST'},
                {'params': {'a': 2}, 'verdict': 'GOOD'},
                {'params': {'a': 3}, 'verdict': 'OK'}
            ]
        }
        result = _extract_candidates(sweep, k=2)
        
        assert len(result) == 2
        assert result[0]['verdict'] == 'BEST'
        assert result[1]['verdict'] == 'GOOD'
    
    def test_from_results_fallback(self):
        """Test fallback to results if no top3."""
        sweep = {
            'results': [
                {'params': {'b': 1}, 'verdict': 'A'},
                {'params': {'b': 2}, 'verdict': 'B'},
                {'params': {'b': 3}, 'verdict': 'C'},
                {'params': {'b': 4}, 'verdict': 'D'}
            ]
        }
        result = _extract_candidates(sweep, k=3)
        
        assert len(result) == 3
        assert result[0]['verdict'] == 'A'
        assert result[2]['verdict'] == 'C'
    
    def test_k_larger_than_available(self):
        """Test k larger than available candidates."""
        sweep = {
            'results': [
                {'params': {'x': 1}, 'verdict': 'ONLY'}
            ]
        }
        result = _extract_candidates(sweep, k=10)
        
        assert len(result) == 1
        assert result[0]['verdict'] == 'ONLY'
    
    def test_default_k_value(self):
        """Test default k=3."""
        sweep = {
            'results': [
                {'params': {'i': i}, 'verdict': f'V{i}'} for i in range(5)
            ]
        }
        result = _extract_candidates(sweep)
        
        assert len(result) == 3


class TestRenderMd:
    """Tests for _render_md function."""
    
    def test_empty_report(self):
        """Test rendering report with no candidates."""
        report = {
            'selected': None,
            'candidates': [],
            'runtime': {'utc': '2025-01-01T00:00:00Z'}
        }
        md = _render_md(report)
        
        assert "TUNING REPORT" in md
        assert "No candidates available" in md
        assert md.endswith("\n")
    
    def test_with_selected_candidate(self):
        """Test rendering with selected candidate."""
        report = {
            'selected': {
                'verdict': 'BEST',
                'params': {
                    'max_delta_ratio': 0.15,
                    'impact_cap_ratio': 0.25
                },
                'metrics_before': {'net_bps': 2.5},
                'metrics_after': {'net_bps': 3.5, 'order_age_p95_ms': 310.0}
            },
            'candidates': []
        }
        md = _render_md(report)
        
        assert "**Verdict:** BEST" in md
        assert "max_delta_ratio: 0.150000" in md
        assert "impact_cap_ratio: 0.250000" in md
        assert "net_bps_before: 2.500000" in md
        assert "net_bps_after: 3.500000" in md
    
    def test_candidates_table(self):
        """Test rendering candidates table."""
        report = {
            'selected': None,
            'candidates': [
                {
                    'verdict': 'BEST',
                    'params': {
                        'max_delta_ratio': 0.1,
                        'impact_cap_ratio': 0.2,
                        'min_interval_ms': 100.0,
                        'tail_age_ms': 500.0
                    },
                    'metrics_before': {'net_bps': 2.0},
                    'metrics_after': {'net_bps': 3.0, 'order_age_p95_ms': 300.0}
                }
            ]
        }
        md = _render_md(report)
        
        assert "| verdict |" in md
        assert "| BEST |" in md
        assert "0.100000" in md
        assert "0.200000" in md
    
    def test_sorted_params_in_selected(self):
        """Test that params are sorted in selected section."""
        report = {
            'selected': {
                'verdict': 'OK',
                'params': {
                    'z_param': 1.0,
                    'a_param': 2.0,
                    'm_param': 3.0
                },
                'metrics_before': {},
                'metrics_after': {}
            },
            'candidates': []
        }
        md = _render_md(report)
        
        # Check that params appear in sorted order
        a_idx = md.index('a_param')
        m_idx = md.index('m_param')
        z_idx = md.index('z_param')
        assert a_idx < m_idx < z_idx
    
    def test_deterministic_output(self):
        """Test that output is deterministic."""
        report = {
            'selected': {'verdict': 'OK', 'params': {}, 'metrics_before': {}, 'metrics_after': {}},
            'candidates': []
        }
        md1 = _render_md(report)
        md2 = _render_md(report)
        
        assert md1 == md2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

