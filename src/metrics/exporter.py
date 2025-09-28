"""
Prometheus metrics exporter for market making bot.

Production-ready with:
- Exact metric names/labels matching requirements
- DI-based design using AppContext
- No global singletons
- Helper methods for common updates
"""

import time
import threading
from collections import deque
from typing import Dict, Optional, Tuple, Any, Iterable

from prometheus_client import Counter, Gauge, Histogram

from src.common.config import AppConfig
from src.metrics.position_skew import PositionSkewMetricsWriter
from src.metrics.intraday_caps import IntradayCapsMetricsWriter
from src.common.di import AppContext
from src.common.fees import expected_tier, distance_to_next_tier, effective_fee_bps, BYBIT_SPOT_TIERS, FeeTier
from src.metrics.fee_tier import FeeTierMetricsWriter
from src.common.version import VERSION, get_git_sha_short, get_mode, get_env, utc_now_str


class RateLimitedLogger:
    """Rate-limited logger to avoid spam."""
    
    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self.last_log = {}
    
    def warn_once(self, message: str):
        """Log a warning message at most once per interval."""
        now = time.time()
        if message not in self.last_log or (now - self.last_log[message]) >= self.interval:
            print(f"METRICS WARNING: {message}")
            self.last_log[message] = now


class Metrics:
    @staticmethod
    def _finite(x: float) -> float:
        try:
            import math
            if x is None:
                return 0.0
            xx = float(x)
            if math.isfinite(xx):
                return xx
            return 0.0
        except Exception:
            return 0.0
    """Production-ready metrics with exact names/labels; no globals."""
    
    def __init__(self, ctx: AppContext):
        """Initialize metrics with AppContext."""
        self.ctx = ctx
        self._rate_logger = RateLimitedLogger()
        self._pm_lock = threading.Lock()
        # Position skew writer (low-cardinality)
        self._pos_skew = PositionSkewMetricsWriter(self)
        self._caps = IntradayCapsMetricsWriter(self)
        self._fees = FeeTierMetricsWriter(self)
        
        # Flow metrics - EXACT names/labels
        self.orders_active = Gauge('orders_active', 'Active orders by symbol and side', ['symbol', 'side'])
        self.creates_total = Counter('creates_total', 'Total orders created', ['symbol'])
        self.cancels_total = Counter('cancels_total', 'Total orders cancelled', ['symbol'])
        self.replaces_total = Counter('replaces_total', 'Total orders replaced/amended', ['symbol'])
        self.quotes_placed_total = Counter('quotes_placed_total', 'Total quotes placed', ['symbol'])
        
        # NEW: Reliability metrics - EXACT names/labels
        self.amend_attempts_total = Counter('amend_attempts_total', 'Total amend attempts', ['symbol', 'side'])
        self.amend_success_total = Counter('amend_success_total', 'Total successful amends', ['symbol', 'side'])
        self.reconcile_actions_total = Counter('reconcile_actions_total', 'Total reconciliation actions', ['action'])
        self.backoff_seconds_sum = Counter('backoff_seconds_sum', 'Total backoff time in seconds')
        self.circuit_breaker_state = Gauge('circuit_breaker_state', 'Circuit breaker state (0=closed, 1=open)')
        
        # Rate metrics (computed from timestamps)
        self.create_rate = Gauge('create_rate', 'Orders created per second', ['symbol'])
        self.cancel_rate = Gauge('cancel_rate', 'Orders cancelled per second', ['symbol'])
        
        # Queue position metrics
        self.queue_pos_delta = Gauge('queue_pos_delta', 'Queue position delta (positive = improved)', ['symbol', 'side'])
        
        # P&L and fees
        self.maker_pnl = Gauge('maker_pnl', 'Maker P&L in USD', ['symbol'])
        self.taker_fees = Gauge('taker_fees', 'Taker fees paid in USD', ['symbol'])
        self.inventory_abs = Gauge('inventory_abs', 'Absolute inventory value in USD', ['symbol'])
        
        # Latency histograms - EXACT stage values: "md", "rest", "ws"
        self.latency_ms = Histogram('latency_ms', 'Latency in milliseconds', ['stage'])
        
        # Exchange connectivity
        self.ws_reconnects_total = Gauge('ws_reconnects_total', 'WebSocket reconnections', ['exchange'])
        self.rest_error_rate = Gauge('rest_error_rate', 'REST API error rate', ['exchange'])
        
        # Risk metrics
        self.risk_paused = Gauge('risk_paused', 'Risk management paused (0/1)')
        self.drawdown_day = Gauge('drawdown_day', 'Daily drawdown percentage')
        
        # Portfolio metrics
        self.portfolio_weight = Gauge('portfolio_weight', 'Portfolio weight by symbol', ['symbol'])
        self.portfolio_target_usd = Gauge('portfolio_target_usd', 'Portfolio target USD by symbol', ['symbol'])
        self.portfolio_active_usd = Gauge('portfolio_active_usd', 'Portfolio active USD by symbol', ['symbol'])
        self.portfolio_active_levels = Gauge('portfolio_active_levels', 'Portfolio active levels by symbol and side', ['symbol', 'side'])
        self.allocator_last_update_ts = Gauge('allocator_last_update_ts', 'Portfolio allocator last update timestamp')
        self.portfolio_budget_available_usd = Gauge('portfolio_budget_available_usd', 'Available portfolio budget in USD')
        self.portfolio_drawdown_pct = Gauge('portfolio_drawdown_pct', 'Portfolio drawdown percent (0..1)')
        self.allocator_soft_factor = Gauge('allocator_soft_factor', 'Allocator soft factor (0..1)')
        self.allocator_hwm_equity_usd = Gauge('allocator_hwm_equity_usd', 'Allocator HWM equity in USD')
        # Allocator micro smoothing metrics
        self.allocator_backoff_level = Gauge('allocator_backoff_level', 'Allocator backoff level', ['symbol'])
        self.allocator_delta_capped_total = Counter('allocator_delta_capped_total', 'Sum of absolute capped deltas', ['symbol'])
        self.allocator_sizing_delta_ratio = Gauge('allocator_sizing_delta_ratio', 'Abs(delta_capped)/max(1,Abs(current))', ['symbol'])
        # MICRO_SIGNALS
        self.micro_bias_strength = Gauge('micro_bias_strength', 'Per-symbol micro bias strength', ['symbol'])
        self.adverse_fill_rate = Gauge('adverse_fill_rate', 'Per-symbol adverse fill rate (5-tick)', ['symbol'])
        # HA leader/idempotency metrics (low-cardinality)
        self.leader_state = Gauge('leader_state', 'Leader state (1=leader,0=follower)', ['env','service','instance'])
        self.leader_elections_total = Counter('leader_elections_total', 'Leader elections total', ['env','service'])
        self.leader_renew_fail_total = Counter('leader_renew_fail_total', 'Leader renew failures total', ['env','service'])
        self.order_idem_hits_total = Counter('order_idem_hits_total', 'Order idempotency hits total', ['env','service','op'])
        
        # Anti-stale order guard metrics
        self.order_age_ms_bucket_total = Counter('order_age_ms_bucket_total', 'Total order age in milliseconds by bucket', ['symbol', 'bucket'])
        self.stale_cancels_total = Counter('stale_cancels_total', 'Total stale orders cancelled', ['symbol', 'reason'])
        self.refresh_amends_total = Counter('refresh_amends_total', 'Total orders refreshed via amend', ['symbol', 'reason'])
        
        # Latency Boost metrics (low-cardinality)
        self.replace_rate_per_min = Gauge('replace_rate_per_min', 'Replace operations per minute', ['symbol'])
        self.cancel_batch_events_total = Counter('cancel_batch_events_total', 'Batch cancel events total', ['symbol'])
        self.order_age_p95_ms = Gauge('order_age_p95_ms', 'Order age p95 in ms', ['symbol'])

        # SIM-only metrics
        if get_mode() == 'sim':
            self.sim_replaced_total = Counter('sim_replaced_total', 'Sim: replaced total', ['symbol'])
            self.sim_canceled_total = Counter('sim_canceled_total', 'Sim: canceled total', ['symbol'])
            self.sim_fills_total = Counter('sim_fills_total', 'Sim: fills total', ['symbol'])
            self.sim_taker_share_pct = Gauge('sim_taker_share_pct', 'Sim: taker share percent', ['symbol'])
            self.sim_net_bps = Gauge('sim_net_bps', 'Sim: net bps', ['symbol'])
            self.sim_order_age_p95_ms = Gauge('sim_order_age_p95_ms', 'Sim: order age p95 ms', ['symbol'])
        
        # Cost/slippage allocator metrics (L6)
        self.allocator_estimated_cost_bps = Gauge('allocator_estimated_cost_bps', 'Estimated full cost (fee+slippage) in bps', ['symbol'])
        self.allocator_cost_attenuation = Gauge('allocator_cost_attenuation', 'Allocator cost attenuation factor (0..1)', ['symbol'])
        self.allocator_cost_inputs_spread_bps = Gauge('allocator_cost_inputs_spread_bps', 'Allocator cost input: spread bps (from shadow/metrics)', ['symbol'])
        self.allocator_cost_inputs_volume_usd = Gauge('allocator_cost_inputs_volume_usd', 'Allocator cost input: volume USD (from shadow/metrics)', ['symbol'])
        self.allocator_cost_slippage_bps = Gauge('allocator_cost_slippage_bps', 'Allocator computed slippage bps', ['symbol'])
        # L6.3 visibility
        self.allocator_fillrate_attenuation = Gauge('allocator_fillrate_attenuation', 'Allocator fill-rate attenuation factor (0..1)', ['symbol'])
        # L6.2: Online cost calibration (per symbol)
        self.cost_calib_samples_total = Counter('cost_calib_samples_total', 'Cost calibration samples total', ['symbol'])
        self.cost_calib_spread_ewma_bps = Gauge('cost_calib_spread_ewma_bps', 'Cost calibration spread EWMA (bps)', ['symbol'])
        self.cost_calib_volume_ewma_usd = Gauge('cost_calib_volume_ewma_usd', 'Cost calibration volume EWMA (USD)', ['symbol'])
        self.cost_calib_slippage_ewma_bps = Gauge('cost_calib_slippage_ewma_bps', 'Cost calibration slippage EWMA (bps)', ['symbol'])
        self.cost_calib_k_eff = Gauge('cost_calib_k_eff', 'Calibrated k (bps per kUSD)', ['symbol'])
        self.cost_calib_cap_eff_bps = Gauge('cost_calib_cap_eff_bps', 'Calibrated slippage cap (bps)', ['symbol'])
        # Scheduler metrics
        self.scheduler_open = Gauge('scheduler_open', '1 if open else 0')
        self.scheduler_window = Gauge('scheduler_window', 'Active window flag', ['name'])
        self.scheduler_cooldown_active = Gauge('scheduler_cooldown_active', '1 if cooldown active else 0')
        self.scheduler_next_change_ts = Gauge('scheduler_next_change_ts', 'Unix ts of next change')
        self.scheduler_seconds_to_change = Gauge('scheduler_seconds_to_change', 'Seconds to next change')
        self.scheduler_transitions_total = Counter('scheduler_transitions_total', 'Scheduler state transitions', ['state'])
        self.scheduler_reload_total = Counter('scheduler_reload_total', 'Scheduler reloads applied')
        # Per-symbol scheduler metrics
        self.scheduler_open_by_symbol = Gauge('scheduler_open_by_symbol', 'ToD open flag per symbol', ['symbol'])
        self.scheduler_cooldown_by_symbol = Gauge('scheduler_cooldown_by_symbol', 'ToD cooldown flag per symbol', ['symbol'])

        # Runtime guard metrics
        self.guard_paused = Gauge('guard_paused', '1 if runtime guard paused else 0')
        self.guard_breach_streak = Gauge('guard_breach_streak', 'current consecutive breach count')
        self.guard_pauses_total = Counter('guard_pauses_total', 'Total pauses triggered')
        self.guard_reload_total = Counter('guard_reload_total', 'Guard reloads applied')
        self.guard_cancels_total = Counter('guard_cancels_total', 'Orders cancelled due to pause')
        self.guard_last_reason = Gauge('guard_last_reason', 'Bitmask of last pause reason')
        self.guard_last_change_ts = Gauge('guard_last_change_ts', 'Unix ts of last guard state change')
        self.guard_dry_run = Gauge('guard_dry_run', '1 if guard in dry_run else 0')
        self.guard_manual_override = Gauge('guard_manual_override', '1 if manual override pause else 0')
        self.guard_paused_effective = Gauge('guard_paused_effective', '1 if effective pause (manual or paused&&!dry_run) else 0')
        
        # Throttle metrics (L4)
        self.throttle_creates_in_window = Gauge('throttle_creates_in_window', 'Creates in current window', ['symbol'])
        self.throttle_amends_in_window = Gauge('throttle_amends_in_window', 'Amends in current window', ['symbol'])
        self.throttle_cancels_in_window = Gauge('throttle_cancels_in_window', 'Cancels in current window', ['symbol'])
        self.throttle_backoff_ms = Gauge('throttle_backoff_ms', 'Current backoff delay ms', ['symbol'])
        self.throttle_backoffs_total = Counter('throttle_backoffs_total', 'Total backoffs applied')
        self.throttle_events_in_window = Gauge('throttle_events_in_window', 'Events in sliding window', ['op', 'symbol'])
        self.throttle_backoff_ms_max = Gauge('throttle_backoff_ms_max', 'Max observed backoff over run')
        # AutoPolicy
        self.autopolicy_active = Gauge('autopolicy_active', '1 if autopolicy active else 0')
        self.autopolicy_level = Gauge('autopolicy_level', 'Current autopolicy level')
        self.autopolicy_steps_total = Counter('autopolicy_steps_total', 'Autopolicy level changes total')
        self.autopolicy_last_change_ts = Gauge('autopolicy_last_change_ts', 'Unix ts of last level change')
        self.autopolicy_min_time_in_book_ms_eff = Gauge('autopolicy_min_time_in_book_ms_eff', 'Effective min_time_in_book_ms')
        self.autopolicy_replace_threshold_bps_eff = Gauge('autopolicy_replace_threshold_bps_eff', 'Effective replace_threshold_bps')
        self.autopolicy_levels_per_side_max_eff = Gauge('autopolicy_levels_per_side_max_eff', 'Effective levels cap')
        # Circuit breaker
        self.circuit_state = Gauge('circuit_state', 'Circuit breaker state (1 for current state)', ['state'])
        self.circuit_open_total = Counter('circuit_open_total', 'Times circuit opened')
        self.circuit_half_open_probes = Gauge('circuit_half_open_probes', 'Remaining half-open probes')
        self.circuit_window_err_rate = Gauge('circuit_window_err_rate', 'Window error rate')
        self.circuit_window_5xx_rate = Gauge('circuit_window_5xx_rate', 'Window 5xx rate')
        self.circuit_window_429_rate = Gauge('circuit_window_429_rate', 'Window 429 rate')
        # Shadow mode
        self.shadow_orders_total = Counter('shadow_orders_total', 'Shadow orders emulated', ['symbol'])
        self.shadow_price_diff_bps_last = Gauge('shadow_price_diff_bps_last', 'Last price diff vs best (bps)', ['symbol'])
        self.shadow_price_diff_bps_avg = Gauge('shadow_price_diff_bps_avg', 'Avg price diff vs best (bps)', ['symbol'])
        self.shadow_size_diff_pct_last = Gauge('shadow_size_diff_pct_last', 'Last size diff vs best (%)', ['symbol'])
        self.shadow_size_diff_pct_avg = Gauge('shadow_size_diff_pct_avg', 'Avg size diff vs best (%)', ['symbol'])

        # Shadow aggregators (runtime-only, not exported as labels)
        # Fixed-point integers for determinism:
        # - price_diff_bps_sum_i: sum of price diffs in bps as integers
        # - size_diff_permille_sum_i: sum of size diffs in permille (pct*10) as integers
        # - count: number of samples
        self._shadow_sum_price_bps_i: Dict[str, int] = {}
        self._shadow_sum_size_permille_i: Dict[str, int] = {}
        self._shadow_count: Dict[str, int] = {}
        
        # Markout metrics - EXACT names/labels
        self.markout_up_total = Counter('markout_up_total', 'Total markout up events', ['horizon_ms', 'color', 'symbol'])
        self.markout_down_total = Counter('markout_down_total', 'Total markout down events', ['horizon_ms', 'color', 'symbol'])
        self.markout_avg_bps = Gauge('markout_avg_bps', 'Average markout in basis points', ['horizon_ms', 'color', 'symbol'])
        # M1.1 — Markout samples for gate evaluation
        self.markout_samples_total = Gauge('markout_samples_total', 'Total markout samples by horizon and color', ['horizon_ms', 'color'])
        # Portfolio budget state (in-memory)
        self._portfolio_budget_available_usd: float = 0.0
        self._portfolio_drawdown_pct: float = 0.0
        self._allocator_soft_factor: float = 1.0
        self._allocator_hwm_equity_usd: float = 0.0
        # L6 cost snapshot (per symbol caches for tests)
        self._allocator_cost_bps: Dict[str, float] = {}
        self._allocator_cost_atten: Dict[str, float] = {}
        self._allocator_cost_inputs_spread_bps: Dict[str, float] = {}
        self._allocator_cost_inputs_volume_usd: Dict[str, float] = {}
        self._allocator_cost_slippage_bps: Dict[str, float] = {}
        # L6.2 calibration internal state
        self._cost_calib_spread_ewma_bps: Dict[str, float] = {}
        self._cost_calib_volume_ewma_usd: Dict[str, float] = {}
        self._cost_calib_slippage_ewma_bps: Dict[str, float] = {}
        self._cost_calib_samples: Dict[str, int] = {}
        self._cost_calib_k_eff: Dict[str, float] = {}
        self._cost_calib_cap_eff_bps: Dict[str, float] = {}
        self._cost_calib_last_ts: Dict[str, float] = {}
        # Admin-applied overrides for calibration
        self._cal_override_k_eff: Dict[str, float] = {}
        self._cal_override_cap_eff_bps: Dict[str, float] = {}
        # Calibration runtime settings (hardened)
        self._calib_warmup_min_samples: int = 50
        self._calib_winsor_pct: float = 0.05
        self._calib_half_life_sec: float = 600.0
        self._calib_max_step_pct: float = 0.10
        # E3: internal perf state
        self._perf_latency_buckets_ms: Tuple[float, ...] = (
            0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, float('inf')
        )
        
        # Markout internal state (runtime-only, not exported as labels)
        # Fixed-point integers for determinism:
        # - markout_bps_sum_i: sum of markout values in bps as integers (price_diff_bps * 10000)
        # - count: number of samples
        self._markout_bps_sum_i: Dict[str, Dict[str, Dict[str, int]]] = {}  # horizon_ms -> color -> symbol -> sum
        self._markout_count: Dict[str, Dict[str, Dict[str, int]]] = {}  # horizon_ms -> color -> symbol -> count
        self._loop_hist_counts: Dict[str, Tuple[int, ...]] = {}
        self._admin_endpoint_bucket_counts: Dict[Tuple[str, str], int] = {}
        # L6.3 fill-rate internal state
        self._fillrate_ewma: Dict[str, float] = {}
        self._fillrate_last_ts: Dict[str, float] = {}
        self._fillrate_samples: Dict[str, int] = {}
        # L7 turnover state
        self._turnover_ewma_usd: Dict[str, float] = {}
        self._turnover_last_ts: Dict[str, float] = {}
        self._turnover_samples: Dict[str, int] = {}
        # Snapshot observability
        self.allocator_snapshot_writes_total = Counter('allocator_snapshot_writes_total', 'Allocator snapshot writes total')
        self.allocator_snapshot_writes_failed_total = Counter('allocator_snapshot_writes_failed_total', 'Allocator snapshot writes failed total')
        self.allocator_snapshot_loads_total = Counter('allocator_snapshot_loads_total', 'Allocator snapshot loads total')
        self.allocator_snapshot_loads_failed_total = Counter('allocator_snapshot_loads_failed_total', 'Allocator snapshot loads failed total')
        self.allocator_snapshot_mtime_seconds = Gauge('allocator_snapshot_mtime_seconds', 'Allocator snapshot last op unix ts', ['op'])
        self._allocator_last_write_ts: float = 0.0
        self._allocator_last_load_ts: float = 0.0
        # Throttle snapshot observability
        self.throttle_snapshot_writes_total = Counter('throttle_snapshot_writes_total', 'Throttle snapshot writes total')
        self.throttle_snapshot_writes_failed_total = Counter('throttle_snapshot_writes_failed_total', 'Throttle snapshot writes failed total')
        self.throttle_snapshot_loads_total = Counter('throttle_snapshot_loads_total', 'Throttle snapshot loads total')
        self.throttle_snapshot_loads_failed_total = Counter('throttle_snapshot_loads_failed_total', 'Throttle snapshot loads failed total')
        self.throttle_snapshot_mtime_seconds = Gauge('throttle_snapshot_mtime_seconds', 'Throttle snapshot last op unix ts', ['op'])
        self._throttle_last_write_ts: float = 0.0
        self._throttle_last_load_ts: float = 0.0
        # Rollout metrics
        self.rollout_orders_total = Counter('rollout_orders_total', 'Orders by rollout color', ['color'])
        self.rollout_traffic_split_pct = Gauge('rollout_traffic_split_pct', 'Traffic split percent routed to GREEN (0..100)')
        self.rollout_fills_total = Counter('rollout_fills_total', 'Order fills by rollout color', ['color'])
        self.rollout_rejects_total = Counter('rollout_rejects_total', 'Order rejects by rollout color', ['color'])
        self.rollout_avg_latency_ms = Gauge('rollout_avg_latency_ms', 'EWMA of order latency in ms by color', ['color'])
        self.rollout_pnl_usd = Gauge('rollout_pnl_usd', 'PnL in USD by rollout color', ['color'])
        self.rollout_split_observed_pct = Gauge('rollout_split_observed_pct', 'Observed percent of GREEN orders (0..100)')
        self.rollout_split_drift_alerts_total = Counter('rollout_split_drift_alerts_total', 'Total split drift alerts')
        # rollout internal aggregators
        self._rollout_latency_ewma: Dict[str, float] = {}
        self._rollout_fills: Dict[str, int] = {}
        self._rollout_rejects: Dict[str, int] = {}
        self._rollout_ewma_alpha: float = 0.3
        self._rollout_orders_count: Dict[str, int] = {}
        # Latency histogram buckets (ms) and quantiles (p95/p99)
        # Buckets are inclusive upper bounds; last bucket is +Inf sentinel
        self._latency_buckets_ms: Tuple[float, ...] = (
            0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, float('inf')
        )
        self.rollout_latency_bucket_total = Counter(
            'rollout_latency_bucket_total',
            'Latency histogram buckets by color (ms upper bound)',
            ['color', 'bucket_ms']
        )
        self.rollout_latency_p95_ms = Gauge('rollout_latency_p95_ms', 'p95 of rollout latency (ms) by color', ['color'])
        self.rollout_latency_p99_ms = Gauge('rollout_latency_p99_ms', 'p99 of rollout latency (ms) by color', ['color'])
        self.rollout_latency_samples_total = Gauge('rollout_latency_samples_total', 'Total latency samples by color', ['color'])
        # Latency SLO gauges/counters
        self.latency_slo_burn_rate = Gauge('latency_slo_burn_rate', 'Latency SLO burn rate', ['color', 'percentile'])
        self.latency_slo_budget_remaining = Gauge('latency_slo_budget_remaining', 'Latency SLO budget remaining', ['color', 'percentile'])
        self.latency_slo_alerts_total = Counter('latency_slo_alerts_total', 'Latency SLO alerts raised', ['percentile'])
        # E3: Perf/Soak micro-profiler
        self.loop_tick_ms = Gauge('loop_tick_ms', 'Last loop tick duration (ms)', ['loop'])
        self.loop_tick_cpu_ms = Gauge('loop_tick_cpu_ms', 'Last loop tick CPU time (ms)', ['loop'])
        self.loop_tick_p95_ms = Gauge('loop_tick_p95_ms', 'Loop tick p95 (ms)', ['loop'])
        self.loop_tick_p99_ms = Gauge('loop_tick_p99_ms', 'Loop tick p99 (ms)', ['loop'])
        self.event_loop_drift_ms = Gauge('event_loop_drift_ms', 'Max event-loop sleep drift (ms) over window')
        # E3.3 — Soak & leak guard gauges (stdlib-only)
        self.soak_mem_rss_bytes = Gauge('soak_mem_rss_bytes', 'Resident set size (bytes)')
        self.soak_open_fds = Gauge('soak_open_fds', 'Open file descriptors (0 on Windows)')
        self.soak_gc_gen = Gauge('soak_gc_gen', 'GC objects count per generation', ['gen'])
        self.soak_threads_total = Gauge('soak_threads_total', 'Total number of Python threads')
        self.event_loop_max_drift_ms = Gauge('event_loop_max_drift_ms', 'Max event-loop drift over window (ms)')
        self.admin_endpoint_latency_bucket_total = Counter('admin_endpoint_latency_bucket_total', 'Admin endpoint latency buckets (ms)', ['endpoint', 'bucket_ms'])
        # Snapshot integrity failures
        self.snapshot_integrity_fail_total = Counter('snapshot_integrity_fail_total', 'Snapshot integrity failures by kind', ['kind'])
        # Position skew low-cardinality metrics (no labels explosion)
        self.pos_skew_breach_total = Counter('pos_skew_breach_total', 'Position skew breach events total')
        self.pos_skew_last_ts = Gauge('pos_skew_last_ts', 'Unix ts of last position skew evaluation')
        self.pos_skew_symbol_breach_count = Gauge('pos_skew_symbol_breach_count', 'Count of symbols breaching per-symbol limit')
        self.pos_skew_color_breach = Gauge('pos_skew_color_breach', '1 if color breach, else 0')
        # pos_skew_abs gauge (env, service, symbol) — low cardinality
        self.pos_skew_abs = Gauge('pos_skew_abs', 'Absolute position skew (ratio, 0..inf)', ['env','service','symbol'])
        # Intraday caps gauges
        self.intraday_caps_pnl = Gauge('intraday_caps_pnl', 'Intraday cumulative PnL (base)')
        self.intraday_caps_turnover = Gauge('intraday_caps_turnover', 'Intraday cumulative turnover (USD)')
        self.intraday_caps_vol = Gauge('intraday_caps_vol', 'Intraday cumulative volatility measure (percent)')
        self.intraday_caps_breached = Gauge('intraday_caps_breached', 'Intraday caps breached (0/1)')
        # Fee tier metrics
        self.fee_tier_level = Gauge('fee_tier_level', 'Current fee tier level')
        self.fee_tier_expected_bps = Gauge('fee_tier_expected_bps', 'Expected baseline fee (bps)')
        self.fee_tier_distance_usd = Gauge('fee_tier_distance_usd', 'USD left to reach next tier')
        self.effective_fee_bps_now = Gauge('effective_fee_bps_now', 'Effective current fee (bps)')
        # Cost calibration snapshot counters (admin loader)
        self.cost_calib_snapshot_loads_total = Counter('cost_calib_snapshot_loads_total', 'Cost calibration snapshot loads total')
        self.cost_calib_snapshot_loads_failed_total = Counter('cost_calib_snapshot_loads_failed_total', 'Cost calibration snapshot loads failed total')
        # Selfcheck loop heartbeats (stdlib-only, timestamps in seconds)
        self._loop_heartbeats: Dict[str, float] = {}
        
        # L6.3 fill-rate metrics
        self.cost_fillrate_ewma = Gauge('cost_fillrate_ewma', 'EWMA of fill-rate (0..1)', ['symbol'])
        self.cost_fillrate_samples_total = Counter('cost_fillrate_samples_total', 'Fill-rate samples total', ['symbol'])
        # Execution replay gauges
        self.replay_events_total = Gauge('replay_events_total', 'Execution replay events processed total')
        self.replay_duration_ms = Gauge('replay_duration_ms', 'Execution replay duration (ms)')
        # L6.4 liquidity inputs/outputs
        self.liquidity_depth_usd = Gauge('liquidity_depth_usd', 'Observed liquidity depth (USD)', ['symbol'])
        self.allocator_liquidity_factor = Gauge('allocator_liquidity_factor', 'Allocator liquidity factor (floor..1)', ['symbol'])
        # L7 turnover inputs/outputs
        self.turnover_usd = Gauge('turnover_usd', 'EWMA turnover in USD (half-life)', ['symbol'])
        self.allocator_turnover_factor = Gauge('allocator_turnover_factor', 'Allocator turnover factor (floor..1)', ['symbol'])
        
        # Internal histogram counts per color
        self._rollout_latency_hist_counts: Dict[str, Tuple[int, ...]] = {
            'blue': tuple(0 for _ in self._latency_buckets_ms),
            'green': tuple(0 for _ in self._latency_buckets_ms),
        }

    # ---- Shadow helpers
    def record_shadow_sample(self, symbol: str, price_diff_bps: float, size_diff_pct: float) -> None:
        try:
            symbol = str(symbol)
            # Fixed-point conversion (truncate toward 0)
            bps_i = int(price_diff_bps)
            perml_i = int(size_diff_pct * 10.0)
            # Accumulate integer sums and count
            self._shadow_sum_price_bps_i[symbol] = int(self._shadow_sum_price_bps_i.get(symbol, 0)) + bps_i
            self._shadow_sum_size_permille_i[symbol] = int(self._shadow_sum_size_permille_i.get(symbol, 0)) + perml_i
            self._shadow_count[symbol] = int(self._shadow_count.get(symbol, 0)) + 1
            # Export last/avg gauges deterministically
            self.shadow_price_diff_bps_last.labels(symbol=symbol).set(float(bps_i))
            self.shadow_size_diff_pct_last.labels(symbol=symbol).set(float(perml_i) / 10.0)
            cnt = int(self._shadow_count[symbol])
            if cnt > 0:
                avg_bps = int(self._shadow_sum_price_bps_i[symbol]) // cnt
                avg_permille = int(self._shadow_sum_size_permille_i[symbol]) // cnt
                self.shadow_price_diff_bps_avg.labels(symbol=symbol).set(float(avg_bps))
                self.shadow_size_diff_pct_avg.labels(symbol=symbol).set(float(avg_permille) / 10.0)
            # total counter
            self.shadow_orders_total.labels(symbol=symbol).inc()
        except Exception:
            pass

    # ---- Selfcheck helpers ----
    def record_loop_heartbeat(self, loop_name: str) -> None:
        try:
            ln = str(loop_name)
            import time as _t
            with self._pm_lock:
                self._loop_heartbeats[ln] = float(_t.time())
        except Exception:
            pass

    def get_loop_heartbeats_for_tests(self) -> Dict[str, float]:
        try:
            with self._pm_lock:
                return {str(k): float(v) for k, v in sorted(self._loop_heartbeats.items())}
        except Exception:
            return {}

    # ---- Killswitch helpers ----
    def inc_killswitch_check(self) -> None:
        try:
            self.killswitch_checks_total.inc()
        except Exception:
            pass

    def inc_killswitch_trigger(self, action: str) -> None:
        try:
            self.killswitch_triggers_total.labels(action=str(action)).inc()
        except Exception:
            pass

    # ---- Auto-promotion helpers ----
    def set_autopromote_stable_steps(self, v: int) -> None:
        try:
            self.autopromote_stable_steps.set(int(max(0, v)))
        except Exception:
            pass

    def inc_autopromote_attempt(self) -> None:
        try:
            self.autopromote_attempts_total.inc()
        except Exception:
            pass

    def inc_autopromote_flip(self) -> None:
        try:
            self.autopromote_flips_total.inc()
        except Exception:
            pass

    # alias for legacy callers
    def shadow_record(self, symbol: str, price_diff_bps: float, size_diff_pct: float) -> None:
        self.record_shadow_sample(symbol, price_diff_bps, size_diff_pct)

    def get_shadow_stats(self) -> Dict[str, float]:
        total_count = int(sum(self._shadow_count.values()))
        if total_count <= 0:
            return {"count": 0, "avg_price_diff_bps": 0.0, "avg_size_diff_pct": 0.0}
        # Aggregate across symbols deterministically
        # Use integer sums and integer division (//)
        sum_bps_i = 0
        sum_permille_i = 0
        for sym in sorted(self._shadow_count.keys()):
            cnt = int(self._shadow_count.get(sym, 0))
            if cnt <= 0:
                continue
            sum_bps_i += int(self._shadow_sum_price_bps_i.get(sym, 0))
            sum_permille_i += int(self._shadow_sum_size_permille_i.get(sym, 0))
        avg_bps = sum_bps_i // total_count
        avg_permille = sum_permille_i // total_count
        return {
            "count": int(total_count),
            "avg_price_diff_bps": float(avg_bps),
            "avg_size_diff_pct": float(avg_permille) / 10.0,
        }

    # ---- Portfolio budget helpers
    def set_portfolio_budget_available_usd(self, v: float) -> None:
        try:
            with self._pm_lock:
                self._portfolio_budget_available_usd = float(v)
                self.portfolio_budget_available_usd.set(float(v))
        except Exception:
            pass

    def set_portfolio_drawdown_pct(self, v: float) -> None:
        try:
            # clip to [0,1]
            vv = 0.0 if v is None else max(0.0, min(1.0, float(v)))
            with self._pm_lock:
                self._portfolio_drawdown_pct = vv
                self.portfolio_drawdown_pct.set(vv)
        except Exception:
            pass

    def set_allocator_soft_factor(self, v: float) -> None:
        try:
            vv = 0.0 if v is None else max(0.0, min(1.0, float(v)))
            with self._pm_lock:
                self._allocator_soft_factor = vv
                self.allocator_soft_factor.set(vv)
        except Exception:
            pass

    def get_portfolio_metrics_snapshot(self) -> Dict[str, float]:
        try:
            return {
                "budget_available_usd": float(self._portfolio_budget_available_usd),
                "drawdown_pct": float(self._portfolio_drawdown_pct),
                "soft_factor": float(self._allocator_soft_factor),
                "hwm_equity_usd": float(self._allocator_hwm_equity_usd),
                "allocator_last_write_ts": float(self._allocator_last_write_ts),
                "allocator_last_load_ts": float(self._allocator_last_load_ts),
            }
        except Exception:
            return {"budget_available_usd": 0.0, "drawdown_pct": 0.0, "soft_factor": 1.0, "hwm_equity_usd": 0.0, "allocator_last_write_ts": 0.0, "allocator_last_load_ts": 0.0}

    # --- L6: Cost/slippage allocator helpers ---
    def set_allocator_cost(self, symbol: str, cost_bps: float, attenuation: float) -> None:
        try:
            s = str(symbol)
            cb = float(max(0.0, cost_bps))
            at = float(max(0.0, min(1.0, attenuation)))
            with self._pm_lock:
                self._allocator_cost_bps[s] = cb
                self._allocator_cost_atten[s] = at
                self.allocator_estimated_cost_bps.labels(symbol=s).set(cb)
                self.allocator_cost_attenuation.labels(symbol=s).set(at)
        except Exception:
            pass

    def set_allocator_cost_inputs(self, symbol: str, *, spread_bps: float, volume_usd: float, slippage_bps: float) -> None:
        try:
            s = str(symbol)
            sp = float(max(0.0, spread_bps))
            vu = float(max(0.0, volume_usd))
            sl = float(max(0.0, slippage_bps))
            with self._pm_lock:
                self._allocator_cost_inputs_spread_bps[s] = sp
                self._allocator_cost_inputs_volume_usd[s] = vu
                self._allocator_cost_slippage_bps[s] = sl
                self.allocator_cost_inputs_spread_bps.labels(symbol=s).set(sp)
                self.allocator_cost_inputs_volume_usd.labels(symbol=s).set(vu)
                self.allocator_cost_slippage_bps.labels(symbol=s).set(sl)
        except Exception:
            pass

    def _get_allocator_cost_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                # deterministic order by symbol
                out_cost = {}
                out_att = {}
                out_spread = {}
                out_vol = {}
                out_slip = {}
                for s in sorted(set(list(self._allocator_cost_bps.keys()) + list(self._allocator_cost_atten.keys()))):
                    out_cost[s] = float(self._allocator_cost_bps.get(s, 0.0))
                    out_att[s] = float(self._allocator_cost_atten.get(s, 0.0))
                for s in sorted(self._allocator_cost_inputs_spread_bps.keys() | self._allocator_cost_inputs_volume_usd.keys() | self._allocator_cost_slippage_bps.keys()):
                    out_spread[s] = float(self._allocator_cost_inputs_spread_bps.get(s, 0.0))
                    out_vol[s] = float(self._allocator_cost_inputs_volume_usd.get(s, 0.0))
                    out_slip[s] = float(self._allocator_cost_slippage_bps.get(s, 0.0))
                return {"cost_bps": out_cost, "attenuation": out_att, "spread_bps": out_spread, "volume_usd": out_vol, "slippage_bps": out_slip}
        except Exception:
            return {"cost_bps": {}, "attenuation": {}, "spread_bps": {}, "volume_usd": {}, "slippage_bps": {}}

    # ---- L6.2: Online cost calibration helpers ----
    def record_cost_observation(self, symbol: str, spread_bps: float, volume_usd: float, slippage_bps: float) -> None:
        try:
            s = str(symbol)
            sp_raw = float(max(0.0, spread_bps))
            vu_raw = float(max(0.0, volume_usd))
            sl_raw = float(max(0.0, slippage_bps))
            # Hardened: winsorize relative to previous EWMA
            win = float(max(0.0, min(0.2, self._calib_winsor_pct)))
            with self._pm_lock:
                prev_sp = float(self._cost_calib_spread_ewma_bps.get(s, sp_raw))
                prev_vu = float(self._cost_calib_volume_ewma_usd.get(s, vu_raw))
                prev_sl = float(self._cost_calib_slippage_ewma_bps.get(s, sl_raw))
                # Winsorize around previous EWMA
                def _winsor(x: float, prev: float, upper_default: float) -> float:
                    if prev <= 0.0:
                        lo, hi = 0.0, upper_default
                    else:
                        lo = max(0.0, (1.0 - win) * prev)
                        hi = (1.0 + win) * prev
                    if x < lo:
                        return lo
                    if x > hi:
                        return hi
                    return x
                sp = _winsor(sp_raw, prev_sp, 100000.0)
                vu = _winsor(vu_raw, prev_vu, 1e12)
                sl = _winsor(sl_raw, prev_sl, 10000.0)
                # Time-weighted EWMA with half-life
                import time as _t
                now = _t.time()
                last = float(self._cost_calib_last_ts.get(s, 0.0))
                self._cost_calib_last_ts[s] = now
                dt = 0.0 if last <= 0.0 else max(0.0, now - last)
                hl = float(max(0.0, self._calib_half_life_sec))
                if hl <= 0.0:
                    decay = 0.0
                else:
                    # decay in [0,1): higher dt => smaller decay
                    decay = 2.0 ** (-(dt / hl))
                ew_sp = decay * prev_sp + (1.0 - decay) * sp
                ew_vu = decay * prev_vu + (1.0 - decay) * vu
                ew_sl = decay * prev_sl + (1.0 - decay) * sl
                self._cost_calib_spread_ewma_bps[s] = ew_sp
                self._cost_calib_volume_ewma_usd[s] = ew_vu
                self._cost_calib_slippage_ewma_bps[s] = ew_sl
                # samples
                self._cost_calib_samples[s] = int(self._cost_calib_samples.get(s, 0)) + 1
                self.cost_calib_samples_total.labels(symbol=s).inc()
                # publish gauges
                self.cost_calib_spread_ewma_bps.labels(symbol=s).set(ew_sp)
                self.cost_calib_volume_ewma_usd.labels(symbol=s).set(ew_vu)
                self.cost_calib_slippage_ewma_bps.labels(symbol=s).set(ew_sl)
                # Warm-up: do not change effective params before threshold
                if int(self._cost_calib_samples.get(s, 0)) < int(max(0, self._calib_warmup_min_samples)):
                    return
                # derive effective k and cap with safe formula
                notional_kusd = max(0.0, ew_vu / 1000.0)
                base_k = ew_sl / (1.0 + notional_kusd)
                new_k = max(0.0, min(1000.0, base_k))
                new_cap = max(0.0, min(10000.0, max(ew_sl, ew_sp / 2.0)))
                # Step caps
                step = float(max(0.0, min(1.0, self._calib_max_step_pct)))
                prev_k = float(self._cost_calib_k_eff.get(s, 0.0))
                prev_cap = float(self._cost_calib_cap_eff_bps.get(s, 0.0))
                if prev_k > 0.0:
                    max_up = prev_k * (1.0 + step)
                    min_dn = prev_k * (1.0 - step)
                    new_k = max(min_dn, min(max_up, new_k))
                if prev_cap > 0.0:
                    max_up_c = prev_cap * (1.0 + step)
                    min_dn_c = prev_cap * (1.0 - step)
                    new_cap = max(min_dn_c, min(max_up_c, new_cap))
                self._cost_calib_k_eff[s] = new_k
                self._cost_calib_cap_eff_bps[s] = new_cap
                self.cost_calib_k_eff.labels(symbol=s).set(new_k)
                self.cost_calib_cap_eff_bps.labels(symbol=s).set(new_cap)
        except Exception:
            pass

    def get_cost_calib_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                syms = set(self._cost_calib_spread_ewma_bps.keys()) | set(self._cost_calib_volume_ewma_usd.keys()) | set(self._cost_calib_slippage_ewma_bps.keys()) | set(self._cost_calib_k_eff.keys()) | set(self._cost_calib_cap_eff_bps.keys())
                spread = {}
                vol = {}
                slip = {}
                k = {}
                cap = {}
                samples = {}
                for s in sorted(syms):
                    spread[s] = float(self._cost_calib_spread_ewma_bps.get(s, 0.0))
                    vol[s] = float(self._cost_calib_volume_ewma_usd.get(s, 0.0))
                    slip[s] = float(self._cost_calib_slippage_ewma_bps.get(s, 0.0))
                    k[s] = float(self._cost_calib_k_eff.get(s, 0.0))
                    cap[s] = float(self._cost_calib_cap_eff_bps.get(s, 0.0))
                    samples[s] = int(self._cost_calib_samples.get(s, 0))
                return {
                    "spread_ewma_bps": spread,
                    "volume_ewma_usd": vol,
                    "slippage_ewma_bps": slip,
                    "k_eff": k,
                    "cap_eff_bps": cap,
                    "samples": samples,
                    "config": {
                        "warmup_min_samples": int(self._calib_warmup_min_samples),
                        "winsor_pct": float(self._calib_winsor_pct),
                        "half_life_sec": float(self._calib_half_life_sec),
                        "max_step_pct": float(self._calib_max_step_pct),
                    }
                }
        except Exception:
            return {"spread_ewma_bps": {}, "volume_ewma_usd": {}, "slippage_ewma_bps": {}, "k_eff": {}, "cap_eff_bps": {}, "samples": {}, "config": {}}

    def reset_cost_calib_for_tests(self) -> None:
        try:
            with self._pm_lock:
                self._cost_calib_spread_ewma_bps.clear()
                self._cost_calib_volume_ewma_usd.clear()
                self._cost_calib_slippage_ewma_bps.clear()
                self._cost_calib_samples.clear()
                self._cost_calib_k_eff.clear()
                self._cost_calib_cap_eff_bps.clear()
                self._cost_calib_last_ts.clear()
        except Exception:
            pass

    # Effective params accessors for allocator
    def _get_calibrated_k_eff(self, symbol: str) -> float | None:
        with self._pm_lock:
            s = str(symbol)
            if s in self._cal_override_k_eff:
                return float(self._cal_override_k_eff[s])
            if s in self._cost_calib_k_eff:
                return float(self._cost_calib_k_eff[s])
            return None

    def _get_calibrated_cap_eff_bps(self, symbol: str) -> float | None:
        with self._pm_lock:
            s = str(symbol)
            if s in self._cal_override_cap_eff_bps:
                return float(self._cal_override_cap_eff_bps[s])
            if s in self._cost_calib_cap_eff_bps:
                return float(self._cost_calib_cap_eff_bps[s])
            return None

    def set_allocator_hwm_equity_usd(self, v: float) -> None:
        try:
            vv = max(0.0, float(v))
            with self._pm_lock:
                self._allocator_hwm_equity_usd = vv
                self.allocator_hwm_equity_usd.set(vv)
        except Exception:
            pass

    # ---- Snapshot counters helpers ----
    def inc_allocator_snapshot_write(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.allocator_snapshot_writes_total.inc()
                    self._allocator_last_write_ts = float(ts)
                    self.allocator_snapshot_mtime_seconds.labels(op='write').set(float(ts))
                else:
                    self.allocator_snapshot_writes_failed_total.inc()
        except Exception:
            pass

    def inc_allocator_snapshot_load(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.allocator_snapshot_loads_total.inc()
                    self._allocator_last_load_ts = float(ts)
                    self.allocator_snapshot_mtime_seconds.labels(op='load').set(float(ts))
                else:
                    self.allocator_snapshot_loads_failed_total.inc()
        except Exception:
            pass

    # ---- Throttle snapshot helpers ----
    def inc_throttle_snapshot_write(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.throttle_snapshot_writes_total.inc()
                    self._throttle_last_write_ts = float(ts)
                    self.throttle_snapshot_mtime_seconds.labels(op='write').set(float(ts))
                else:
                    self.throttle_snapshot_writes_failed_total.inc()
        except Exception:
            pass

    def inc_throttle_snapshot_load(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.throttle_snapshot_loads_total.inc()
                    self._throttle_last_load_ts = float(ts)
                    self.throttle_snapshot_mtime_seconds.labels(op='load').set(float(ts))
                else:
                    self.throttle_snapshot_loads_failed_total.inc()
        except Exception:
            pass

    # ---- Admin counters helpers ----
    def inc_admin_request(self, endpoint: str) -> None:
        try:
            self.admin_requests_total.labels(endpoint=str(endpoint)).inc()
        except Exception:
            pass

    def inc_admin_unauthorized(self, endpoint: str) -> None:
        try:
            self.admin_unauthorized_total.labels(endpoint=str(endpoint)).inc()
        except Exception:
            pass
        
        # Market metrics
        self.spread_bps = Gauge('spread_bps', 'Current spread in basis points', ['symbol'])
        self.vola_1m = Gauge('vola_1m', '1-minute volatility', ['symbol'])
        self.vola_ewma = Gauge('vola_ewma', 'EWMA volatility for portfolio allocation', ['symbol'])
        self.ob_imbalance = Gauge('ob_imbalance', 'Order book imbalance', ['symbol'])
        # Inventory/exposure & infra
        self.position_notional_usd = Gauge('position_notional_usd', 'Net position notional', ['symbol'])
        self.gross_exposure_usd = Gauge('gross_exposure_usd', 'Gross exposure', ['symbol'])
        self.cancel_latency_p95_ms = Gauge('cancel_latency_p95_ms', 'P95 cancel latency')
        self.ws_lag_ms = Gauge('ws_lag_ms', 'WebSocket lag ms')
        self.order_reject_rate = Gauge('order_reject_rate', 'Order reject rate')
        
        # Config gauges (updated on reload) - EXACT names
        self.cfg_levels_per_side = Gauge('cfg_levels_per_side', 'Configured levels per side', [])
        self.cfg_min_time_in_book_ms = Gauge('cfg_min_time_in_book_ms', 'Configured min time in book (ms)', [])
        self.cfg_k_vola_spread = Gauge('cfg_k_vola_spread', 'Configured volatility spread coefficient', [])
        self.cfg_skew_coeff = Gauge('cfg_skew_coeff', 'Configured inventory skew coefficient', [])
        self.cfg_imbalance_cutoff = Gauge('cfg_imbalance_cutoff', 'Configured imbalance cutoff', [])
        self.cfg_max_create_per_sec = Gauge('cfg_max_create_per_sec', 'Configured max create rate per second', [])
        self.cfg_max_cancel_per_sec = Gauge('cfg_max_cancel_per_sec', 'Configured max cancel rate per second', [])
        
        # Rate tracking (per-symbol deque timestamps)
        self._create_timestamps: Dict[str, deque] = {}  # symbol -> deque of timestamps
        self._cancel_timestamps: Dict[str, deque] = {}  # symbol -> deque of timestamps
        
        # Initialize config gauges
        self.export_cfg_gauges(ctx.cfg)

        # F2 gate counters
        try:
            self.f2_throttle_gate_pass_total = Counter('f2_throttle_gate_pass_total', 'F2 throttle gate pass', ['symbol'])
            self.f2_throttle_gate_failures_total = Counter('f2_throttle_gate_failures_total', 'F2 throttle gate failures', ['symbol', 'reason'])
        except Exception:
            # If registry already has them, reuse
            try:
                from prometheus_client import REGISTRY
                self.f2_throttle_gate_pass_total = REGISTRY._names_to_collectors['f2_throttle_gate_pass_total']  # type: ignore[attr-defined]
                self.f2_throttle_gate_failures_total = REGISTRY._names_to_collectors['f2_throttle_gate_failures_total']  # type: ignore[attr-defined]
            except Exception:
                self.f2_throttle_gate_pass_total = None  # type: ignore[assignment]
                self.f2_throttle_gate_failures_total = None  # type: ignore[assignment]

        # Thresholds reload metrics
        try:
            self.thresholds_reload_total = Counter('thresholds_reload_total', 'Thresholds reload attempts', ['result'])
            self.thresholds_version = Gauge('thresholds_version', 'Current thresholds version')
        except Exception:
            try:
                from prometheus_client import REGISTRY
                self.thresholds_reload_total = REGISTRY._names_to_collectors['thresholds_reload_total']  # type: ignore[attr-defined]
                self.thresholds_version = REGISTRY._names_to_collectors['thresholds_version']  # type: ignore[attr-defined]
            except Exception:
                self.thresholds_reload_total = None  # type: ignore[assignment]
                self.thresholds_version = None  # type: ignore[assignment]
    
    # NEW: Helper methods for reliability metrics
    def on_amend_attempt(self, symbol: str, side: str) -> None:
        """Increment amend attempts counter."""
        self.amend_attempts_total.labels(symbol=symbol, side=side).inc()
    
    def on_amend_success(self, symbol: str, side: str) -> None:
        """Increment successful amends counter."""
        self.amend_success_total.labels(symbol=symbol, side=side).inc()
    
    def on_reconcile_action(self, action: str) -> None:
        """Increment reconciliation actions counter.
        
        Args:
            action: One of "attach", "close", "mark_filled", "mark_canceled", "noop"
        """
        valid_actions = {"attach", "close", "mark_filled", "mark_canceled", "noop"}
        if action not in valid_actions:
            self._rate_logger.warn_once(f"Invalid reconcile action: {action}")
            return
        self.reconcile_actions_total.labels(action=action).inc()
    
    def add_backoff_seconds(self, seconds: float) -> None:
        """Add backoff time to cumulative counter."""
        if seconds < 0:
            self._rate_logger.warn_once(f"Negative backoff seconds: {seconds}")
            return
        self.backoff_seconds_sum.inc(seconds)
    
    def set_circuit_breaker_state(self, on: bool) -> None:
        """Set circuit breaker state (True=open, False=closed)."""
        self.circuit_breaker_state.set(1 if on else 0)
    
    def export_cfg_gauges(self, cfg: AppConfig) -> None:
        """Export key config values as Prometheus gauges."""
        try:
            self.cfg_levels_per_side.set(cfg.strategy.levels_per_side)
            self.cfg_min_time_in_book_ms.set(cfg.strategy.min_time_in_book_ms)
            self.cfg_k_vola_spread.set(cfg.strategy.k_vola_spread)
            self.cfg_skew_coeff.set(cfg.strategy.skew_coeff)
            self.cfg_imbalance_cutoff.set(cfg.strategy.imbalance_cutoff)
            self.cfg_max_create_per_sec.set(cfg.limits.max_create_per_sec)
            self.cfg_max_cancel_per_sec.set(cfg.limits.max_cancel_per_sec)
        except Exception as e:
            self._rate_logger.warn_once(f"Failed to export config gauges: {e}")
    
    def observe_latency(self, stage: str, ms: float) -> None:
        """Observe latency for a specific stage."""
        if stage not in ["md", "rest", "ws"]:
            self._rate_logger.warn_once(f"Invalid latency stage: {stage}")
            return
        self.latency_ms.labels(stage=stage).observe(ms)
    
    def update_order_metrics(self, symbol: str, side: str, action: str, count: int = 1) -> None:
        """Update order-related metrics."""
        if action == "create":
            self.creates_total.labels(symbol=symbol).inc(count)
            self._update_create_rate(symbol)
        elif action == "cancel":
            self.cancels_total.labels(symbol=symbol).inc(count)
            self._update_cancel_rate(symbol)
        elif action == "replace":
            self.replaces_total.labels(symbol=symbol).inc(count)
    
    def update_quote_metrics(self, symbol: str, count: int = 1) -> None:
        """Update quote-related metrics."""
        self.quotes_placed_total.labels(symbol=symbol).inc(count)

    # ---- F2 gate helper methods
    def inc_f2_gate_pass(self, symbol: str) -> None:
        try:
            if getattr(self, 'f2_throttle_gate_pass_total', None):
                self.f2_throttle_gate_pass_total.labels(symbol=str(symbol)).inc()
        except Exception:
            pass

    def inc_f2_gate_fail(self, symbol: str, reason: str) -> None:
        try:
            if getattr(self, 'f2_throttle_gate_failures_total', None):
                self.f2_throttle_gate_failures_total.labels(symbol=str(symbol), reason=str(reason)).inc()
        except Exception:
            pass

    # ---- Thresholds reload helpers
    def inc_thresholds_reload(self, ok: bool) -> None:
        try:
            if getattr(self, 'thresholds_reload_total', None):
                self.thresholds_reload_total.labels(result='ok' if ok else 'failed').inc()
        except Exception:
            pass

    def set_thresholds_version(self, v: int) -> None:
        try:
            if getattr(self, 'thresholds_version', None):
                self.thresholds_version.set(int(v))
        except Exception:
            pass

    # ---- Rollout helpers ----
    def inc_rollout_order(self, color: str) -> None:
        try:
            c = str(color)
            self.rollout_orders_total.labels(color=c).inc()
            with self._pm_lock:
                # track counts
                self._rollout_orders_count[c] = int(self._rollout_orders_count.get(c, 0)) + 1
                green = int(self._rollout_orders_count.get('green', 0))
                blue = int(self._rollout_orders_count.get('blue', 0))
                total = blue + green
                observed = 0.0 if total <= 0 else (100.0 * green / float(total))
                self.rollout_split_observed_pct.set(observed)
                # drift detection vs expected split gauge
                try:
                    expected = int(self.rollout_traffic_split_pct._value.get())  # type: ignore[attr-defined]
                except Exception:
                    expected = 0
                drift = abs(observed - float(expected))
                if drift > 5.0:  # default cap 5%
                    self.rollout_split_drift_alerts_total.inc()
        except Exception:
            pass

    def set_rollout_split_pct(self, v: int) -> None:
        try:
            self.rollout_traffic_split_pct.set(int(max(0, min(100, int(v)))))
        except Exception:
            pass

    def inc_rollout_fill(self, color: str, latency_ms: float) -> None:
        try:
            c = str(color)
            lm = float(latency_ms)
            with self._pm_lock:
                # counters
                self.rollout_fills_total.labels(color=c).inc()
                self._rollout_fills[c] = int(self._rollout_fills.get(c, 0)) + 1
                # ewma
                prev = float(self._rollout_latency_ewma.get(c, lm))
                ewma = self._rollout_ewma_alpha * lm + (1.0 - self._rollout_ewma_alpha) * prev
                self._rollout_latency_ewma[c] = ewma
                self.rollout_avg_latency_ms.labels(color=c).set(float(ewma))
                # latency histogram update
                self._update_latency_histogram_locked(c, lm)
        except Exception:
            pass

    def inc_rollout_reject(self, color: str) -> None:
        try:
            c = str(color)
            with self._pm_lock:
                self.rollout_rejects_total.labels(color=c).inc()
                self._rollout_rejects[c] = int(self._rollout_rejects.get(c, 0)) + 1
        except Exception:
            pass

    def set_rollout_pnl(self, color: str, v: float) -> None:
        try:
            self.rollout_pnl_usd.labels(color=str(color)).set(float(v))
        except Exception:
            pass

    def inc_rollout_pinned_hit(self) -> None:
        try:
            self.rollout_pinned_hits_total.inc()
        except Exception:
            pass

    def inc_rollout_overlay_applied(self, color: str) -> None:
        try:
            self.rollout_overlay_applied_total.labels(color=str(color)).inc()
        except Exception:
            pass

    def inc_rollout_overlay_compiled(self) -> None:
        try:
            self.rollout_overlay_compiled_total.inc()
        except Exception:
            pass

    def set_rollout_split_observed_pct(self, v: float) -> None:
        try:
            vv = float(max(0.0, min(100.0, float(v))))
            self.rollout_split_observed_pct.set(vv)
        except Exception:
            pass

    def inc_rollout_split_drift_alert(self) -> None:
        try:
            self.rollout_split_drift_alerts_total.inc()
        except Exception:
            pass

    # ---- Latency buckets helpers ----
    def _bucket_index_for_latency(self, latency_ms: float) -> int:
        lm = float(latency_ms)
        for i, ub in enumerate(self._latency_buckets_ms):
            if lm <= ub:
                return i
        return len(self._latency_buckets_ms) - 1

    def _bucket_label(self, idx: int) -> str:
        ub = self._latency_buckets_ms[idx]
        return "+Inf" if ub == float('inf') else (str(int(ub)) if ub.is_integer() else str(ub))

    def _update_latency_histogram_locked(self, color: str, latency_ms: float) -> None:
        try:
            color_key = 'green' if str(color).lower() == 'green' else 'blue'
            # increment bucket counter
            idx = self._bucket_index_for_latency(latency_ms)
            # prometheus bucket counter
            self.rollout_latency_bucket_total.labels(color=color_key, bucket_ms=self._bucket_label(idx)).inc()
            # internal counts: convert tuple to list, then back to tuple for immutability semantics
            counts = list(self._rollout_latency_hist_counts.get(color_key, tuple(0 for _ in self._latency_buckets_ms)))
            counts[idx] = int(counts[idx]) + 1
            self._rollout_latency_hist_counts[color_key] = tuple(counts)
            # update samples gauge
            total_samples = int(sum(counts))
            self.rollout_latency_samples_total.labels(color=color_key).set(float(total_samples))
            # recompute quantiles
            self._recompute_latency_quantiles_locked(color_key)
        except Exception:
            pass

    def _recompute_latency_quantiles_locked(self, color_key: str) -> None:
        try:
            counts = list(self._rollout_latency_hist_counts.get(color_key, ()))
            if not counts:
                self.rollout_latency_p95_ms.labels(color=color_key).set(0.0)
                self.rollout_latency_p99_ms.labels(color=color_key).set(0.0)
                return
            total = int(sum(counts))
            if total <= 0:
                self.rollout_latency_p95_ms.labels(color=color_key).set(0.0)
                self.rollout_latency_p99_ms.labels(color=color_key).set(0.0)
                return
            import math
            def _percentile_rank(p: float) -> int:
                # Nearest-rank, 1-based
                return max(1, int(math.ceil(p * total)))
            def _value_at_rank(rank: int) -> float:
                cum = 0
                for i, cnt in enumerate(counts):
                    cum += int(cnt)
                    if cum >= rank:
                        ub = self._latency_buckets_ms[i]
                        if ub == float('inf'):
                            # fall back to last finite upper bound
                            j = max(0, i - 1)
                            val = self._latency_buckets_ms[j]
                            return float(val)
                        return float(ub)
                # fallback
                return float(self._latency_buckets_ms[-2])
            p95 = _value_at_rank(_percentile_rank(0.95))
            p99 = _value_at_rank(_percentile_rank(0.99))
            self.rollout_latency_p95_ms.labels(color=color_key).set(float(p95))
            self.rollout_latency_p99_ms.labels(color=color_key).set(float(p99))
        except Exception:
            pass

    def _get_latency_snapshot_for_tests(self) -> Dict[str, Any]:
        try:
            with self._pm_lock:
                labels = [self._bucket_label(i) for i in range(len(self._latency_buckets_ms))]
                def _get_quant(color: str, which: str) -> float:
                    try:
                        if which == 'p95':
                            return float(self.rollout_latency_p95_ms.labels(color=color)._value.get())  # type: ignore[attr-defined]
                        return float(self.rollout_latency_p99_ms.labels(color=color)._value.get())  # type: ignore[attr-defined]
                    except Exception:
                        return 0.0
                return {
                    'buckets_ms': labels,
                    'counts': {
                        'blue': list(self._rollout_latency_hist_counts.get('blue', tuple())),
                        'green': list(self._rollout_latency_hist_counts.get('green', tuple())),
                    },
                    'samples_total': {
                        'blue': int(sum(self._rollout_latency_hist_counts.get('blue', tuple()))),
                        'green': int(sum(self._rollout_latency_hist_counts.get('green', tuple()))),
                    },
                    'p95': {
                        'blue': _get_quant('blue', 'p95'),
                        'green': _get_quant('green', 'p95'),
                    },
                    'p99': {
                        'blue': _get_quant('blue', 'p99'),
                        'green': _get_quant('green', 'p99'),
                    },
                }
        except Exception:
            return {'buckets_ms': [], 'counts': {'blue': [], 'green': []}, 'p95': {'blue': 0.0, 'green': 0.0}, 'p99': {'blue': 0.0, 'green': 0.0}}

    # ---- Latency SLO helpers ----
    def set_latency_slo(self, color: str, percentile: str, burn_rate: float, budget_remaining: float) -> None:
        try:
            c = 'green' if str(color).lower() == 'green' else 'blue'
            p = 'p95' if str(percentile).lower() == 'p95' else 'p99'
            br = max(0.0, float(burn_rate))
            bg = max(0.0, float(budget_remaining))
            self.latency_slo_burn_rate.labels(color=c, percentile=p).set(br)
            self.latency_slo_budget_remaining.labels(color=c, percentile=p).set(bg)
        except Exception:
            pass

    def inc_latency_slo_alert(self, percentile: str) -> None:
        try:
            p = 'p95' if str(percentile).lower() == 'p95' else 'p99'
            self.latency_slo_alerts_total.labels(percentile=p).inc()
        except Exception:
            pass

    # ---- E3: Perf/Soak helpers ----
    def _perf_bucket_index(self, latency_ms: float) -> int:
        lm = float(latency_ms)
        for i, ub in enumerate(getattr(self, '_perf_latency_buckets_ms', tuple())):
            if lm <= ub:
                return i
        return len(getattr(self, '_perf_latency_buckets_ms', tuple())) - 1

    def _perf_bucket_label(self, idx: int) -> str:
        ub = getattr(self, '_perf_latency_buckets_ms', tuple())[idx]
        return "+Inf" if ub == float('inf') else (str(int(ub)) if float(ub).is_integer() else str(ub))

    def record_loop_tick(self, loop_name: str, duration_ms: float) -> None:
        """Record loop tick duration and update p95/p99 using nearest-rank on histogram buckets."""
        try:
            ln = str(loop_name)
            dm = max(0.0, float(duration_ms))
            self.loop_tick_ms.labels(loop=ln).set(dm)
            # also record process CPU time delta best-effort
            try:
                import time as _t
                cpu_ms = float(_t.process_time() * 1000.0)
                self.loop_tick_cpu_ms.labels(loop=ln).set(cpu_ms)
            except Exception:
                pass
            # update histogram counts
            idx = self._perf_bucket_index(dm)
            counts = list(self._loop_hist_counts.get(ln, tuple(0 for _ in self._perf_latency_buckets_ms)))
            counts[idx] = int(counts[idx]) + 1
            self._loop_hist_counts[ln] = tuple(counts)
            # recompute percentiles
            total = int(sum(counts))
            if total <= 0:
                self.loop_tick_p95_ms.labels(loop=ln).set(0.0)
                self.loop_tick_p99_ms.labels(loop=ln).set(0.0)
                return
            import math
            def _rank(p: float) -> int:
                return max(1, int(math.ceil(p * total)))
            def _val_at(r: int) -> float:
                cum = 0
                for i, cnt in enumerate(counts):
                    cum += int(cnt)
                    if cum >= r:
                        ub = self._perf_latency_buckets_ms[i]
                        if ub == float('inf'):
                            j = max(0, i-1)
                            return float(self._perf_latency_buckets_ms[j])
                        return float(ub)
                return float(self._perf_latency_buckets_ms[-2])
            p95 = _val_at(_rank(0.95))
            p99 = _val_at(_rank(0.99))
            self.loop_tick_p95_ms.labels(loop=ln).set(p95)
            self.loop_tick_p99_ms.labels(loop=ln).set(p99)
        except Exception:
            pass

    def set_event_loop_drift(self, drift_ms: float) -> None:
        try:
            cur = 0.0
            try:
                cur = float(self.event_loop_drift_ms._value.get())  # type: ignore[attr-defined]
            except Exception:
                cur = 0.0
            v = float(max(cur, float(drift_ms)))
            self.event_loop_drift_ms.set(v)
        except Exception:
            pass

    def record_admin_endpoint_latency(self, endpoint: str, latency_ms: float) -> None:
        try:
            ep = str(endpoint)
            lm = max(0.0, float(latency_ms))
            idx = self._perf_bucket_index(lm)
            label = self._perf_bucket_label(idx)
            self.admin_endpoint_latency_bucket_total.labels(endpoint=ep, bucket_ms=label).inc()
            key = (ep, label)
            self._admin_endpoint_bucket_counts[key] = int(self._admin_endpoint_bucket_counts.get(key, 0)) + 1
        except Exception:
            pass

    def _get_perf_snapshot_for_tests(self) -> Dict[str, Any]:
        try:
            with self._pm_lock:
                loops = {}
                for ln in sorted(self._loop_hist_counts.keys()):
                    try:
                        last = float(self.loop_tick_ms.labels(loop=ln)._value.get())  # type: ignore[attr-defined]
                        p95 = float(self.loop_tick_p95_ms.labels(loop=ln)._value.get())  # type: ignore[attr-defined]
                        p99 = float(self.loop_tick_p99_ms.labels(loop=ln)._value.get())  # type: ignore[attr-defined]
                    except Exception:
                        last = p95 = p99 = 0.0
                    loops[ln] = {"last_ms": last, "p95_ms": p95, "p99_ms": p99}
                drift = 0.0
                try:
                    drift = float(self.event_loop_drift_ms._value.get())  # type: ignore[attr-defined]
                except Exception:
                    drift = 0.0
                buckets = {}
                for (ep, lab), cnt in sorted(self._admin_endpoint_bucket_counts.items()):
                    buckets.setdefault(ep, {})[lab] = int(cnt)
                # include allocator observability (cost_bps and fillrate attenuation)
                alloc = {}
                try:
                    cost_snap = self._get_allocator_cost_snapshot_for_tests()
                except Exception:
                    cost_snap = {"cost_bps": {}, "attenuation": {}}
                try:
                    fr = self.get_cost_fillrate_snapshot_for_tests()
                except Exception:
                    fr = {"r": {}}
                # build per symbol
                symbols = set()
                symbols |= set((cost_snap.get('cost_bps', {}) or {}).keys())
                symbols |= set((fr.get('r', {}) or {}).keys())
                for s in sorted(symbols):
                    alloc[s] = {
                        "cost_bps": float((cost_snap.get('cost_bps', {}) or {}).get(s, 0.0)),
                        "fillrate_ewma": float((fr.get('r', {}) or {}).get(s, 1.0)),
                        # best-effort read of fillrate attenuation gauge
                        "fillrate_attenuation": float(self.allocator_fillrate_attenuation.labels(symbol=s)._value.get()) if hasattr(self.allocator_fillrate_attenuation, '_value') else 0.0,  # type: ignore[attr-defined]
                    }
                return {"loops": loops, "event_loop_drift_ms": drift, "admin_latency_buckets": buckets, "allocator": alloc}
        except Exception:
            return {"loops": {}, "event_loop_drift_ms": 0.0, "admin_latency_buckets": {}, "allocator": {}}

    def reset_perf_for_tests(self) -> None:
        try:
            with self._pm_lock:
                self._loop_hist_counts.clear()
                self._admin_endpoint_bucket_counts.clear()
                # reset gauges to zero for known loops is not possible without labels; leave as-is
                self.event_loop_drift_ms.set(0.0)
        except Exception:
            pass

    # ---- E3.3: Soak & leak test snapshot ----
    def _get_soak_snapshot_for_tests(self) -> Dict[str, Any]:
        try:
            with self._pm_lock:
                try:
                    rss = int(self.soak_mem_rss_bytes._value.get())  # type: ignore[attr-defined]
                except Exception:
                    rss = 0
                try:
                    fds = int(self.soak_open_fds._value.get())  # type: ignore[attr-defined]
                except Exception:
                    fds = 0
                try:
                    th = int(self.soak_threads_total._value.get())  # type: ignore[attr-defined]
                except Exception:
                    th = 0
                gc_map: Dict[str, int] = {}
                for g in ('0', '1', '2'):
                    try:
                        gc_map[g] = int(self.soak_gc_gen.labels(gen=g)._value.get())  # type: ignore[attr-defined]
                    except Exception:
                        gc_map[g] = 0
                try:
                    dmax = float(self.event_loop_max_drift_ms._value.get())  # type: ignore[attr-defined]
                except Exception:
                    dmax = 0.0
                return {
                    "version": 1,
                    "current": {
                        "rss_bytes": int(rss),
                        "open_fds": int(fds),
                        "threads": int(th),
                        "gc_gen": {k: int(v) for k, v in sorted(gc_map.items())},
                        "drift_ms": float(dmax),
                    },
                    "window_max": {
                        "rss_bytes": int(rss),
                        "open_fds": int(fds),
                        "threads": int(th),
                        "gc_gen": {k: int(v) for k, v in sorted(gc_map.items())},
                        "drift_ms": float(dmax),
                    }
                }
        except Exception:
            return {"version": 1, "current": {"rss_bytes": 0, "open_fds": 0, "threads": 0, "gc_gen": {"0": 0, "1": 0, "2": 0}, "drift_ms": 0.0}, "window_max": {"rss_bytes": 0, "open_fds": 0, "threads": 0, "gc_gen": {"0": 0, "1": 0, "2": 0}, "drift_ms": 0.0}}

    # ---- L6.4: Liquidity test hooks ----
    def test_set_liquidity_depth(self, symbol: str, depth_usd: float) -> None:
        try:
            s = str(symbol)
            d = float(max(0.0, depth_usd))
            self.liquidity_depth_usd.labels(symbol=s).set(d)
        except Exception:
            pass

    def get_liquidity_snapshot_for_tests(self) -> Dict[str, float]:
        try:
            out: Dict[str, float] = {}
            # We don't have a registry listing of labels; rely on known symbols from cost/fillrate snapshots
            syms = set()
            try:
                cs = self._get_allocator_cost_snapshot_for_tests()
                syms |= set((cs.get('cost_bps', {}) or {}).keys())
            except Exception:
                pass
            try:
                fr = self.get_cost_fillrate_snapshot_for_tests()
                syms |= set((fr.get('r', {}) or {}).keys())
            except Exception:
                pass
            for s in sorted(syms):
                try:
                    v = float(self.liquidity_depth_usd.labels(symbol=s)._value.get())  # type: ignore[attr-defined]
                except Exception:
                    v = 0.0
                out[s] = float(max(0.0, v))
            return out
        except Exception:
            return {}

    # ---- L7: Turnover helpers ----
    def record_trade_notional(self, symbol: str, usd: float, ts: float | None = None) -> None:
        try:
            s = str(symbol)
            now = float(ts) if ts is not None else time.time()
            with self._pm_lock:
                prev_ts = float(self._turnover_last_ts.get(s, 0.0))
                self._turnover_last_ts[s] = now
                prev = float(self._turnover_ewma_usd.get(s, 0.0))
                v = float(max(0.0, usd))
                # half-life from cfg
                hl = 600.0
                try:
                    hl = float(getattr(getattr(self.ctx, 'cfg', object()), 'portfolio').cost.turnover_half_life_sec)
                except Exception:
                    hl = 600.0
                if hl < 10.0:
                    hl = 10.0
                dt = 0.0 if prev_ts <= 0.0 else max(0.0, now - prev_ts)
                decay = 0.0 if hl <= 0.0 else (2.0 ** (-(dt / hl)))
                ew = decay * prev + (1.0 - decay) * v
                if ew < 0.0:
                    ew = 0.0
                self._turnover_ewma_usd[s] = float(ew)
                self._turnover_samples[s] = int(self._turnover_samples.get(s, 0)) + 1
                self.turnover_usd.labels(symbol=s).set(float(ew))
        except Exception:
            pass

    def get_turnover_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                out_r = {}
                out_n = {}
                for s in sorted(self._turnover_ewma_usd.keys() | self._turnover_samples.keys()):
                    out_r[s] = float(self._turnover_ewma_usd.get(s, 0.0))
                    out_n[s] = int(self._turnover_samples.get(s, 0))
                return {"usd": out_r, "samples": out_n}
        except Exception:
            return {"usd": {}, "samples": {}}

    def reset_turnover_for_tests(self) -> None:
        try:
            with self._pm_lock:
                self._turnover_ewma_usd.clear()
                self._turnover_last_ts.clear()
                self._turnover_samples.clear()
        except Exception:
            pass

    def _get_allocator_obs_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                cost = self._get_allocator_cost_snapshot_for_tests()
                fr = self.get_cost_fillrate_snapshot_for_tests()
                to = self.get_turnover_snapshot_for_tests() if hasattr(self, 'get_turnover_snapshot_for_tests') else {"usd": {}}
                out: Dict[str, Dict[str, float]] = {}
                symbols = set()
                symbols |= set((cost.get('cost_bps', {}) or {}).keys())
                symbols |= set((fr.get('r', {}) or {}).keys())
                try:
                    symbols |= set(((to or {}).get('usd', {}) or {}).keys())
                except Exception:
                    pass
                for s in sorted(symbols):
                    try:
                        att_fill = float(self.allocator_fillrate_attenuation.labels(symbol=s)._value.get())  # type: ignore[attr-defined]
                    except Exception:
                        att_fill = 0.0
                    try:
                        turn_factor = float(self.allocator_turnover_factor.labels(symbol=s)._value.get())  # type: ignore[attr-defined]
                    except Exception:
                        turn_factor = 0.0
                    try:
                        turn_usd = float(((to or {}).get('usd', {}) or {}).get(s, 0.0))
                    except Exception:
                        turn_usd = 0.0
                    out[s] = {
                        'cost_bps': float((cost.get('cost_bps', {}) or {}).get(s, 0.0)),
                        'fillrate_ewma': float((fr.get('r', {}) or {}).get(s, 1.0)),
                        'fillrate_attenuation': att_fill,
                        'turnover_usd': turn_usd,
                        'turnover_factor': turn_factor,
                    }
                return out
        except Exception:
            return {}

    # ---- L7.1: Position skew integration hooks ----
    def record_position_skew_breach(self, *, symbol_breach: Iterable[str], color_breach: bool) -> None:
        try:
            self._pos_skew.on_breach(symbol_breach, bool(color_breach))
        except Exception:
            pass

    def build_position_skew_artifacts_payload(self, *, positions_by_symbol: Dict[str, float], decision: Any) -> Dict[str, Any]:
        try:
            sym_breach = sorted(list(getattr(decision, 'symbol_breach', set()) or []))
            color_breach = bool(getattr(decision, 'color_breach', False))
        except Exception:
            sym_breach = []
            color_breach = False
        try:
            positions_compact = self._pos_skew.snapshot(positions_by_symbol or {})
        except Exception:
            positions_compact = {}
        # Best-effort export pos_skew_abs per symbol
        try:
            from src.guards.position_skew import PositionSkewGuard
            # infer env/service (defaults if not set)
            env = str(getattr(getattr(self.ctx, 'cfg', object()), 'env', 'canary')) if hasattr(getattr(self.ctx, 'cfg', object()), 'env') else 'canary'
            service = 'mm-bot'
            # If guard instance exists on state and has _last_pos_skew_abs, export single value
            guard = getattr(getattr(self.ctx, 'state', object()), 'intraday_caps_guard', None)
        except Exception:
            guard = None  # type: ignore
        try:
            # Without direct guard, compute max per-symbol ratio using per_symbol_abs_limit if available
            limit = 0.0
            try:
                limit = float(getattr(getattr(getattr(self.ctx, 'cfg', object()), 'guards', object()), 'pos_skew', object()).per_symbol_abs_limit)  # type: ignore[attr-defined]
            except Exception:
                limit = 0.0
            if limit > 0.0:
                for s in sorted((positions_by_symbol or {}).keys()):
                    val = abs(float((positions_by_symbol or {}).get(s, 0.0))) / float(limit)
                    try:
                        self.pos_skew_abs.labels(env=str(env), service=str(service), symbol=str(s)).set(float(val))
                    except Exception:
                        pass
        except Exception:
            pass
        return {
            "positions": positions_compact,
            "symbol_breach": sym_breach,
            "color_breach": color_breach,
        }

    # ---- Intraday caps helpers ----
    def update_intraday_caps(self, *, pnl: float, turnover: float, vol: float, breached: bool) -> None:
        try:
            self._caps.on_update(float(pnl), float(turnover), float(vol), bool(breached))
        except Exception:
            pass

    def get_intraday_caps_snapshot(self) -> Dict[str, Any]:
        try:
            return self._caps.snapshot()
        except Exception:
            return {'pnl': 0.0, 'turnover': 0.0, 'vol': 0.0, 'breached': 0}

    # ---- Fee tiers helpers ----
    def get_turnover_total_ewma_usd(self) -> float:
        # Sum turnover EWMA across symbols (best-effort)
        try:
            with self._pm_lock:
                # use internal snapshot helper if available
                snap = self.get_turnover_snapshot_for_tests() if hasattr(self, 'get_turnover_snapshot_for_tests') else {"usd": {}}
                return float(sum((snap.get('usd', {}) or {}).values()))
        except Exception:
            return 0.0

    def build_fee_tier_payload(self, *, maker_share: float = 0.8, taker_share: float = 0.2) -> Dict[str, Any]:
        try:
            rolling = float(self.get_turnover_total_ewma_usd())
            tier = expected_tier(rolling)
            dist = distance_to_next_tier(rolling)
            eff_now = float(effective_fee_bps(float(maker_share), float(taker_share), tier))
            # publish gauges
            self._fees.publish(tier=tier, distance_usd=dist, eff_fee_bps_now=eff_now)
            return {'level': float(int(tier.level)), 'maker_bps': float(tier.maker_bps), 'taker_bps': float(tier.taker_bps), 'distance_usd': float(dist), 'effective_fee_bps_now': float(eff_now)}
        except Exception:
            return {'level': 0.0, 'maker_bps': 0.0, 'taker_bps': 0.0, 'distance_usd': 0.0, 'effective_fee_bps_now': 0.0}

    def build_fee_tier_artifacts_payload(self, *, tier_now: FeeTier, tier_next: Optional[FeeTier], dist_usd: float, eff_now_bps: float, eff_next_bps: float) -> Dict[str, Any]:
        try:
            tier_now_obj = {
                'level': float(int(getattr(tier_now, 'level', 0))),
                'maker_bps': float(getattr(tier_now, 'maker_bps', 0.0)),
                'taker_bps': float(getattr(tier_now, 'taker_bps', 0.0)),
            }
            if tier_next is not None:
                tier_next_obj = {
                    'level': float(int(getattr(tier_next, 'level', 0))),
                    'maker_bps': float(getattr(tier_next, 'maker_bps', 0.0)),
                    'taker_bps': float(getattr(tier_next, 'taker_bps', 0.0)),
                }
            else:
                tier_next_obj = None
            return {
                'tier_now': tier_now_obj,
                'tier_next': tier_next_obj,
                'distance_usd': float(dist_usd),
                'effective_fee_bps_now': float(eff_now_bps),
                'effective_fee_bps_next': float(eff_next_bps),
            }
        except Exception:
            return {
                'tier_now': {'level': 0.0, 'maker_bps': 0.0, 'taker_bps': 0.0},
                'tier_next': None,
                'distance_usd': 0.0,
                'effective_fee_bps_now': 0.0,
                'effective_fee_bps_next': 0.0,
            }

    def export_fees_artifacts(self, *, maker_share: float = 0.8, taker_share: float = 0.2) -> None:
        try:
            rolling = float(self.get_turnover_total_ewma_usd())
            tier_now = expected_tier(rolling)
            # find next tier
            try:
                idx = 0
                for i, t in enumerate(BYBIT_SPOT_TIERS):
                    if int(t.level) == int(tier_now.level):
                        idx = i
                        break
                tier_next = BYBIT_SPOT_TIERS[idx + 1] if idx + 1 < len(BYBIT_SPOT_TIERS) else None
            except Exception:
                tier_next = None
            dist = distance_to_next_tier(rolling)
            eff_now = float(effective_fee_bps(float(maker_share), float(taker_share), tier_now))
            eff_next = float(effective_fee_bps(float(maker_share), float(taker_share), tier_next)) if tier_next is not None else 0.0
            payload = self.build_fee_tier_artifacts_payload(tier_now=tier_now, tier_next=tier_next, dist_usd=dist, eff_now_bps=eff_now, eff_next_bps=eff_next)
            try:
                from src.common.artifacts import write_json_atomic
                write_json_atomic("artifacts/metrics.json", {"fees": payload})
            except Exception:
                pass
        except Exception:
            pass

    def build_unified_artifacts_payload(self) -> Dict[str, Any]:
        """Build unified payload for artifacts/metrics.json with alphabetical keys."""
        payload = {}
        
        # fees section
        try:
            rolling = float(self.get_turnover_total_ewma_usd())
            tier_now = expected_tier(rolling)
            dist = distance_to_next_tier(rolling)
            eff_now = float(effective_fee_bps(0.8, 0.2, tier_now))
            payload["fees"] = {
                "tier_level": self._finite(float(tier_now.level)),
                "maker_bps": self._finite(float(tier_now.maker_bps)),
                "taker_bps": self._finite(float(tier_now.taker_bps)),
                "distance_usd": self._finite(float(dist)),
                "effective_fee_bps_now": self._finite(float(eff_now))
            }
        except Exception:
            print("WARN artifacts: section 'fees' missing, writing {}")
            payload["fees"] = {}
        
        # intraday_caps section
        try:
            caps_snapshot = self.get_intraday_caps_snapshot()
            if caps_snapshot:
                sanitized = {}
                for k, v in caps_snapshot.items():
                    if isinstance(v, (int, float)):
                        sanitized[k] = self._finite(float(v))
                    else:
                        sanitized[k] = v
                payload["intraday_caps"] = sanitized
            else:
                payload["intraday_caps"] = {}
        except Exception:
            print("WARN artifacts: section 'intraday_caps' missing, writing {}")
            payload["intraday_caps"] = {}
        
        # position_skew section
        try:
            # Get current positions and decision from context if available
            positions_by_symbol = {}
            decision = type('D', (), {'symbol_breach': set(), 'color_breach': False})()
            try:
                ctx = getattr(self, 'ctx', None)
                if ctx:
                    state = getattr(ctx, 'state', None)
                    if state:
                        positions_by_symbol = getattr(state, 'positions_by_symbol', {}) or {}
            except Exception:
                pass
            
            skew_payload = self.build_position_skew_artifacts_payload(
                positions_by_symbol=positions_by_symbol, decision=decision
            )
            payload["position_skew"] = skew_payload
        except Exception:
            print("WARN artifacts: section 'position_skew' missing, writing {}")
            payload["position_skew"] = {}
        
        # runtime section (always present)
        payload["runtime"] = {
            "utc": utc_now_str(),
            "version": VERSION,
            "git_sha": get_git_sha_short(),
            "mode": get_mode(),
            "env": get_env()
        }
        
        return payload

    def export_unified_artifacts(self, path: str = "artifacts/metrics.json") -> None:
        """Export unified artifacts to JSON file using atomic writer."""
        try:
            payload = self.build_unified_artifacts_payload()
            from src.common.artifacts import write_json_atomic
            write_json_atomic(path, payload)
        except Exception as e:
            print(f"ERROR artifacts: failed to export {path}: {e}")

    # ---- Admin helpers
    def inc_admin_rate_limited(self, endpoint: str) -> None:
        try:
            self.admin_rate_limited_total.labels(endpoint=str(endpoint)).inc()
        except Exception:
            pass

    def inc_admin_audit_event(self, endpoint: str) -> None:
        try:
            self.admin_audit_events_total.labels(endpoint=str(endpoint)).inc()
        except Exception:
            pass

    def inc_admin_alert_event(self, kind: str) -> None:
        try:
            self.admin_alert_events_total.labels(kind=str(kind)).inc()
        except Exception:
            pass

    # ---- Rollout state snapshot helpers
    def inc_rollout_state_snapshot_write(self, ok: bool, ts: float) -> None:
        try:
            if ok:
                self.rollout_state_snapshot_writes_total.inc()
            else:
                self.rollout_state_snapshot_writes_failed_total.inc()
            self._rollout_state_last_write_ts = float(ts)
            self.rollout_state_snapshot_mtime_seconds.labels(op='write').set(float(ts))
        except Exception:
            pass

    def inc_rollout_state_snapshot_load(self, ok: bool, ts: float) -> None:
        try:
            if ok:
                self.rollout_state_snapshot_loads_total.inc()
            else:
                self.rollout_state_snapshot_loads_failed_total.inc()
            self._rollout_state_last_load_ts = float(ts)
            self.rollout_state_snapshot_mtime_seconds.labels(op='load').set(float(ts))
        except Exception:
            pass

    # Testing helper snapshot
    def _get_rollout_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                return {
                    "fills": dict(self._rollout_fills),
                    "rejects": dict(self._rollout_rejects),
                    "latency_ewma": dict(self._rollout_latency_ewma),
                    "split": int(self.rollout_traffic_split_pct._value.get()),  # type: ignore[attr-defined]
                    "observed": float(self.rollout_split_observed_pct._value.get()),  # type: ignore[attr-defined]
                }
        except Exception:
            # Fallback without direct gauge read
            with self._pm_lock:
                return {
                    "fills": dict(self._rollout_fills),
                    "rejects": dict(self._rollout_rejects),
                    "latency_ewma": dict(self._rollout_latency_ewma),
                    "split": 0,
                    "observed": 0.0,
                }

    # ---- Testing seed/reset hooks (stdlib-only) ----
    def test_seed_rollout_counters(
        self,
        *,
        fills_blue: int = 0,
        fills_green: int = 0,
        rejects_blue: int = 0,
        rejects_green: int = 0,
        split_expected_pct: int | float | None = None,
        observed_green_pct: float | None = None,
    ) -> None:
        """Seed rollout fills/reject counters for tests and update relevant gauges.

        Args:
            fills_blue: Number of BLUE fills.
            fills_green: Number of GREEN fills.
            rejects_blue: Number of BLUE rejects.
            rejects_green: Number of GREEN rejects.
            split_expected_pct: Optional expected GREEN split percent for the gauge.
            observed_green_pct: Optional observed GREEN orders percent for the gauge.
        """
        try:
            with self._pm_lock:
                self._rollout_fills["blue"] = int(max(0, fills_blue))
                self._rollout_fills["green"] = int(max(0, fills_green))
                self._rollout_rejects["blue"] = int(max(0, rejects_blue))
                self._rollout_rejects["green"] = int(max(0, rejects_green))
                # Update gauges deterministically
                # Expected split (0..100)
                if split_expected_pct is None:
                    exp = 0
                else:
                    exp = int(max(0, min(100, int(split_expected_pct))))
                self.rollout_traffic_split_pct.set(exp)
                # Observed percent of GREEN orders: derive if not provided
                if observed_green_pct is None:
                    denom = float(
                        self._rollout_fills.get("green", 0)
                        + self._rollout_fills.get("blue", 0)
                        + self._rollout_rejects.get("green", 0)
                        + self._rollout_rejects.get("blue", 0)
                    )
                    obs = 0.0 if denom <= 0.0 else (100.0 * float(self._rollout_fills.get("green", 0) + self._rollout_rejects.get("green", 0)) / denom)
                else:
                    obs = float(max(0.0, min(100.0, float(observed_green_pct))))
                self.rollout_split_observed_pct.set(obs)
        except Exception:
            pass

    def test_seed_rollout_latency_ms(self, *, blue_ms: float = 0.0, green_ms: float = 0.0) -> None:
        """Seed rollout latency EWMA values and update gauges for tests."""
        try:
            with self._pm_lock:
                lb = float(max(0.0, blue_ms))
                lg = float(max(0.0, green_ms))
                self._rollout_latency_ewma["blue"] = lb
                self._rollout_latency_ewma["green"] = lg
                self.rollout_avg_latency_ms.labels(color="blue").set(lb)
                self.rollout_avg_latency_ms.labels(color="green").set(lg)
        except Exception:
            pass

    def test_set_rollout_split_observed_pct(self, obs_pct: float, sample_total: int) -> None:
        """Set observed GREEN split percent and backfill orders sample for tests.

        - Clamps obs_pct to [0,100]
        - Clamps sample_total to >=0
        - Sets internal orders counts so that blue+green == sample_total and
          observed ~= obs_pct (integer rounding)
        - Updates rollout_split_observed_pct gauge
        """
        try:
            with self._pm_lock:
                vv = float(max(0.0, min(100.0, float(obs_pct))))
                tot = int(max(0, int(sample_total)))
                green = int(round(tot * (vv / 100.0)))
                green = max(0, min(tot, green))
                blue = int(tot - green)
                self._rollout_orders_count["green"] = int(green)
                self._rollout_orders_count["blue"] = int(blue)
                self.rollout_split_observed_pct.set(vv)
        except Exception:
            pass

    def test_reset_rollout(self) -> None:
        """Reset all rollout-related internal counters/gauges for tests."""
        try:
            with self._pm_lock:
                self._rollout_fills.clear()
                self._rollout_rejects.clear()
                self._rollout_latency_ewma.clear()
                # Reset gauges to 0 deterministically
                try:
                    self.rollout_traffic_split_pct.set(0)
                except Exception:
                    pass
                try:
                    self.rollout_split_observed_pct.set(0.0)
                except Exception:
                    pass
                try:
                    self.rollout_avg_latency_ms.labels(color="blue").set(0.0)
                    self.rollout_avg_latency_ms.labels(color="green").set(0.0)
                except Exception:
                    pass
        except Exception:
            pass

    # ---- Rollout ramp helpers ----
    def set_ramp_enabled(self, enabled: bool) -> None:
        try:
            self.rollout_ramp_enabled.set(1 if enabled else 0)
        except Exception:
            pass

    def set_ramp_step_idx(self, idx: int) -> None:
        try:
            self.rollout_ramp_step_idx.set(int(max(0, idx)))
        except Exception:
            pass

    def inc_ramp_transition(self, direction: str) -> None:
        try:
            self.rollout_ramp_transitions_total.labels(direction=str(direction)).inc()
        except Exception:
            pass

    def inc_ramp_rollback(self) -> None:
        try:
            self.rollout_ramp_rollbacks_total.inc()
        except Exception:
            pass

    def inc_ramp_hold(self, reason: str) -> None:
        try:
            self.rollout_ramp_holds_total.labels(reason=str(reason)).inc()
            # Track internal counts for canary snapshots/tests
            r = str(reason)
            self._ramp_holds_counts[r] = int(self._ramp_holds_counts.get(r, 0)) + 1
        except Exception:
            pass

    def set_ramp_cooldown_seconds(self, v: float) -> None:
        try:
            self.rollout_ramp_cooldown_seconds.set(max(0.0, float(v)))
        except Exception:
            pass

    def inc_ramp_snapshot_write(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.rollout_ramp_snapshot_writes_total.inc()
                    self._ramp_last_write_ts = float(ts)
                    self.rollout_ramp_snapshot_mtime_seconds.labels(op='write').set(float(ts))
                else:
                    self.rollout_ramp_snapshot_writes_failed_total.inc()
        except Exception:
            pass

    def inc_ramp_snapshot_load(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.rollout_ramp_snapshot_loads_total.inc()
                    self._ramp_last_load_ts = float(ts)
                    self.rollout_ramp_snapshot_mtime_seconds.labels(op='load').set(float(ts))
                else:
                    self.rollout_ramp_snapshot_loads_failed_total.inc()
        except Exception:
            pass

    # ---- Cost calibration snapshot helpers ----
    def inc_cost_calib_snapshot_load(self, ok: bool, ts: float) -> None:
        try:
            with self._pm_lock:
                if ok:
                    self.cost_calib_snapshot_loads_total.inc()
                else:
                    self.cost_calib_snapshot_loads_failed_total.inc()
        except Exception:
            pass

    def inc_ramp_freeze(self) -> None:
        try:
            self.rollout_ramp_freezes_total.inc()
        except Exception:
            pass

    def set_ramp_frozen(self, state: bool) -> None:
        try:
            self.rollout_ramp_frozen.set(1 if state else 0)
        except Exception:
            pass
    
    def update_market_metrics(self, symbol: str, spread_bps: float, vola_1m: float, ob_imbalance: float) -> None:
        """Update market metrics."""
        self.spread_bps.labels(symbol=symbol).set(spread_bps)
        self.vola_1m.labels(symbol=symbol).set(vola_1m)
        self.ob_imbalance.labels(symbol=symbol).set(ob_imbalance)
    
    def update_risk_metrics(self, risk_paused: bool, drawdown_day: float) -> None:
        """Update risk metrics."""
        self.risk_paused.set(1 if risk_paused else 0)
        self.drawdown_day.set(drawdown_day)
    
    def update_connectivity_metrics(self, exchange: str, ws_reconnects: int, rest_error_rate: float) -> None:
        """Update connectivity metrics."""
        self.ws_reconnects_total.labels(exchange=exchange).set(ws_reconnects)
        self.rest_error_rate.labels(exchange=exchange).set(rest_error_rate)
    
    def update_active_orders(self, symbol: str, side: str, count: int) -> None:
        """Update active orders count."""
        self.orders_active.labels(symbol=symbol, side=side).set(count)
    
    def update_queue_pos_delta(self, symbol: str, side: str, delta: float) -> None:
        """Update queue position delta metric."""
        self.queue_pos_delta.labels(symbol=symbol, side=side).set(delta)
    
    def update_pnl_metrics(self, symbol: str, maker_pnl: float, taker_fees: float, inventory_abs: float) -> None:
        """Update P&L and inventory metrics."""
        self.maker_pnl.labels(symbol=symbol).set(maker_pnl)
        self.taker_fees.labels(symbol=symbol).set(taker_fees)
        self.inventory_abs.labels(symbol=symbol).set(inventory_abs)
    
    def _update_create_rate(self, symbol: str) -> None:
        """Update create rate based on recent timestamps."""
        if symbol not in self._create_timestamps:
            self._create_timestamps[symbol] = deque(maxlen=100)
        
        now = time.time()
        self._create_timestamps[symbol].append(now)
        
        # Update rate (orders per second over last 10 seconds)
        recent = [ts for ts in self._create_timestamps[symbol] if now - ts <= 10.0]
        rate = len(recent) / 10.0 if recent else 0.0
        self.create_rate.labels(symbol=symbol).set(rate)
    
    def _update_cancel_rate(self, symbol: str) -> None:
        """Update cancel rate based on recent timestamps."""
        if symbol not in self._cancel_timestamps:
            self._cancel_timestamps[symbol] = deque(maxlen=100)
        
        now = time.time()
        self._cancel_timestamps[symbol].append(now)
        
        # Update rate
        recent = [ts for ts in self._cancel_timestamps[symbol] if now - ts <= 10.0]
        rate = len(recent) / 10.0 if recent else 0.0
        self.cancel_rate.labels(symbol=symbol).set(rate)

    # ---- L6.3: Fill-rate helpers ----
    def record_fill_event(self, symbol: str, filled: bool, ts: float | None = None) -> None:
        try:
            import time as _t
            s = str(symbol)
            now = float(ts) if ts is not None else _t.time()
            with self._pm_lock:
                prev_ts = float(self._fillrate_last_ts.get(s, 0.0))
                self._fillrate_last_ts[s] = now
                prev = float(self._fillrate_ewma.get(s, 1.0))
                # cfg lookup for half-life
                hl = 600.0
                try:
                    hl = float(getattr(getattr(self.ctx, 'cfg', object()), 'portfolio').cost.fill_rate_half_life_sec)  # type: ignore[attr-defined]
                except Exception:
                    hl = 600.0
                if hl < 10.0:
                    hl = 10.0
                # time-decay alpha from half-life: decay=2^(-dt/hl); ew = decay*prev + (1-decay)*x
                dt = 0.0 if prev_ts <= 0.0 else max(0.0, now - prev_ts)
                decay = 0.0 if hl <= 0.0 else (2.0 ** (-(dt / hl)))
                x = 1.0 if filled else 0.0
                ew = decay * prev + (1.0 - decay) * x
                # clamp r to [0,1]
                if ew < 0.0:
                    ew = 0.0
                if ew > 1.0:
                    ew = 1.0
                self._fillrate_ewma[s] = float(ew)
                self._fillrate_samples[s] = int(self._fillrate_samples.get(s, 0)) + 1
                # export
                self.cost_fillrate_ewma.labels(symbol=s).set(float(ew))
                self.cost_fillrate_samples_total.labels(symbol=s).inc()
        except Exception:
            pass

    def get_cost_fillrate_snapshot_for_tests(self) -> Dict[str, Dict[str, float]]:
        try:
            with self._pm_lock:
                out_r = {}
                out_n = {}
                for s in sorted(self._fillrate_ewma.keys() | self._fillrate_samples.keys()):
                    out_r[s] = float(self._fillrate_ewma.get(s, 1.0))
                    out_n[s] = int(self._fillrate_samples.get(s, 0))
                return {"r": out_r, "samples": out_n}
        except Exception:
            return {"r": {}, "samples": {}}

    def reset_cost_fillrate_for_tests(self) -> None:
        try:
            with self._pm_lock:
                self._fillrate_ewma.clear()
                self._fillrate_samples.clear()
                self._fillrate_last_ts.clear()
        except Exception:
            pass

    def record_markout(self, symbol: str, color: str, price_exec: float, mid_t0: float, mid_t200: float, mid_t500: float) -> None:
        """Record markout metrics for execution quality assessment.
        
        Args:
            symbol: Trading symbol
            color: Rollout color (blue/green)
            price_exec: Execution price
            mid_t0: Mid price at execution time
            mid_t200: Mid price at t+200ms
            mid_t500: Mid price at t+500ms
        """
        try:
            with self._pm_lock:
                # Calculate markout values in bps
                markout_200_bps = ((mid_t200 - price_exec) / price_exec) * 10000
                markout_500_bps = ((mid_t500 - price_exec) / price_exec) * 10000
                
                # Update counters
                if markout_200_bps > 0:
                    self.markout_up_total.labels(horizon_ms="200", color=color, symbol=symbol).inc()
                else:
                    self.markout_down_total.labels(horizon_ms="200", color=color, symbol=symbol).inc()
                
                if markout_500_bps > 0:
                    self.markout_up_total.labels(horizon_ms="500", color=color, symbol=symbol).inc()
                else:
                    self.markout_down_total.labels(horizon_ms="500", color=color, symbol=symbol).inc()
                
                # Update internal state for averaging (fixed-point integers for determinism)
                for horizon_ms, markout_bps in [("200", markout_200_bps), ("500", markout_500_bps)]:
                    if horizon_ms not in self._markout_bps_sum_i:
                        self._markout_bps_sum_i[horizon_ms] = {}
                        self._markout_count[horizon_ms] = {}
                    
                    if color not in self._markout_bps_sum_i[horizon_ms]:
                        self._markout_bps_sum_i[horizon_ms][color] = {}
                        self._markout_count[horizon_ms][color] = {}
                    
                    if symbol not in self._markout_bps_sum_i[horizon_ms][color]:
                        self._markout_bps_sum_i[horizon_ms][color][symbol] = 0
                        self._markout_count[horizon_ms][color][symbol] = 0
                    
                    # Convert to fixed-point integer (bps * 10000 for precision)
                    markout_bps_int = int(markout_bps * 10000)
                    self._markout_bps_sum_i[horizon_ms][color][symbol] += markout_bps_int
                    self._markout_count[horizon_ms][color][symbol] += 1
                    
                    # Update gauge with current average
                    if self._markout_count[horizon_ms][color][symbol] > 0:
                        avg_bps = self._markout_bps_sum_i[horizon_ms][color][symbol] / (self._markout_count[horizon_ms][color][symbol] * 10000)
                        self.markout_avg_bps.labels(horizon_ms=horizon_ms, color=color, symbol=symbol).set(avg_bps)
                    
                    # Update samples total gauge (M1.1)
                    total_samples = sum(self._markout_count[horizon_ms][color].values())
                    self.markout_samples_total.labels(horizon_ms=horizon_ms, color=color).set(total_samples)
                        
        except Exception as e:
            self._rate_logger.warn_once(f"Failed to record markout: {e}")

    def _get_markout_snapshot_for_tests(self) -> Dict[str, Any]:
        """Get markout snapshot for testing (deterministic JSON)."""
        try:
            with self._pm_lock:
                result = {}
                for horizon_ms in ["200", "500"]:
                    result[horizon_ms] = {}
                    for color in ["blue", "green"]:
                        result[horizon_ms][color] = {}
                        # Add samples total for gate evaluation
                        total_samples = sum(self._markout_count.get(horizon_ms, {}).get(color, {}).values())
                        result[horizon_ms][color]["samples"] = total_samples
                        
                        for symbol in sorted(self._markout_count.get(horizon_ms, {}).get(color, {}).keys()):
                            count = self._markout_count[horizon_ms][color][symbol]
                            if count > 0:
                                avg_bps = self._markout_bps_sum_i[horizon_ms][color][symbol] / (count * 10000)
                                result[horizon_ms][color][symbol] = {
                                    "count": count,
                                    "avg_bps": round(avg_bps, 6),
                                    "sum_bps_int": self._markout_bps_sum_i[horizon_ms][color][symbol]
                                }
                return result
        except Exception:
            return {}

    def on_replace_allowed(self, symbol: str, per_min: float) -> None:
        try:
            self.replace_rate_per_min.labels(symbol=symbol).set(self._finite(per_min))
        except Exception:
            pass
    
    def on_batch_cancel(self, symbol: str, batch_size: int) -> None:
        try:
            if batch_size > 0:
                self.cancel_batch_events_total.labels(symbol=symbol).inc()
        except Exception:
            pass
    
    def set_order_age_p95(self, symbol: str, p95_ms: float) -> None:
        try:
            self.order_age_p95_ms.labels(symbol=symbol).set(self._finite(p95_ms))
        except Exception:
            pass
    
    # ---- HA helper setters ----
    def set_leader_state(self, *, env: str, service: str, instance: str, state: float) -> None:
        try:
            self.leader_state.labels(env=str(env), service=str(service), instance=str(instance)).set(self._finite(state))
        except Exception:
            pass

    def inc_leader_elections(self, *, env: str, service: str) -> None:
        try:
            self.leader_elections_total.labels(env=str(env), service=str(service)).inc()
        except Exception:
            pass

    def inc_leader_renew_fail(self, *, env: str, service: str) -> None:
        try:
            self.leader_renew_fail_total.labels(env=str(env), service=str(service)).inc()
        except Exception:
            pass

    def inc_order_idem_hit(self, *, env: str, service: str, op: str) -> None:
        try:
            self.order_idem_hits_total.labels(env=str(env), service=str(service), op=str(op)).inc()
        except Exception:
            pass

    # --- MICRO_SIGNALS helpers ---
    def set_micro_bias_strength(self, *, symbol: str, v: float) -> None:
        try:
            self.micro_bias_strength.labels(symbol=str(symbol)).set(self._finite(v))
        except Exception:
            pass

    def set_adverse_fill_rate(self, *, symbol: str, v: float) -> None:
        try:
            self.adverse_fill_rate.labels(symbol=str(symbol)).set(self._finite(v))
        except Exception:
            pass


class MetricsExporter:
    """Legacy wrapper for backward compatibility."""
    
    def __init__(self, config, data_recorder):
        """Initialize exporter."""
        self.config = config
        self.data_recorder = data_recorder
        self.metrics: Optional[Metrics] = None
    
    def set_metrics(self, metrics: Metrics) -> None:
        """Set metrics instance."""
        self.metrics = metrics
    
    def export_cfg_gauges(self, cfg: AppConfig) -> None:
        """Export config gauges."""
        if self.metrics:
            self.metrics.export_cfg_gauges(cfg)
    
    def update_connection_status(self, status: Dict[str, str]) -> None:
        """Update connection status metrics."""
        if self.metrics:
            # Extract exchange from config or use default
            exchange = getattr(self.config, 'exchange', 'bybit')
            ws_reconnects = 1 if status.get('ws') == 'down' else 0
            rest_error_rate = 1.0 if status.get('rest') == 'down' else 0.0
            self.metrics.update_connectivity_metrics(exchange, ws_reconnects, rest_error_rate)


# --- Module-level F2 gate counters for tests and lightweight usage (stdlib-only) ---
_F2_GATE_PASS: Dict[str, int] = {}
_F2_GATE_FAIL: Dict[Tuple[str, str], int] = {}
_F2_LOCK = threading.Lock()


def inc_f2_gate_pass(symbol: str) -> None:
    s = str(symbol)
    with _F2_LOCK:
        _F2_GATE_PASS[s] = _F2_GATE_PASS.get(s, 0) + 1


def inc_f2_gate_fail(symbol: str, reason: str) -> None:
    key = (str(symbol), str(reason))
    with _F2_LOCK:
        _F2_GATE_FAIL[key] = _F2_GATE_FAIL.get(key, 0) + 1


def _reset_f2_gate_metrics_for_tests() -> None:
    with _F2_LOCK:
        _F2_GATE_PASS.clear()
        _F2_GATE_FAIL.clear()


def _get_f2_gate_metrics_snapshot_for_tests() -> Dict[str, Dict]:
    with _F2_LOCK:
        return {
            "pass": dict(_F2_GATE_PASS),
            "fail": dict(_F2_GATE_FAIL),
        }

# Module-level thresholds reload counters for tests/CLI (stdlib-only)
_thresholds_reload_total: Dict[str, int] = {"ok": 0, "failed": 0}
_thresholds_version: int = 0
_THR_LOCK = threading.Lock()


def inc_thresholds_reload(ok: bool) -> None:
    with _THR_LOCK:
        global _thresholds_reload_total
        key = 'ok' if ok else 'failed'
        _thresholds_reload_total[key] = int(_thresholds_reload_total.get(key, 0)) + 1


def set_thresholds_version(v: int) -> None:
    with _THR_LOCK:
        global _thresholds_version
        _thresholds_version = int(v)


def _reset_thresholds_metrics_for_tests() -> None:
    with _THR_LOCK:
        global _thresholds_reload_total, _thresholds_version
        _thresholds_reload_total = {"ok": 0, "failed": 0}
        _thresholds_version = 0


def _get_thresholds_metrics_snapshot_for_tests() -> Dict[str, Dict[str, int]]:
    with _THR_LOCK:
        return {"reload": dict(_thresholds_reload_total), "version": int(_thresholds_version)}
