"""
Minimal performance tracer для измерения стадий торгового тика.

stdlib-only (time.monotonic_ns), thread-local буфер, детерминированный вывод.
"""
import time
import threading
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Span:
    """Временной отрезок для одной стадии."""
    name: str
    start_ns: int
    end_ns: int = 0
    duration_ms: float = 0.0
    
    def finish(self) -> None:
        """Завершить span и вычислить duration."""
        self.end_ns = time.monotonic_ns()
        self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000


@dataclass
class Trace:
    """Трейс одного тика."""
    trace_id: str
    start_ns: int
    end_ns: int = 0
    spans: List[Span] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self) -> None:
        """Завершить трейс."""
        self.end_ns = time.monotonic_ns()
    
    def total_duration_ms(self) -> float:
        """Общая продолжительность трейса."""
        if self.end_ns == 0:
            return 0.0
        return (self.end_ns - self.start_ns) / 1_000_000
    
    def get_stage_durations(self) -> Dict[str, float]:
        """Получить duration всех стадий."""
        return {span.name: span.duration_ms for span in self.spans}


class PerformanceTracer:
    """
    Минимальный трейсер для измерения стадий тика.
    
    Features:
    - stdlib-only (time.monotonic_ns)
    - thread-local storage
    - sampling support (trace.sample_rate)
    - deterministic output (ASCII-JSON)
    - low overhead (≤3%)
    """
    
    def __init__(self, enabled: bool = True, sample_rate: float = 1.0):
        """
        Инициализация.
        
        Args:
            enabled: Включить трейсинг (rollback via trace.enabled=false)
            sample_rate: Доля тиков для трейсинга (0.0-1.0)
        """
        self.enabled = enabled
        self.sample_rate = sample_rate
        
        # Thread-local storage для текущего трейса
        self._local = threading.local()
        
        # Счётчик тиков для сэмплинга
        self._tick_counter = 0
        self._tick_counter_lock = threading.Lock()
        
        # Accumulated traces для агрегации
        self._traces: List[Trace] = []
        self._traces_lock = threading.Lock()
        
        # Overhead tracking
        self._overhead_ns = 0
        self._overhead_samples = 0
    
    def should_trace(self) -> bool:
        """
        Проверить, нужно ли трейсить текущий тик (сэмплинг).
        
        Returns:
            True, если нужно трейсить
        """
        if not self.enabled:
            return False
        
        if self.sample_rate >= 1.0:
            return True
        
        with self._tick_counter_lock:
            self._tick_counter += 1
            # Детерминированный сэмплинг: каждый N-й тик
            sample_interval = max(1, int(1.0 / self.sample_rate))
            return (self._tick_counter % sample_interval) == 0
    
    def start_trace(self, trace_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Начать новый трейс.
        
        Args:
            trace_id: Уникальный ID трейса (e.g., tick_12345)
            metadata: Дополнительные метаданные (e.g., {"symbols": ["BTCUSDT", "ETHUSDT"]})
        """
        if not self.enabled:
            return
        
        trace = Trace(
            trace_id=trace_id,
            start_ns=time.monotonic_ns(),
            metadata=metadata or {}
        )
        
        self._local.current_trace = trace
    
    def finish_trace(self) -> Optional[Trace]:
        """
        Завершить текущий трейс.
        
        Returns:
            Завершённый трейс или None, если трейсинг выключен
        """
        if not self.enabled:
            return None
        
        trace = getattr(self._local, 'current_trace', None)
        if not trace:
            return None
        
        trace.finish()
        
        # Сохранить в accumulated traces
        with self._traces_lock:
            self._traces.append(trace)
        
        # Очистить thread-local
        self._local.current_trace = None
        
        return trace
    
    @contextmanager
    def span(self, name: str):
        """
        Context manager для измерения стадии.
        
        Usage:
            with tracer.span("stage_fetch_md"):
                fetch_market_data()
        
        Args:
            name: Название стадии (e.g., "stage_fetch_md")
        """
        if not self.enabled:
            yield
            return
        
        trace = getattr(self._local, 'current_trace', None)
        if not trace:
            yield
            return
        
        # Start span
        overhead_start = time.monotonic_ns()
        span_obj = Span(name=name, start_ns=time.monotonic_ns())
        overhead_ns = time.monotonic_ns() - overhead_start
        
        try:
            yield span_obj
        finally:
            # Finish span
            overhead_start = time.monotonic_ns()
            span_obj.finish()
            trace.spans.append(span_obj)
            overhead_ns += time.monotonic_ns() - overhead_start
            
            # Track overhead
            self._overhead_ns += overhead_ns
            self._overhead_samples += 1
    
    def get_traces(self, clear: bool = True) -> List[Trace]:
        """
        Получить accumulated traces.
        
        Args:
            clear: Очистить буфер после получения
        
        Returns:
            List of traces
        """
        with self._traces_lock:
            traces = list(self._traces)
            if clear:
                self._traces.clear()
        
        return traces
    
    def compute_percentiles(self, stage: str, percentiles: List[float] = [0.5, 0.95, 0.99]) -> Dict[float, float]:
        """
        Вычислить перцентили для стадии.
        
        Args:
            stage: Название стадии (e.g., "stage_fetch_md")
            percentiles: List of percentiles (e.g., [0.5, 0.95, 0.99])
        
        Returns:
            {percentile: duration_ms}
        """
        traces = self.get_traces(clear=False)
        
        # Собрать все durations для стадии
        durations = []
        for trace in traces:
            for span in trace.spans:
                if span.name == stage:
                    durations.append(span.duration_ms)
        
        if not durations:
            return {p: 0.0 for p in percentiles}
        
        durations.sort()
        
        result = {}
        for p in percentiles:
            idx = int(len(durations) * p)
            if idx >= len(durations):
                idx = len(durations) - 1
            result[p] = durations[idx]
        
        return result
    
    def get_overhead_pct(self) -> float:
        """
        Получить overhead трейсинга в процентах.
        
        Returns:
            Overhead percentage (should be ≤3%)
        """
        if self._overhead_samples == 0:
            return 0.0
        
        traces = self.get_traces(clear=False)
        if not traces:
            return 0.0
        
        # Total traced time
        total_traced_ns = sum(trace.end_ns - trace.start_ns for trace in traces if trace.end_ns > 0)
        
        if total_traced_ns == 0:
            return 0.0
        
        overhead_pct = (self._overhead_ns / total_traced_ns) * 100
        return overhead_pct
    
    def export_to_json(self, trace: Trace) -> Dict[str, Any]:
        """
        Экспорт трейса в JSON (ASCII-only, детерминированный).
        
        Args:
            trace: Trace для экспорта
        
        Returns:
            JSON-serializable dict
        """
        return {
            "trace_id": trace.trace_id,
            "duration_ms": trace.total_duration_ms(),
            "metadata": trace.metadata,
            "spans": [
                {
                    "name": span.name,
                    "duration_ms": span.duration_ms
                }
                for span in trace.spans
            ],
            "stage_durations": trace.get_stage_durations()
        }


# Global tracer instance (configurable via config)
_global_tracer: Optional[PerformanceTracer] = None


def get_tracer() -> PerformanceTracer:
    """Get global tracer instance."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = PerformanceTracer(enabled=False)
    return _global_tracer


def init_tracer(enabled: bool = True, sample_rate: float = 1.0) -> PerformanceTracer:
    """
    Initialize global tracer.
    
    Args:
        enabled: Enable tracing
        sample_rate: Sampling rate (0.0-1.0)
    
    Returns:
        Tracer instance
    """
    global _global_tracer
    _global_tracer = PerformanceTracer(enabled=enabled, sample_rate=sample_rate)
    return _global_tracer
