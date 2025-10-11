"""
AB-Testing Harness for spread/queue calibration.

Features:
- Symbol routing: A (baseline) / B (candidate)
- Per-bucket metrics tracking
- Safety gates with auto-rollback
- Results logging to artifacts/edge/reports/ab_run_*.md
"""
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime
import threading
import statistics

logger = logging.getLogger(__name__)


@dataclass
class ABBucketMetrics:
    """Metrics for an AB bucket (A or B)."""
    bucket_id: str  # "A" or "B"
    
    # Core metrics (rolling window)
    net_bps_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    slippage_bps_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    fill_rate_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    taker_share_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    tick_total_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    deadline_miss_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    # Aggregates (last 10 minutes)
    net_bps_10m: List[float] = field(default_factory=list)
    slippage_bps_10m: List[float] = field(default_factory=list)
    
    # Counters
    total_ticks: int = 0
    total_fills: int = 0
    total_quotes: int = 0
    
    # Timestamps
    first_seen_ms: int = 0
    last_updated_ms: int = 0


@dataclass
class ABSafetyGate:
    """Safety gate configuration."""
    name: str
    metric: str  # "slippage_bps", "taker_share", "tick_total_p95", "deadline_miss_rate"
    threshold: float  # Absolute threshold or relative delta
    relative: bool = True  # If True, threshold is relative to baseline (B - A)
    duration_sec: int = 600  # How long degradation must persist (10 minutes)
    enabled: bool = True


class ABHarness:
    """
    AB-testing harness with safety gates.
    
    Routes symbols to buckets A (baseline) or B (candidate).
    Tracks metrics per bucket and triggers auto-rollback if safety gates fire.
    """
    
    def __init__(
        self,
        mode: str = "dry",  # "dry" or "online"
        split_pct: float = 0.5,  # Percentage of symbols to route to B
        safety_gates: Optional[List[ABSafetyGate]] = None,
        reports_dir: str = "artifacts/edge/reports",
        whitelist: Optional[Set[str]] = None,
        blacklist: Optional[Set[str]] = None
    ):
        """
        Initialize AB harness.
        
        Args:
            mode: "dry" (shadow mode) or "online" (live routing)
            split_pct: Percentage of symbols to route to bucket B
            safety_gates: List of safety gate configurations
            reports_dir: Directory for AB reports
            whitelist: If set, only these symbols can be routed to B
            blacklist: If set, these symbols will never be routed to B
        """
        self.mode = mode
        self.split_pct = split_pct
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.whitelist = whitelist or set()
        self.blacklist = blacklist or set()
        
        # Safety gates
        if safety_gates is None:
            # Default safety gates
            self.safety_gates = [
                ABSafetyGate(
                    name="slippage_degradation",
                    metric="slippage_bps",
                    threshold=0.0,  # Any increase
                    relative=True,
                    duration_sec=600
                ),
                ABSafetyGate(
                    name="taker_share_increase",
                    metric="taker_share",
                    threshold=0.01,  # +1 percentage point
                    relative=True,
                    duration_sec=600
                ),
                ABSafetyGate(
                    name="latency_regression",
                    metric="tick_total_p95",
                    threshold=0.10,  # +10%
                    relative=True,
                    duration_sec=600
                ),
                ABSafetyGate(
                    name="deadline_miss_spike",
                    metric="deadline_miss_rate",
                    threshold=0.02,  # 2% absolute
                    relative=False,
                    duration_sec=600
                )
            ]
        else:
            self.safety_gates = safety_gates
        
        # Symbol routing: symbol -> bucket_id ("A" or "B")
        self._symbol_routing: Dict[str, str] = {}
        
        # Bucket metrics
        self._bucket_metrics: Dict[str, ABBucketMetrics] = {
            "A": ABBucketMetrics(bucket_id="A"),
            "B": ABBucketMetrics(bucket_id="B")
        }
        
        # Safety gate state
        self._gate_violations: Dict[str, List[int]] = defaultdict(list)  # gate_name -> [ts, ts, ...]
        self._rollback_triggered = False
        
        self._lock = threading.Lock()
        
        logger.info(
            f"[AB_HARNESS] Initialized: mode={mode}, split_pct={split_pct}, "
            f"gates={len(self.safety_gates)}"
        )
    
    def assign_symbols(self, symbols: List[str]) -> Dict[str, str]:
        """
        Assign symbols to buckets A or B.
        
        Args:
            symbols: List of symbols to assign
        
        Returns:
            Dict mapping symbol -> bucket_id
        """
        with self._lock:
            # Deterministic assignment based on hash
            for symbol in symbols:
                # Check blacklist
                if self.blacklist and symbol in self.blacklist:
                    self._symbol_routing[symbol] = "A"
                    continue
                
                # Check whitelist
                if self.whitelist and symbol not in self.whitelist:
                    self._symbol_routing[symbol] = "A"
                    continue
                
                # Hash-based assignment
                symbol_hash = hash(symbol)
                if (symbol_hash % 100) < (self.split_pct * 100):
                    self._symbol_routing[symbol] = "B"
                else:
                    self._symbol_routing[symbol] = "A"
            
            logger.info(
                f"[AB_HARNESS] Assigned {len(symbols)} symbols: "
                f"A={sum(1 for b in self._symbol_routing.values() if b == 'A')}, "
                f"B={sum(1 for b in self._symbol_routing.values() if b == 'B')}"
            )
            
            return dict(self._symbol_routing)
    
    def get_bucket(self, symbol: str) -> str:
        """
        Get bucket assignment for symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Bucket ID ("A" or "B")
        """
        with self._lock:
            # If rollback triggered, route everything to A
            if self._rollback_triggered:
                return "A"
            
            return self._symbol_routing.get(symbol, "A")
    
    def record_tick(
        self,
        symbol: str,
        net_bps: Optional[float] = None,
        slippage_bps: Optional[float] = None,
        fill_rate: Optional[float] = None,
        taker_share: Optional[float] = None,
        tick_total_ms: Optional[float] = None,
        deadline_miss: bool = False
    ) -> None:
        """
        Record metrics for a tick.
        
        Args:
            symbol: Trading symbol
            net_bps: Net P&L in bps
            slippage_bps: Slippage in bps
            fill_rate: Fill rate (0.0-1.0)
            taker_share: Taker fills percentage (0.0-1.0)
            tick_total_ms: Total tick time (ms)
            deadline_miss: True if deadline was missed
        """
        with self._lock:
            bucket_id = self.get_bucket(symbol)
            metrics = self._bucket_metrics[bucket_id]
            
            now_ms = int(time.time() * 1000)
            
            # Update samples
            if net_bps is not None:
                metrics.net_bps_samples.append(net_bps)
                metrics.net_bps_10m.append((now_ms, net_bps))
            
            if slippage_bps is not None:
                metrics.slippage_bps_samples.append(slippage_bps)
                metrics.slippage_bps_10m.append((now_ms, slippage_bps))
            
            if fill_rate is not None:
                metrics.fill_rate_samples.append(fill_rate)
            
            if taker_share is not None:
                metrics.taker_share_samples.append(taker_share)
            
            if tick_total_ms is not None:
                metrics.tick_total_samples.append(tick_total_ms)
            
            if deadline_miss:
                metrics.deadline_miss_samples.append(1.0)
            else:
                metrics.deadline_miss_samples.append(0.0)
            
            # Update counters
            metrics.total_ticks += 1
            metrics.last_updated_ms = now_ms
            
            # Trim 10m windows (keep last 10 minutes only)
            cutoff_ms = now_ms - 600_000  # 10 minutes
            metrics.net_bps_10m = [(ts, val) for ts, val in metrics.net_bps_10m if ts > cutoff_ms]
            metrics.slippage_bps_10m = [(ts, val) for ts, val in metrics.slippage_bps_10m if ts > cutoff_ms]
    
    def check_safety_gates(self) -> Tuple[bool, List[str]]:
        """
        Check all safety gates.
        
        Returns:
            (should_rollback, violated_gates)
        """
        with self._lock:
            if self._rollback_triggered:
                return True, []
            
            violated_gates = []
            now_ms = int(time.time() * 1000)
            
            for gate in self.safety_gates:
                if not gate.enabled:
                    continue
                
                # Check gate condition
                violated = self._check_gate(gate)
                
                if violated:
                    # Record violation
                    self._gate_violations[gate.name].append(now_ms)
                    
                    # Trim old violations (outside duration window)
                    cutoff_ms = now_ms - (gate.duration_sec * 1000)
                    self._gate_violations[gate.name] = [
                        ts for ts in self._gate_violations[gate.name] if ts > cutoff_ms
                    ]
                    
                    # Check if violation persisted for duration
                    violation_count = len(self._gate_violations[gate.name])
                    # Heuristic: need at least 5 violations in window
                    if violation_count >= 5:
                        violated_gates.append(gate.name)
                        logger.warning(
                            f"[AB_HARNESS] Safety gate '{gate.name}' violated: "
                            f"{violation_count} violations in {gate.duration_sec}s"
                        )
            
            # Trigger rollback if any gate violated
            if violated_gates:
                self._rollback_triggered = True
                logger.error(
                    f"[AB_HARNESS] ROLLBACK TRIGGERED: gates={violated_gates}"
                )
                return True, violated_gates
            
            return False, []
    
    def _check_gate(self, gate: ABSafetyGate) -> bool:
        """
        Check if a single gate is violated.
        
        Args:
            gate: Safety gate configuration
        
        Returns:
            True if gate is violated
        """
        metrics_a = self._bucket_metrics["A"]
        metrics_b = self._bucket_metrics["B"]
        
        # Get metric values
        if gate.metric == "slippage_bps":
            val_a = statistics.mean(metrics_a.slippage_bps_samples) if metrics_a.slippage_bps_samples else 0.0
            val_b = statistics.mean(metrics_b.slippage_bps_samples) if metrics_b.slippage_bps_samples else 0.0
        elif gate.metric == "taker_share":
            val_a = statistics.mean(metrics_a.taker_share_samples) if metrics_a.taker_share_samples else 0.0
            val_b = statistics.mean(metrics_b.taker_share_samples) if metrics_b.taker_share_samples else 0.0
        elif gate.metric == "tick_total_p95":
            val_a = statistics.quantiles(metrics_a.tick_total_samples, n=20)[18] if len(metrics_a.tick_total_samples) > 20 else 0.0
            val_b = statistics.quantiles(metrics_b.tick_total_samples, n=20)[18] if len(metrics_b.tick_total_samples) > 20 else 0.0
        elif gate.metric == "deadline_miss_rate":
            val_a = statistics.mean(metrics_a.deadline_miss_samples) if metrics_a.deadline_miss_samples else 0.0
            val_b = statistics.mean(metrics_b.deadline_miss_samples) if metrics_b.deadline_miss_samples else 0.0
        else:
            logger.warning(f"[AB_HARNESS] Unknown metric: {gate.metric}")
            return False
        
        # Check threshold
        if gate.relative:
            # Relative: check if B is worse than A by threshold
            delta = val_b - val_a
            return delta > gate.threshold
        else:
            # Absolute: check if B exceeds threshold
            return val_b > gate.threshold
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary for both buckets."""
        with self._lock:
            summary = {}
            
            for bucket_id, metrics in self._bucket_metrics.items():
                bucket_summary = {
                    "total_ticks": metrics.total_ticks,
                    "net_bps_mean": statistics.mean(metrics.net_bps_samples) if metrics.net_bps_samples else 0.0,
                    "slippage_bps_mean": statistics.mean(metrics.slippage_bps_samples) if metrics.slippage_bps_samples else 0.0,
                    "fill_rate_mean": statistics.mean(metrics.fill_rate_samples) if metrics.fill_rate_samples else 0.0,
                    "taker_share_mean": statistics.mean(metrics.taker_share_samples) if metrics.taker_share_samples else 0.0,
                    "tick_total_p95": statistics.quantiles(metrics.tick_total_samples, n=20)[18] if len(metrics.tick_total_samples) > 20 else 0.0,
                    "deadline_miss_rate": statistics.mean(metrics.deadline_miss_samples) if metrics.deadline_miss_samples else 0.0
                }
                summary[bucket_id] = bucket_summary
            
            # Add deltas (B - A)
            if "A" in summary and "B" in summary:
                summary["delta"] = {
                    "net_bps": summary["B"]["net_bps_mean"] - summary["A"]["net_bps_mean"],
                    "slippage_bps": summary["B"]["slippage_bps_mean"] - summary["A"]["slippage_bps_mean"],
                    "fill_rate": summary["B"]["fill_rate_mean"] - summary["A"]["fill_rate_mean"],
                    "taker_share": summary["B"]["taker_share_mean"] - summary["A"]["taker_share_mean"],
                    "tick_total_p95": summary["B"]["tick_total_p95"] - summary["A"]["tick_total_p95"],
                    "deadline_miss_rate": summary["B"]["deadline_miss_rate"] - summary["A"]["deadline_miss_rate"]
                }
            
            summary["rollback_triggered"] = self._rollback_triggered
            summary["symbol_routing"] = {
                "A": sum(1 for b in self._symbol_routing.values() if b == "A"),
                "B": sum(1 for b in self._symbol_routing.values() if b == "B")
            }
            
            return summary
    
    def export_report(self, run_id: Optional[str] = None) -> Path:
        """
        Export AB test report to markdown.
        
        Args:
            run_id: Optional run ID (default: timestamp)
        
        Returns:
            Path to report file
        """
        if run_id is None:
            run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        filename = f"ab_run_{run_id}.md"
        filepath = self.reports_dir / filename
        
        summary = self.get_metrics_summary()
        
        # Build markdown report
        lines = []
        lines.append(f"# AB Test Report: {run_id}")
        lines.append("")
        lines.append(f"**Generated**: {datetime.utcnow().isoformat()}Z")
        lines.append(f"**Mode**: {self.mode}")
        lines.append(f"**Split**: {self.split_pct * 100:.1f}% to B")
        lines.append(f"**Rollback Triggered**: {'✗ YES' if self._rollback_triggered else '✓ NO'}")
        lines.append("")
        
        lines.append("## Symbol Routing")
        lines.append("")
        lines.append(f"- Bucket A: {summary['symbol_routing']['A']} symbols")
        lines.append(f"- Bucket B: {summary['symbol_routing']['B']} symbols")
        lines.append("")
        
        lines.append("## Metrics Comparison")
        lines.append("")
        lines.append("| Metric | Bucket A | Bucket B | Delta (B - A) | Result |")
        lines.append("|--------|----------|----------|---------------|--------|")
        
        # Net BPS
        net_a = summary["A"]["net_bps_mean"]
        net_b = summary["B"]["net_bps_mean"]
        net_delta = summary["delta"]["net_bps"]
        net_result = "✓" if net_delta >= 0 else "✗"
        lines.append(f"| Net BPS | {net_a:.4f} | {net_b:.4f} | {net_delta:+.4f} | {net_result} |")
        
        # Slippage BPS
        slip_a = summary["A"]["slippage_bps_mean"]
        slip_b = summary["B"]["slippage_bps_mean"]
        slip_delta = summary["delta"]["slippage_bps"]
        slip_result = "✓" if slip_delta <= 0 else "✗"
        lines.append(f"| Slippage BPS | {slip_a:.4f} | {slip_b:.4f} | {slip_delta:+.4f} | {slip_result} |")
        
        # Fill Rate
        fill_a = summary["A"]["fill_rate_mean"]
        fill_b = summary["B"]["fill_rate_mean"]
        fill_delta = summary["delta"]["fill_rate"]
        fill_result = "✓" if fill_delta >= 0 else "✗"
        lines.append(f"| Fill Rate | {fill_a:.4f} | {fill_b:.4f} | {fill_delta:+.4f} | {fill_result} |")
        
        # Taker Share
        taker_a = summary["A"]["taker_share_mean"]
        taker_b = summary["B"]["taker_share_mean"]
        taker_delta = summary["delta"]["taker_share"]
        taker_result = "✓" if taker_delta <= 0 else "✗"
        lines.append(f"| Taker Share | {taker_a:.4f} | {taker_b:.4f} | {taker_delta:+.4f} | {taker_result} |")
        
        # Tick Total P95
        tick_a = summary["A"]["tick_total_p95"]
        tick_b = summary["B"]["tick_total_p95"]
        tick_delta = summary["delta"]["tick_total_p95"]
        tick_result = "✓" if tick_delta <= 0 else "✗"
        lines.append(f"| Tick Total P95 (ms) | {tick_a:.2f} | {tick_b:.2f} | {tick_delta:+.2f} | {tick_result} |")
        
        # Deadline Miss Rate
        dm_a = summary["A"]["deadline_miss_rate"]
        dm_b = summary["B"]["deadline_miss_rate"]
        dm_delta = summary["delta"]["deadline_miss_rate"]
        dm_result = "✓" if dm_delta <= 0 else "✗"
        lines.append(f"| Deadline Miss Rate | {dm_a:.4f} | {dm_b:.4f} | {dm_delta:+.4f} | {dm_result} |")
        
        lines.append("")
        
        # Safety gates
        lines.append("## Safety Gates")
        lines.append("")
        for gate in self.safety_gates:
            status = "ENABLED" if gate.enabled else "DISABLED"
            violations = len(self._gate_violations.get(gate.name, []))
            lines.append(f"- **{gate.name}**: {status}, Violations: {violations}")
        
        lines.append("")
        
        # Write report
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        logger.info(f"[AB_HARNESS] Exported report to {filepath}")
        
        return filepath

