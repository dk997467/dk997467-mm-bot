"""Tests for LiveController FSM."""
import pytest
from tools.live.controller import LiveController, LiveState, KPIThresholds, SymbolKPI


class TestLiveControllerFSM:
    """Test FSM transitions."""
    
    def test_active_to_cooldown_on_warn(self):
        """ACTIVE → COOLDOWN when WARN count >= min_warn_windows."""
        controller = LiveController(KPIThresholds(min_warn_windows=2))
        
        # Simulate 2 symbols with WARN status
        kpis = [
            SymbolKPI(symbol="BTCUSDT", edge_bps=3.0, maker_taker_ratio=0.80, p95_latency_ms=360, risk_ratio=0.38),
            SymbolKPI(symbol="ETHUSDT", edge_bps=2.8, maker_taker_ratio=0.81, p95_latency_ms=355, risk_ratio=0.39)
        ]
        
        decision = controller.decide(kpis)
        
        assert decision.next_state == LiveState.COOLDOWN
        assert 0.3 <= decision.throttle_factor <= 0.8
    
    def test_cooldown_to_frozen_on_crit(self):
        """COOLDOWN → FROZEN when CRIT violations occur."""
        controller = LiveController(KPIThresholds())
        controller.current_state = LiveState.COOLDOWN
        
        # Simulate CRIT violation
        kpis = [
            SymbolKPI(symbol="BTCUSDT", edge_bps=2.0, maker_taker_ratio=0.85, p95_latency_ms=300, risk_ratio=0.45)  # risk > max_risk
        ]
        
        decision = controller.decide(kpis)
        
        assert decision.next_state == LiveState.FROZEN
        assert decision.throttle_factor == 0.0
        assert "BTCUSDT" in decision.per_symbol_throttle
        assert decision.per_symbol_throttle["BTCUSDT"] == 0.0
    
    def test_frozen_to_active_hysteresis(self):
        """FROZEN → ACTIVE requires unfreeze_after_ok_windows consecutive OK."""
        controller = LiveController(KPIThresholds(unfreeze_after_ok_windows=3, min_ok_windows=2))
        controller.current_state = LiveState.FROZEN
        
        # Simulate OK KPI
        kpis = [
            SymbolKPI(symbol="BTCUSDT", edge_bps=3.5, maker_taker_ratio=0.85, p95_latency_ms=300, risk_ratio=0.35),
            SymbolKPI(symbol="ETHUSDT", edge_bps=3.0, maker_taker_ratio=0.84, p95_latency_ms=310, risk_ratio=0.36)
        ]
        
        # First OK - still FROZEN (hysteresis not satisfied)
        decision1 = controller.decide(kpis)
        assert decision1.next_state == LiveState.FROZEN
        assert controller.ok_counter == 1
        
        # Second OK - still FROZEN
        decision2 = controller.decide(kpis)
        assert decision2.next_state == LiveState.FROZEN
        assert controller.ok_counter == 2
        
        # Third OK - should unfreeze
        decision3 = controller.decide(kpis)
        assert decision3.next_state == LiveState.ACTIVE
        assert decision3.throttle_factor == 1.0
    
    def test_anomaly_score_triggers_crit(self):
        """High anomaly_score should trigger CRIT."""
        controller = LiveController(KPIThresholds(anomaly_threshold=2.0))
        
        kpis = [
            SymbolKPI(symbol="BTCUSDT", edge_bps=3.5, maker_taker_ratio=0.85, 
                     p95_latency_ms=300, risk_ratio=0.35, anomaly_score=3.0)  # > threshold
        ]
        
        decision = controller.decide(kpis)
        
        assert decision.next_state == LiveState.FROZEN
        assert "anomaly_score" in str(decision.reasons)


class TestPerSymbolThrottle:
    """Test per-symbol throttle calculation."""
    
    def test_mixed_symbol_status(self):
        """Test throttle for mixed OK/WARN/CRIT symbols."""
        controller = LiveController()
        
        kpis = [
            SymbolKPI(symbol="BTCUSDT", edge_bps=3.5, maker_taker_ratio=0.85, p95_latency_ms=300, risk_ratio=0.35),  # OK
            SymbolKPI(symbol="ETHUSDT", edge_bps=2.8, maker_taker_ratio=0.80, p95_latency_ms=360, risk_ratio=0.38),  # WARN
            SymbolKPI(symbol="SOLUSDT", edge_bps=2.0, maker_taker_ratio=0.75, p95_latency_ms=300, risk_ratio=0.45)   # CRIT
        ]
        
        decision = controller.decide(kpis)
        
        # Check per-symbol throttle
        assert decision.per_symbol_throttle["BTCUSDT"] == 1.0  # OK
        assert 0.3 <= decision.per_symbol_throttle["ETHUSDT"] <= 0.8  # WARN
        assert decision.per_symbol_throttle["SOLUSDT"] == 0.0  # CRIT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

