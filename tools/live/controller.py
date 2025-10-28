#!/usr/bin/env python3
"""
Live Mode Controller: FSM + hysteresis + auto-freeze logic.

States: ACTIVE, COOLDOWN, FROZEN
Transitions based on KPI thresholds and window counters.
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class LiveState(str, Enum):
    """Live mode FSM states."""
    ACTIVE = "ACTIVE"      # Full throttle (1.0)
    COOLDOWN = "COOLDOWN"  # Reduced throttle (0.3-0.6)
    FROZEN = "FROZEN"      # Zero throttle (0.0)


@dataclass
class KPIThresholds:
    """KPI thresholds for freeze/unfreeze decisions."""
    min_edge_bps: float = 2.5
    min_maker_taker: float = 0.83
    max_risk: float = 0.40
    max_latency_ms: float = 350.0
    
    # Window thresholds
    min_ok_windows: int = 12
    min_warn_windows: int = 12
    max_crit_windows: int = 0
    unfreeze_after_ok_windows: int = 24  # Hysteresis
    
    # Anomaly detection (optional)
    anomaly_threshold: float = 2.0


@dataclass
class SymbolKPI:
    """Per-symbol KPI snapshot."""
    symbol: str
    edge_bps: Optional[float] = None
    maker_taker_ratio: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    risk_ratio: Optional[float] = None
    anomaly_score: Optional[float] = None
    window_index: Optional[int] = None


@dataclass
class ControllerDecision:
    """Controller decision output."""
    next_state: LiveState
    throttle_factor: float  # 0.0 to 1.0
    reasons: List[str]
    per_symbol_throttle: Dict[str, float]
    triggered_by: Optional[str] = None  # Symbol that triggered freeze
    timestamp_utc: str = ""


class LiveController:
    """
    Live mode FSM controller with hysteresis and auto-freeze.
    
    FSM transitions:
    - ACTIVE → COOLDOWN: WARN violations accumulate
    - COOLDOWN → FROZEN: CRIT violations occur
    - FROZEN → ACTIVE: Hysteresis (unfreeze_after_ok_windows consecutive OK)
    """
    
    def __init__(self, thresholds: Optional[KPIThresholds] = None):
        self.thresholds = thresholds or KPIThresholds()
        self.current_state = LiveState.ACTIVE
        self.ok_counter = 0  # For hysteresis (unfreeze)
        self.warn_counter = 0
        self.crit_counter = 0
        
        logger.info(f"LiveController initialized: state={self.current_state}, thresholds={asdict(self.thresholds)}")
    
    def evaluate_symbol_kpi(self, kpi: SymbolKPI) -> Tuple[str, List[str]]:
        """
        Evaluate single symbol KPI against thresholds.
        
        Returns: (status: "OK"|"WARN"|"CRIT", reasons: List[str])
        """
        reasons = []
        status = "OK"
        
        # Check edge_bps
        if kpi.edge_bps is not None and kpi.edge_bps < self.thresholds.min_edge_bps:
            reasons.append(f"edge_bps={kpi.edge_bps:.2f} < {self.thresholds.min_edge_bps}")
            status = "CRIT"
        
        # Check maker_taker_ratio
        if kpi.maker_taker_ratio is not None and kpi.maker_taker_ratio < self.thresholds.min_maker_taker:
            reasons.append(f"maker_taker={kpi.maker_taker_ratio:.3f} < {self.thresholds.min_maker_taker}")
            if status != "CRIT":
                status = "WARN"
        
        # Check risk_ratio
        if kpi.risk_ratio is not None and kpi.risk_ratio > self.thresholds.max_risk:
            reasons.append(f"risk={kpi.risk_ratio:.3f} > {self.thresholds.max_risk}")
            status = "CRIT"
        
        # Check p95_latency_ms
        if kpi.p95_latency_ms is not None and kpi.p95_latency_ms > self.thresholds.max_latency_ms:
            reasons.append(f"p95_latency={kpi.p95_latency_ms:.0f}ms > {self.thresholds.max_latency_ms}ms")
            if status != "CRIT":
                status = "WARN"
        
        # Check anomaly_score (optional)
        if kpi.anomaly_score is not None and kpi.anomaly_score > self.thresholds.anomaly_threshold:
            reasons.append(f"anomaly_score={kpi.anomaly_score:.2f} > {self.thresholds.anomaly_threshold}")
            status = "CRIT"
        
        return status, reasons
    
    def decide(self, symbols_kpi: List[SymbolKPI]) -> ControllerDecision:
        """
        Main decision function: evaluates KPIs and determines next state + throttle.
        
        Logic:
        1. Evaluate each symbol
        2. Count OK/WARN/CRIT across symbols
        3. Apply FSM transitions
        4. Calculate throttle factors
        """
        if not symbols_kpi:
            logger.warning("No symbols KPI provided, staying in current state")
            return ControllerDecision(
                next_state=self.current_state,
                throttle_factor=self._get_throttle_for_state(self.current_state),
                reasons=["no_kpi_data"],
                per_symbol_throttle={},
                timestamp_utc=datetime.now(timezone.utc).isoformat()
            )
        
        # Evaluate all symbols
        evaluations = {}
        ok_count = 0
        warn_count = 0
        crit_count = 0
        
        for kpi in symbols_kpi:
            status, reasons = self.evaluate_symbol_kpi(kpi)
            evaluations[kpi.symbol] = {
                "status": status,
                "reasons": reasons
            }
            
            if status == "OK":
                ok_count += 1
            elif status == "WARN":
                warn_count += 1
            else:  # CRIT
                crit_count += 1
        
        logger.debug(f"Evaluations: OK={ok_count}, WARN={warn_count}, CRIT={crit_count}")
        
        # FSM logic
        next_state, decision_reasons, triggered_by = self._apply_fsm_logic(
            ok_count, warn_count, crit_count, evaluations
        )
        
        # Calculate throttle
        throttle_factor = self._get_throttle_for_state(next_state)
        per_symbol_throttle = {}
        
        for kpi in symbols_kpi:
            sym_status = evaluations[kpi.symbol]["status"]
            if sym_status == "OK":
                per_symbol_throttle[kpi.symbol] = 1.0
            elif sym_status == "WARN":
                per_symbol_throttle[kpi.symbol] = 0.5
            else:  # CRIT
                per_symbol_throttle[kpi.symbol] = 0.0
        
        # Update internal state
        self.current_state = next_state
        
        decision = ControllerDecision(
            next_state=next_state,
            throttle_factor=throttle_factor,
            reasons=decision_reasons,
            per_symbol_throttle=per_symbol_throttle,
            triggered_by=triggered_by,
            timestamp_utc=datetime.now(timezone.utc).isoformat()
        )
        
        logger.info(f"Decision: state={next_state}, throttle={throttle_factor:.2f}, reasons={decision_reasons}")
        
        return decision
    
    def _apply_fsm_logic(
        self,
        ok_count: int,
        warn_count: int,
        crit_count: int,
        evaluations: Dict
    ) -> Tuple[LiveState, List[str], Optional[str]]:
        """
        Apply FSM transition logic.
        
        Returns: (next_state, reasons, triggered_by_symbol)
        """
        reasons = []
        triggered_by = None
        
        # CRIT → immediate freeze
        if crit_count > self.thresholds.max_crit_windows:
            if self.current_state != LiveState.FROZEN:
                reasons.append(f"crit_violations={crit_count} > max_crit_windows={self.thresholds.max_crit_windows}")
                # Find which symbol triggered
                for sym, eval_data in evaluations.items():
                    if eval_data["status"] == "CRIT":
                        triggered_by = sym
                        break
                self.crit_counter += 1
                self.ok_counter = 0  # Reset hysteresis
                return LiveState.FROZEN, reasons, triggered_by
        
        # Current state logic
        if self.current_state == LiveState.ACTIVE:
            # ACTIVE → COOLDOWN if too many WARNs
            if warn_count >= self.thresholds.min_warn_windows:
                reasons.append(f"warn_violations={warn_count} >= min_warn_windows={self.thresholds.min_warn_windows}")
                self.warn_counter += 1
                self.ok_counter = 0
                return LiveState.COOLDOWN, reasons, None
            elif ok_count >= self.thresholds.min_ok_windows:
                reasons.append(f"ok_count={ok_count} >= min_ok_windows={self.thresholds.min_ok_windows}")
                self.ok_counter += 1
                return LiveState.ACTIVE, reasons, None
            else:
                reasons.append("insufficient_ok_windows")
                return LiveState.ACTIVE, reasons, None
        
        elif self.current_state == LiveState.COOLDOWN:
            # COOLDOWN → FROZEN if CRIT
            if crit_count > 0:
                reasons.append(f"crit_count={crit_count} in cooldown")
                self.crit_counter += 1
                self.ok_counter = 0
                for sym, eval_data in evaluations.items():
                    if eval_data["status"] == "CRIT":
                        triggered_by = sym
                        break
                return LiveState.FROZEN, reasons, triggered_by
            # COOLDOWN → ACTIVE if stable OK
            elif ok_count >= self.thresholds.min_ok_windows and warn_count == 0:
                reasons.append(f"ok_count={ok_count}, warn_count=0")
                self.ok_counter += 1
                self.warn_counter = 0
                return LiveState.ACTIVE, reasons, None
            else:
                reasons.append("cooldown_monitoring")
                return LiveState.COOLDOWN, reasons, None
        
        else:  # FROZEN
            # FROZEN → ACTIVE: hysteresis (need consecutive OK windows)
            if ok_count >= self.thresholds.min_ok_windows and warn_count == 0 and crit_count == 0:
                self.ok_counter += 1
                if self.ok_counter >= self.thresholds.unfreeze_after_ok_windows:
                    reasons.append(f"hysteresis_satisfied: {self.ok_counter} consecutive OK windows")
                    self.warn_counter = 0
                    self.crit_counter = 0
                    return LiveState.ACTIVE, reasons, None
                else:
                    reasons.append(f"hysteresis_progress: {self.ok_counter}/{self.thresholds.unfreeze_after_ok_windows}")
                    return LiveState.FROZEN, reasons, None
            else:
                # Reset hysteresis if violations occur
                self.ok_counter = 0
                reasons.append(f"frozen: ok={ok_count}, warn={warn_count}, crit={crit_count}")
                return LiveState.FROZEN, reasons, None
    
    def _get_throttle_for_state(self, state: LiveState) -> float:
        """Map state to throttle factor."""
        if state == LiveState.ACTIVE:
            return 1.0
        elif state == LiveState.COOLDOWN:
            return 0.5
        else:  # FROZEN
            return 0.0
    
    def export_decision_to_file(self, decision: ControllerDecision, out_path: Path) -> None:
        """Export decision to LIVE_DECISION.json."""
        decision_dict = {
            "next_state": decision.next_state.value,
            "throttle_factor": decision.throttle_factor,
            "reasons": decision.reasons,
            "per_symbol_throttle": decision.per_symbol_throttle,
            "triggered_by": decision.triggered_by,
            "timestamp_utc": decision.timestamp_utc,
            "thresholds": asdict(self.thresholds),
            "counters": {
                "ok_counter": self.ok_counter,
                "warn_counter": self.warn_counter,
                "crit_counter": self.crit_counter
            }
        }
        
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(decision_dict, indent=2), encoding="utf-8")
        logger.info(f"Decision exported to {out_path}")


if __name__ == "__main__":
    # Simple test
    logging.basicConfig(level=logging.DEBUG)
    
    controller = LiveController()
    
    # Test case: ACTIVE → COOLDOWN
    test_kpis = [
        SymbolKPI(symbol="BTCUSDT", edge_bps=3.5, maker_taker_ratio=0.85, p95_latency_ms=300, risk_ratio=0.35),
        SymbolKPI(symbol="ETHUSDT", edge_bps=2.0, maker_taker_ratio=0.80, p95_latency_ms=360, risk_ratio=0.38)
    ]
    
    decision = controller.decide(test_kpis)
    print(f"\nDecision: {decision.next_state}, throttle={decision.throttle_factor}, reasons={decision.reasons}")
    print(f"Per-symbol: {decision.per_symbol_throttle}")

