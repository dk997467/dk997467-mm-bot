"""
Chaos Injector для resilience testing.

10 сценариев хаоса с контролируемой инъекцией и метриками.
"""
import time
import random
import asyncio
from typing import Dict, Optional, Any, List
from enum import Enum
from dataclasses import dataclass, field

from src.common.config import ChaosConfig


class ChaosScenario(Enum):
    """Типы chaos сценариев."""
    NET_LOSS = "net_loss"
    EXCH_429 = "exch_429"
    EXCH_5XX = "exch_5xx"
    LAT_SPIKE = "lat_spike"
    WS_LAG = "ws_lag"
    WS_DISCONNECT = "ws_disconnect"
    DNS_FLAP = "dns_flap"
    CLOCK_SKEW = "clock_skew"
    MEM_PRESSURE = "mem_pressure"
    RATE_LIMIT_STORM = "rate_limit_storm"
    RECONCILE_MISMATCH = "reconcile_mismatch"


@dataclass
class ChaosInjection:
    """Record одной инъекции хаоса."""
    scenario: ChaosScenario
    intensity: float
    duration_ms: float
    reason_code: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChaosInjector:
    """
    Инжектор хаоса для тестирования устойчивости.
    
    Features:
    - 10 сценариев (NET_LOSS, EXCH_429, LAT_SPIKE, etc.)
    - Burst control (duty cycle on/off)
    - Метрики: mm_chaos_injections_total{scenario}
    - JSON logging каждой инъекции
    """
    
    def __init__(self, config: ChaosConfig):
        """
        Инициализация.
        
        Args:
            config: Chaos configuration
        """
        self.config = config
        self.enabled = config.enabled
        self.dry_run = config.dry_run
        
        # Burst state
        self._burst_state = "off"  # "on" | "off"
        self._burst_last_switch_ms = int(time.time() * 1000)
        
        # Injection log
        self._injections: List[ChaosInjection] = []
        
        # Counters for metrics
        self._injection_counts: Dict[str, int] = {}
        
        print(f"[CHAOS] Initialized: enabled={self.enabled}, dry_run={self.dry_run}")
    
    def _update_burst_state(self) -> None:
        """Update burst state (on/off duty cycle)."""
        now_ms = int(time.time() * 1000)
        elapsed_sec = (now_ms - self._burst_last_switch_ms) / 1000
        
        if self._burst_state == "on":
            if elapsed_sec >= self.config.burst_on_sec:
                self._burst_state = "off"
                self._burst_last_switch_ms = now_ms
        else:
            if elapsed_sec >= self.config.burst_off_sec:
                self._burst_state = "on"
                self._burst_last_switch_ms = now_ms
    
    def is_burst_active(self) -> bool:
        """Check if burst is currently active."""
        if not self.enabled:
            return False
        
        self._update_burst_state()
        return self._burst_state == "on"
    
    def should_inject_net_loss(self) -> bool:
        """
        Check if packet should be dropped (NET_LOSS).
        
        Returns:
            True if packet should be dropped
        """
        if not self.is_burst_active() or self.config.net_loss == 0.0:
            return False
        
        should_drop = random.random() < self.config.net_loss
        
        if should_drop:
            self._record_injection(ChaosScenario.NET_LOSS, self.config.net_loss, 0.0, "packet_dropped")
        
        return should_drop
    
    def should_inject_http_429(self) -> bool:
        """
        Check if HTTP 429 should be injected (EXCH_429).
        
        Returns:
            True if 429 should be returned
        """
        if not self.is_burst_active() or self.config.exch_429 == 0.0:
            return False
        
        should_429 = random.random() < self.config.exch_429
        
        if should_429:
            self._record_injection(ChaosScenario.EXCH_429, self.config.exch_429, 0.0, "http_429_rate_limit")
        
        return should_429
    
    def should_inject_http_5xx(self) -> bool:
        """
        Check if HTTP 5xx should be injected (EXCH_5XX).
        
        Returns:
            True if 5xx should be returned
        """
        if not self.is_burst_active() or self.config.exch_5xx == 0.0:
            return False
        
        should_5xx = random.random() < self.config.exch_5xx
        
        if should_5xx:
            self._record_injection(ChaosScenario.EXCH_5XX, self.config.exch_5xx, 0.0, "http_5xx_server_error")
        
        return should_5xx
    
    async def inject_latency_spike(self) -> None:
        """
        Inject latency spike (LAT_SPIKE).
        
        Delays execution by configured amount.
        """
        if not self.is_burst_active() or self.config.lat_spike_ms == 0:
            return
        
        delay_ms = self.config.lat_spike_ms
        self._record_injection(ChaosScenario.LAT_SPIKE, 1.0, delay_ms, "latency_spike_injected")
        
        await asyncio.sleep(delay_ms / 1000)
    
    def should_inject_ws_disconnect(self) -> bool:
        """
        Check if WebSocket should disconnect (WS_DISCONNECT).
        
        Returns:
            True if WS should disconnect
        """
        if not self.is_burst_active() or self.config.ws_disconnect == 0.0:
            return False
        
        # Probability per minute -> per second
        prob_per_sec = self.config.ws_disconnect / 60.0
        should_disconnect = random.random() < prob_per_sec
        
        if should_disconnect:
            self._record_injection(ChaosScenario.WS_DISCONNECT, self.config.ws_disconnect, 0.0, "ws_disconnect_forced")
        
        return should_disconnect
    
    def should_inject_dns_flap(self) -> bool:
        """
        Check if DNS should fail (DNS_FLAP).
        
        Returns:
            True if DNS should fail (NXDOMAIN/timeout)
        """
        if not self.is_burst_active() or self.config.dns_flap == 0.0:
            return False
        
        should_fail = random.random() < self.config.dns_flap
        
        if should_fail:
            self._record_injection(ChaosScenario.DNS_FLAP, self.config.dns_flap, 0.0, "dns_nxdomain_or_timeout")
        
        return should_fail
    
    def get_clock_skew_ms(self) -> int:
        """
        Get clock skew (CLOCK_SKEW).
        
        Returns:
            Clock skew in milliseconds (can be negative)
        """
        if not self.is_burst_active() or self.config.clock_skew_ms == 0:
            return 0
        
        # Random skew between [-clock_skew_ms, +clock_skew_ms]
        skew_ms = random.randint(-self.config.clock_skew_ms, self.config.clock_skew_ms)
        
        if skew_ms != 0:
            self._record_injection(ChaosScenario.CLOCK_SKEW, abs(skew_ms) / self.config.clock_skew_ms, 
                                 abs(skew_ms), f"clock_skew_{'+' if skew_ms > 0 else '-'}{abs(skew_ms)}ms")
        
        return skew_ms
    
    def should_inject_reconcile_mismatch(self) -> bool:
        """
        Check if order reconcile mismatch should be injected (RECONCILE_MISMATCH).
        
        Returns:
            True if order state should mismatch
        """
        if not self.is_burst_active() or self.config.reconcile_mismatch == 0.0:
            return False
        
        should_mismatch = random.random() < self.config.reconcile_mismatch
        
        if should_mismatch:
            self._record_injection(ChaosScenario.RECONCILE_MISMATCH, self.config.reconcile_mismatch, 
                                 0.0, "order_state_mismatch")
        
        return should_mismatch
    
    def _record_injection(self, scenario: ChaosScenario, intensity: float, duration_ms: float, reason_code: str) -> None:
        """
        Record chaos injection.
        
        Args:
            scenario: Chaos scenario type
            intensity: Injection intensity (0.0-1.0)
            duration_ms: Duration of injection
            reason_code: Human-readable reason
        """
        injection = ChaosInjection(
            scenario=scenario,
            intensity=intensity,
            duration_ms=duration_ms,
            reason_code=reason_code
        )
        
        self._injections.append(injection)
        
        # Update counter
        scenario_name = scenario.value
        self._injection_counts[scenario_name] = self._injection_counts.get(scenario_name, 0) + 1
    
    def get_injections(self, clear: bool = True) -> List[ChaosInjection]:
        """
        Get recorded injections.
        
        Args:
            clear: Clear buffer after retrieval
        
        Returns:
            List of injections
        """
        injections = list(self._injections)
        
        if clear:
            self._injections.clear()
        
        return injections
    
    def get_injection_counts(self) -> Dict[str, int]:
        """
        Get injection counts by scenario.
        
        Returns:
            {scenario_name: count}
        """
        return dict(self._injection_counts)
    
    def export_to_json(self) -> Dict[str, Any]:
        """
        Export chaos state to JSON.
        
        Returns:
            JSON-serializable dict
        """
        return {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "burst_state": self._burst_state,
            "injection_counts": self.get_injection_counts(),
            "config": {
                "net_loss": self.config.net_loss,
                "exch_429": self.config.exch_429,
                "exch_5xx": self.config.exch_5xx,
                "lat_spike_ms": self.config.lat_spike_ms,
                "ws_lag_ms": self.config.ws_lag_ms,
                "ws_disconnect": self.config.ws_disconnect,
                "dns_flap": self.config.dns_flap,
                "clock_skew_ms": self.config.clock_skew_ms,
                "mem_pressure": self.config.mem_pressure,
                "rate_limit_storm": self.config.rate_limit_storm,
                "reconcile_mismatch": self.config.reconcile_mismatch
            }
        }


# Global injector instance
_global_injector: Optional[ChaosInjector] = None


def get_chaos_injector() -> Optional[ChaosInjector]:
    """Get global chaos injector instance."""
    return _global_injector


def init_chaos_injector(config: ChaosConfig) -> ChaosInjector:
    """
    Initialize global chaos injector.
    
    Args:
        config: Chaos configuration
    
    Returns:
        Injector instance
    """
    global _global_injector
    _global_injector = ChaosInjector(config)
    return _global_injector
