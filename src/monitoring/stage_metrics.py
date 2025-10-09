"""
Stage metrics для Prometheus экспорта.

Метрики:
- mm_stage_duration_ms{stage} (Histogram)
- mm_exchange_req_ms{verb,api} (Histogram)
- mm_guard_trips_total{reason} (Counter)
- mm_tick_deadline_miss_total (Counter)
- mm_parallel_symbols (Gauge)
"""
from typing import Dict, Optional, Any, List
from collections import defaultdict

from src.monitoring.tracer import Trace, PerformanceTracer


class StageMetrics:
    """
    Метрики для стадий тика (Prometheus-ready).
    
    Features:
    - Stage duration histograms
    - Guard trip counters
    - Deadline miss tracking
    - Canary safety metrics
    """
    
    # Stage names (константы)
    STAGE_FETCH_MD = "stage_fetch_md"
    STAGE_SPREAD = "stage_spread"
    STAGE_GUARDS = "stage_guards"
    STAGE_EMIT = "stage_emit"
    STAGE_TICK_TOTAL = "tick_total"
    
    def __init__(self, deadline_ms: float = 200.0):
        """
        Инициализация.
        
        Args:
            deadline_ms: Deadline для тика (default: 200ms)
        """
        self.deadline_ms = deadline_ms
        
        # Stage duration tracking (для histogram)
        self._stage_durations: Dict[str, List[float]] = defaultdict(list)
        
        # Guard trips (для counter)
        self._guard_trips: Dict[str, int] = defaultdict(int)
        
        # Deadline misses (для counter)
        self._deadline_misses = 0
        self._total_ticks = 0
        
        # Exchange request tracking
        self._exchange_req_durations: Dict[str, List[float]] = defaultdict(list)  # key: "verb:api"
        
        # Parallel symbols (для gauge)
        self._parallel_symbols = 0
        
        # Chaos metrics
        self._chaos_injections: Dict[str, int] = defaultdict(int)  # scenario -> count
        self._reconnect_attempts: Dict[str, int] = defaultdict(int)  # kind -> count
        self._partial_fail_rate: Dict[str, float] = {}  # "op:exchange" -> rate
        self._ws_gap_ms: List[float] = []  # WebSocket gap histogram
        self._reconcile_discrepancies: Dict[str, int] = defaultdict(int)  # type -> count
    
    def record_trace(self, trace: Trace) -> None:
        """
        Записать метрики из трейса.
        
        Args:
            trace: Completed trace
        """
        self._total_ticks += 1
        
        # Record stage durations
        for span in trace.spans:
            self._stage_durations[span.name].append(span.duration_ms)
        
        # Record total tick duration
        total_ms = trace.total_duration_ms()
        self._stage_durations[self.STAGE_TICK_TOTAL].append(total_ms)
        
        # Check deadline miss
        if total_ms > self.deadline_ms:
            self._deadline_misses += 1
        
        # Extract metadata
        if "parallel_symbols" in trace.metadata:
            self._parallel_symbols = trace.metadata["parallel_symbols"]
    
    def record_guard_trip(self, reason: str) -> None:
        """
        Записать срабатывание guard.
        
        Args:
            reason: Причина срабатывания (e.g., "vol_hard", "latency_soft")
        """
        self._guard_trips[reason] += 1
    
    def record_exchange_req(self, verb: str, api: str, duration_ms: float) -> None:
        """
        Записать exchange request.
        
        Args:
            verb: HTTP verb (e.g., "POST", "GET")
            api: API endpoint (e.g., "create", "cancel", "batch-cancel")
            duration_ms: Request duration
        """
        key = f"{verb}:{api}"
        self._exchange_req_durations[key].append(duration_ms)
    
    def get_stage_percentiles(self, stage: str, percentiles: List[float] = [0.5, 0.95, 0.99]) -> Dict[float, float]:
        """
        Получить перцентили для стадии.
        
        Args:
            stage: Stage name
            percentiles: List of percentiles
        
        Returns:
            {percentile: duration_ms}
        """
        durations = self._stage_durations.get(stage, [])
        if not durations:
            return {p: 0.0 for p in percentiles}
        
        sorted_durations = sorted(durations)
        
        result = {}
        for p in percentiles:
            idx = int(len(sorted_durations) * p)
            if idx >= len(sorted_durations):
                idx = len(sorted_durations) - 1
            result[p] = sorted_durations[idx]
        
        return result
    
    def get_deadline_miss_pct(self) -> float:
        """
        Получить процент deadline misses.
        
        Returns:
            Percentage of deadline misses (should be <2% for canary)
        """
        if self._total_ticks == 0:
            return 0.0
        
        return (self._deadline_misses / self._total_ticks) * 100
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Получить summary всех метрик.
        
        Returns:
            Summary dict для экспорта
        """
        summary = {
            "total_ticks": self._total_ticks,
            "deadline_misses": self._deadline_misses,
            "deadline_miss_pct": self.get_deadline_miss_pct(),
            "parallel_symbols": self._parallel_symbols,
            "stage_percentiles": {},
            "guard_trips": dict(self._guard_trips),
            "exchange_req_percentiles": {}
        }
        
        # Stage percentiles
        for stage in [self.STAGE_FETCH_MD, self.STAGE_SPREAD, self.STAGE_GUARDS, 
                      self.STAGE_EMIT, self.STAGE_TICK_TOTAL]:
            percentiles = self.get_stage_percentiles(stage)
            summary["stage_percentiles"][stage] = {
                "p50": percentiles.get(0.5, 0.0),
                "p95": percentiles.get(0.95, 0.0),
                "p99": percentiles.get(0.99, 0.0)
            }
        
        # Exchange req percentiles
        for key, durations in self._exchange_req_durations.items():
            if durations:
                sorted_durations = sorted(durations)
                summary["exchange_req_percentiles"][key] = {
                    "p50": sorted_durations[int(len(sorted_durations) * 0.5)],
                    "p95": sorted_durations[int(len(sorted_durations) * 0.95)],
                    "p99": sorted_durations[int(len(sorted_durations) * 0.99)]
                }
        
        return summary
    
    def export_to_prometheus(self) -> str:
        """
        Экспорт метрик в Prometheus формат.
        
        Returns:
            Prometheus exposition format string
        """
        lines = []
        
        # Stage duration histograms
        for stage, durations in self._stage_durations.items():
            if not durations:
                continue
            
            percentiles = self.get_stage_percentiles(stage)
            
            lines.append(f"# HELP mm_stage_duration_ms Stage duration in milliseconds")
            lines.append(f"# TYPE mm_stage_duration_ms histogram")
            lines.append(f'mm_stage_duration_ms{{stage="{stage}",quantile="0.5"}} {percentiles.get(0.5, 0.0):.2f}')
            lines.append(f'mm_stage_duration_ms{{stage="{stage}",quantile="0.95"}} {percentiles.get(0.95, 0.0):.2f}')
            lines.append(f'mm_stage_duration_ms{{stage="{stage}",quantile="0.99"}} {percentiles.get(0.99, 0.0):.2f}')
        
        # Guard trips
        lines.append(f"# HELP mm_guard_trips_total Number of guard trips")
        lines.append(f"# TYPE mm_guard_trips_total counter")
        for reason, count in self._guard_trips.items():
            lines.append(f'mm_guard_trips_total{{reason="{reason}"}} {count}')
        
        # Deadline misses
        lines.append(f"# HELP mm_tick_deadline_miss_total Number of deadline misses")
        lines.append(f"# TYPE mm_tick_deadline_miss_total counter")
        lines.append(f"mm_tick_deadline_miss_total {self._deadline_misses}")
        
        # Parallel symbols
        lines.append(f"# HELP mm_parallel_symbols Number of parallel symbols")
        lines.append(f"# TYPE mm_parallel_symbols gauge")
        lines.append(f"mm_parallel_symbols {self._parallel_symbols}")
        
        # Chaos metrics
        lines.append(f"# HELP mm_chaos_injections_total Number of chaos injections")
        lines.append(f"# TYPE mm_chaos_injections_total counter")
        for scenario, count in self._chaos_injections.items():
            lines.append(f'mm_chaos_injections_total{{scenario="{scenario}"}} {count}')
        
        lines.append(f"# HELP mm_reconnect_attempts_total Number of reconnect attempts")
        lines.append(f"# TYPE mm_reconnect_attempts_total counter")
        for kind, count in self._reconnect_attempts.items():
            lines.append(f'mm_reconnect_attempts_total{{kind="{kind}"}} {count}')
        
        lines.append(f"# HELP mm_partial_fail_rate Partial failure rate")
        lines.append(f"# TYPE mm_partial_fail_rate gauge")
        for key, rate in self._partial_fail_rate.items():
            op, exchange = key.split(":")
            lines.append(f'mm_partial_fail_rate{{op="{op}",exchange="{exchange}"}} {rate:.4f}')
        
        # WS gap histogram
        if self._ws_gap_ms:
            sorted_gaps = sorted(self._ws_gap_ms)
            lines.append(f"# HELP mm_ws_gap_ms WebSocket gap in milliseconds")
            lines.append(f"# TYPE mm_ws_gap_ms histogram")
            lines.append(f'mm_ws_gap_ms{{quantile="0.5"}} {sorted_gaps[int(len(sorted_gaps)*0.5)]:.2f}')
            lines.append(f'mm_ws_gap_ms{{quantile="0.95"}} {sorted_gaps[int(len(sorted_gaps)*0.95)]:.2f}')
            lines.append(f'mm_ws_gap_ms{{quantile="0.99"}} {sorted_gaps[int(len(sorted_gaps)*0.99)]:.2f}')
        
        lines.append(f"# HELP mm_reconcile_discrepancies_total Number of reconcile discrepancies")
        lines.append(f"# TYPE mm_reconcile_discrepancies_total counter")
        for disc_type, count in self._reconcile_discrepancies.items():
            lines.append(f'mm_reconcile_discrepancies_total{{type="{disc_type}"}} {count}')
        
        return "\n".join(lines)
    
    def record_chaos_injection(self, scenario: str) -> None:
        """
        Record chaos injection.
        
        Args:
            scenario: Chaos scenario name (e.g., "net_loss", "exch_429")
        """
        self._chaos_injections[scenario] += 1
    
    def record_reconnect_attempt(self, kind: str) -> None:
        """
        Record reconnect attempt.
        
        Args:
            kind: Connection kind (e.g., "ws", "rest")
        """
        self._reconnect_attempts[kind] += 1
    
    def record_partial_fail_rate(self, op: str, exchange: str, rate: float) -> None:
        """
        Record partial failure rate.
        
        Args:
            op: Operation (e.g., "place", "cancel")
            exchange: Exchange name
            rate: Failure rate (0.0-1.0)
        """
        key = f"{op}:{exchange}"
        self._partial_fail_rate[key] = rate
    
    def record_ws_gap(self, gap_ms: float) -> None:
        """
        Record WebSocket gap (time between updates).
        
        Args:
            gap_ms: Gap in milliseconds
        """
        self._ws_gap_ms.append(gap_ms)
        
        # Keep last 1000 samples
        if len(self._ws_gap_ms) > 1000:
            self._ws_gap_ms = self._ws_gap_ms[-1000:]
    
    def record_reconcile_discrepancy(self, discrepancy_type: str) -> None:
        """
        Record order reconcile discrepancy.
        
        Args:
            discrepancy_type: Type of discrepancy (e.g., "status_mismatch", "qty_mismatch")
        """
        self._reconcile_discrepancies[discrepancy_type] += 1
    
    def reset(self) -> None:
        """Сбросить все метрики (для тестов)."""
        self._stage_durations.clear()
        self._guard_trips.clear()
        self._deadline_misses = 0
        self._total_ticks = 0
        self._exchange_req_durations.clear()
        self._parallel_symbols = 0
        
        # Reset chaos metrics
        self._chaos_injections.clear()
        self._reconnect_attempts.clear()
        self._partial_fail_rate.clear()
        self._ws_gap_ms.clear()
        self._reconcile_discrepancies.clear()


# Global metrics instance
_global_metrics: Optional[StageMetrics] = None


def get_metrics() -> StageMetrics:
    """Get global metrics instance."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = StageMetrics()
    return _global_metrics


def init_metrics(deadline_ms: float = 200.0) -> StageMetrics:
    """
    Initialize global metrics.
    
    Args:
        deadline_ms: Deadline для тика
    
    Returns:
        Metrics instance
    """
    global _global_metrics
    _global_metrics = StageMetrics(deadline_ms=deadline_ms)
    return _global_metrics
