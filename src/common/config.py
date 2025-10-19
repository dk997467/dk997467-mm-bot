"""
Configuration management for the market maker bot.

Adds:
- AppConfig with versioning and strict validation
- Unknown-key detection (fail-fast)
- Invariants validation
- Runtime mutability whitelist and helpers
- Sanitized hashing helpers and git SHA helper
- Secure secret loading from Docker Secrets or env vars
"""

import os
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field, asdict, is_dataclass

import yaml
import orjson
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


def _load_secret(env_var: str, default: str = '') -> str:
    """
    Load secret from Docker Secret file if available, otherwise from environment variable.
    
    Priority order:
    1. /run/secrets/<secret_name> (Docker Swarm secrets)
    2. {ENV_VAR}_FILE environment variable pointing to a file
    3. {ENV_VAR} environment variable
    4. default value
    
    This provides security for production (Docker Secrets) while maintaining
    dev/test compatibility (environment variables).
    
    Args:
        env_var: Name of environment variable (e.g., 'BYBIT_API_KEY')
        default: Default value if secret not found
    
    Returns:
        Secret value as string
    
    Examples:
        >>> _load_secret('BYBIT_API_KEY')  # Production with Docker Secrets
        'real_api_key_from_file'
        >>> _load_secret('BYBIT_API_KEY')  # Dev with env vars
        'test_api_key_from_env'
    """
    # Priority 1: Check for _FILE suffix env var (Docker Secrets pattern)
    file_var = f"{env_var}_FILE"
    secret_path = os.getenv(file_var)
    
    if secret_path:
        try:
            with open(secret_path, 'r', encoding='utf-8') as f:
                secret = f.read().strip()
            if secret:
                logger.debug(f"Loaded {env_var} from file: {secret_path}")
                return secret
        except FileNotFoundError:
            logger.warning(f"Secret file not found: {secret_path} (from {file_var})")
        except Exception as e:
            logger.error(f"Failed to read secret from {secret_path}: {e}")
    
    # Priority 2: Try standard Docker Swarm secrets location
    docker_secret_path = f"/run/secrets/{env_var.lower()}"
    if os.path.exists(docker_secret_path):
        try:
            with open(docker_secret_path, 'r', encoding='utf-8') as f:
                secret = f.read().strip()
            if secret:
                logger.debug(f"Loaded {env_var} from Docker secret: {docker_secret_path}")
                return secret
        except Exception as e:
            logger.error(f"Failed to read Docker secret from {docker_secret_path}: {e}")
    
    # Priority 3: Fall back to environment variable (dev/test mode)
    env_value = os.getenv(env_var)
    if env_value:
        logger.debug(f"Loaded {env_var} from environment variable")
        return env_value
    
    # Priority 4: Return default
    if default:
        logger.debug(f"Using default value for {env_var}")
    else:
        logger.warning(f"No value found for {env_var} (not in secrets or env)")
    
    return default

def _normalize_fees_section(yaml_config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize fees section in-place and return updated dict.

    - Move fees.k_vola_spread -> strategy.k_vola_spread if not set in strategy
    - Filter unknown keys in fees, allowing only {"bybit"}
    """
    cfg = yaml_config
    try:
        fees_raw = dict((cfg.get('fees') or {}))
        strategy_raw = dict((cfg.get('strategy') or {}))
        moved = False
        if 'k_vola_spread' in fees_raw and 'k_vola_spread' not in strategy_raw:
            strategy_raw['k_vola_spread'] = fees_raw.get('k_vola_spread')
            moved = True
            fees_raw.pop('k_vola_spread', None)
        allowed = {'bybit'}
        filtered_fees = {k: v for k, v in fees_raw.items() if k in allowed}
        cfg['strategy'] = strategy_raw
        cfg['fees'] = filtered_fees
        if moved:
            logger.info("Config fees-section normalized")
            logger.debug("moved=k_vola_spread value=%s", strategy_raw.get('k_vola_spread'))
    except Exception:
        logger.debug("fees-section normalization skipped due to exception")
    return cfg


class Side(str):
    """Trading side."""
    BUY = "Buy"
    SELL = "Sell"


class TimeInForce(str):
    """Time in force for orders."""
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


@dataclass
class StrategyConfig:
    """Strategy configuration with feature flags."""
    # Feature flags
    enable_enhanced_quoting: bool = False  # New feature flag for EnhancedQuoter
    enable_dynamic_spread: bool = True
    enable_inventory_skew: bool = True
    enable_adverse_guard: bool = True
    
    # Spread parameters
    k_vola_spread: float = 0.95
    min_spread_bps: int = 2
    max_spread_bps: int = 25
    
    # Inventory skew
    skew_coeff: float = 0.3
    imbalance_cutoff: float = 0.65
    
    # Order book levels
    levels_per_side: int = 3
    level_spacing_coeff: float = 0.4
    
    # Volatility parameters
    vola_half_life_s: int = 60
    microprice_drift_bps: int = 3
    imbalance_levels: int = 5
    guard_pause_ms: int = 300
    
    # Order management
    min_time_in_book_ms: int = 500
    replace_threshold_bps: int = 3
    
    # Research and backtesting parameters
    slip_bps: float = 2.0  # Estimated slippage in basis points
    
    # Legacy parameters (kept for backward compatibility)
    volatility_lookback_sec: int = 30
    imbalance_weight: float = 0.4
    microprice_weight: float = 0.6
    k_vola: float = 0.5
    k_imb: float = 0.2
    t_imb: float = 0.1
    risk_buffer_bps: float = 2.0
    skew_k: float = 0.1
    max_skew_bps: float = 30.0
    max_quote_levels: int = 3
    max_active_orders_per_symbol: int = 30
    max_new_orders_per_sec: float = 5.0
    quote_refresh_ms: int = 800
    amend_price_threshold_bps: float = 1.0
    amend_size_threshold: float = 0.2
    cancel_stale_ms: int = 60000
    backoff_on_reject_ms: int = 1500
    
    # Anti-stale order guard configuration
    order_ttl_ms: int = 800  # Order TTL in milliseconds (default: 800ms)
    price_drift_bps: float = 2.0  # Price drift threshold in bps (default: 2.0 bps)
    enable_anti_stale_guard: bool = True  # Enable/disable anti-stale order guard
    
    def __post_init__(self):
        """Validate configuration values."""
        # Load from environment variables if available
        self.order_ttl_ms = int(os.getenv('ORDER_TTL_MS', self.order_ttl_ms))
        self.price_drift_bps = float(os.getenv('PRICE_DRIFT_BPS', self.price_drift_bps))
        self.enable_anti_stale_guard = os.getenv('ENABLE_ANTI_STALE_GUARD', 'true').lower() == 'true'
        
        if self.min_spread_bps < 0:
            raise ValueError("min_spread_bps must be >= 0")
        if self.max_spread_bps <= self.min_spread_bps:
            raise ValueError("max_spread_bps must be > min_spread_bps")
        if self.levels_per_side < 1 or self.levels_per_side > 10:
            raise ValueError("levels_per_side must be between 1 and 10")
        if self.skew_coeff < 0 or self.skew_coeff > 1:
            raise ValueError("skew_coeff must be between 0 and 1")
        if self.imbalance_cutoff < 0.5 or self.imbalance_cutoff > 0.9:
            raise ValueError("imbalance_cutoff must be between 0.5 and 0.9")
        if self.vola_half_life_s < 10 or self.vola_half_life_s > 300:
            raise ValueError("vola_half_life_s must be between 10 and 300")
        if self.microprice_drift_bps < 1 or self.microprice_drift_bps > 10:
            raise ValueError("microprice_drift_bps must be between 1 and 10")
        if self.imbalance_levels < 3 or self.imbalance_levels > 10:
            raise ValueError("imbalance_levels must be between 3 and 10")
        if self.guard_pause_ms < 100 or self.guard_pause_ms > 1000:
            raise ValueError("guard_pause_ms must be between 100 and 1000")


@dataclass
class ConnectionPoolConfig:
    """HTTP connection pooling configuration for REST API connector.
    
    Optimizes connection reuse to reduce latency and resource usage.
    Configured based on Bybit API best practices and high-frequency trading requirements.
    """
    # Connection limits
    limit: int = 100  # Total connection pool limit
    limit_per_host: int = 30  # Max connections per host (Bybit API)
    
    # Timeouts (in seconds)
    connect_timeout: float = 10.0  # TCP connection timeout
    sock_read_timeout: float = 30.0  # Socket read timeout
    total_timeout: float = 60.0  # Total request timeout
    
    # DNS and keepalive
    ttl_dns_cache: int = 300  # DNS cache TTL (5 minutes)
    keepalive_timeout: float = 30.0  # TCP keepalive timeout
    
    # Connection management
    enable_cleanup_closed: bool = True  # Cleanup closed connections
    force_close: bool = False  # Close connections after each request (disable pooling if True)
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.limit < 1:
            raise ValueError("ConnectionPoolConfig.limit must be >= 1")
        if self.limit_per_host < 1 or self.limit_per_host > self.limit:
            raise ValueError("ConnectionPoolConfig.limit_per_host must be between 1 and limit")
        if self.connect_timeout <= 0 or self.connect_timeout > self.total_timeout:
            raise ValueError("ConnectionPoolConfig.connect_timeout must be > 0 and <= total_timeout")
        if self.sock_read_timeout <= 0 or self.sock_read_timeout > self.total_timeout:
            raise ValueError("ConnectionPoolConfig.sock_read_timeout must be > 0 and <= total_timeout")
        if self.total_timeout <= 0:
            raise ValueError("ConnectionPoolConfig.total_timeout must be > 0")
        if self.ttl_dns_cache < 0:
            raise ValueError("ConnectionPoolConfig.ttl_dns_cache must be >= 0")
        if self.keepalive_timeout <= 0:
            raise ValueError("ConnectionPoolConfig.keepalive_timeout must be > 0")


@dataclass
class PosSkewConfig:
    per_symbol_abs_limit: float = 0.0
    per_color_abs_limit: float = 0.0

    def __post_init__(self):
        try:
            self.per_symbol_abs_limit = float(self.per_symbol_abs_limit)
        except Exception:
            raise ValueError("E_CFG_TYPE:per_symbol_abs_limit must be a float")
        try:
            self.per_color_abs_limit = float(self.per_color_abs_limit)
        except Exception:
            raise ValueError("E_CFG_TYPE:per_color_abs_limit must be a float")
        if self.per_symbol_abs_limit < 0.0:
            raise ValueError("E_CFG_RANGE:per_symbol_abs_limit must be >= 0.0")
        if self.per_color_abs_limit < 0.0:
            raise ValueError("E_CFG_RANGE:per_color_abs_limit must be >= 0.0")


@dataclass
class IntradayCapsConfig:
    daily_pnl_stop: float = 0.0
    daily_turnover_cap: float = 0.0
    daily_vol_cap: float = 0.0

    def __post_init__(self):
        try:
            self.daily_pnl_stop = float(self.daily_pnl_stop)
        except Exception:
            raise ValueError("E_CFG_TYPE:daily_pnl_stop must be a float")
        try:
            self.daily_turnover_cap = float(self.daily_turnover_cap)
        except Exception:
            raise ValueError("E_CFG_TYPE:daily_turnover_cap must be a float")
        try:
            self.daily_vol_cap = float(self.daily_vol_cap)
        except Exception:
            raise ValueError("E_CFG_TYPE:daily_vol_cap must be a float")
        if self.daily_pnl_stop < 0.0:
            raise ValueError("E_CFG_RANGE:daily_pnl_stop must be >= 0.0")
        if self.daily_turnover_cap < 0.0:
            raise ValueError("E_CFG_RANGE:daily_turnover_cap must be >= 0.0")
        if self.daily_vol_cap < 0.0:
            raise ValueError("E_CFG_RANGE:daily_vol_cap must be >= 0.0")


@dataclass
class GuardsConfig:
    pos_skew: PosSkewConfig = field(default_factory=PosSkewConfig)
    intraday_caps: IntradayCapsConfig = field(default_factory=IntradayCapsConfig)


@dataclass
class AllocatorSmoothingConfig:
    bias_cap: float = 0.10  # ratio [0.0,1.0] (alias: bias_cap_ratio)
    fee_bias_cap: float = 0.05  # ratio [0.0,1.0] (alias: fee_bias_cap_ratio, fee_bias_cap_bps)
    max_delta_ratio: float = 0.15
    max_delta_abs_base_units: float = 0.0
    backoff_steps: list = field(default_factory=lambda: [1.0, 0.7, 0.5])

    def __post_init__(self):
        try:
            self.bias_cap = float(self.bias_cap)
        except Exception:
            raise ValueError("E_CFG_TYPE:allocator.smoothing.bias_cap_ratio must be a float")
        if self.bias_cap < 0.0 or self.bias_cap > 1.0:
            raise ValueError("E_CFG_RANGE:allocator.smoothing.bias_cap_ratio must be in [0.0,1.0]")
        try:
            self.fee_bias_cap = float(self.fee_bias_cap)
        except Exception:
            raise ValueError("E_CFG_TYPE:allocator.smoothing.fee_bias_cap_ratio must be a float")
        if self.fee_bias_cap < 0.0 or self.fee_bias_cap > 1.0:
            raise ValueError("E_CFG_RANGE:allocator.smoothing.fee_bias_cap_ratio must be in [0.0,1.0]")
        try:
            self.max_delta_ratio = float(self.max_delta_ratio)
        except Exception:
            raise ValueError("E_CFG_TYPE:allocator.smoothing.max_delta_ratio must be a float")
        if self.max_delta_ratio < 0.0 or self.max_delta_ratio > 1.0:
            raise ValueError("E_CFG_RANGE:allocator.smoothing.max_delta_ratio must be in [0.0,1.0]")
        try:
            self.max_delta_abs_base_units = float(self.max_delta_abs_base_units)
        except Exception:
            raise ValueError("E_CFG_TYPE:allocator.smoothing.max_delta_abs_base_units must be a float")
        if self.max_delta_abs_base_units < 0.0:
            raise ValueError("E_CFG_RANGE:allocator.smoothing.max_delta_abs_base_units must be >= 0.0")
        # backoff_steps
        if not isinstance(self.backoff_steps, list) or len(self.backoff_steps) == 0:
            raise ValueError("E_CFG_TYPE:allocator.smoothing.backoff_steps must be a non-empty list of floats in (0.0,1.0]")
        normalized = []
        for v in self.backoff_steps:
            try:
                fv = float(v)
            except Exception:
                raise ValueError("E_CFG_TYPE:allocator.smoothing.backoff_steps must be a non-empty list of floats in (0.0,1.0]")
            if not (0.0 < fv <= 1.0):
                raise ValueError("E_CFG_RANGE:allocator.smoothing.backoff_steps values must be in (0.0,1.0]")
            normalized.append(fv)
        self.backoff_steps = normalized

@dataclass
class FeesBybitConfig:
    distance_usd_threshold: float = 25000.0
    min_improvement_bps: float = 0.2

    def __post_init__(self):
        try:
            self.distance_usd_threshold = float(self.distance_usd_threshold)
        except Exception:
            raise ValueError("E_CFG_TYPE:distance_usd_threshold must be a float")
        try:
            self.min_improvement_bps = float(self.min_improvement_bps)
        except Exception:
            raise ValueError("E_CFG_TYPE:min_improvement_bps must be a float")
        if self.distance_usd_threshold < 0.0:
            raise ValueError("E_CFG_RANGE:distance_usd_threshold must be >= 0.0")
        if self.min_improvement_bps < 0.0 or self.min_improvement_bps > 1000.0:
            raise ValueError("E_CFG_RANGE:min_improvement_bps must be in [0.0,1000.0]")

@dataclass
class FeesConfig:
    bybit: FeesBybitConfig = field(default_factory=FeesBybitConfig)


@dataclass
class PipelineConfig:
    """Pipeline architecture configuration."""
    enabled: bool = False  # Feature flag: enable pipeline architecture
    sample_stage_tracing: float = 0.2  # Fraction of ticks to trace (0.0-1.0)
    
    def __post_init__(self):
        """Validate pipeline configuration."""
        if not (0.0 <= self.sample_stage_tracing <= 1.0):
            raise ValueError("sample_stage_tracing must be between 0.0 and 1.0")


@dataclass
class MDCacheConfig:
    """Market data cache configuration."""
    enabled: bool = False  # Feature flag: enable MD cache
    ttl_ms: int = 100  # Cache TTL in milliseconds
    max_depth: int = 50  # Max orderbook depth to cache
    stale_ok: bool = True  # Allow stale-while-refresh mode
    invalidate_on_ws_gap_ms: int = 300  # Invalidate if WS gap > this
    max_inflight_refresh: int = 1  # Max concurrent refreshes per symbol
    
    # Freshness safeguards
    fresh_ms_for_pricing: int = 60  # Max age for pricing/spread decisions
    skip_pricing_on_stale: bool = False  # Skip pricing if stale (vs widen spread)
    
    def __post_init__(self):
        """Validate MD cache configuration."""
        if self.ttl_ms < 10 or self.ttl_ms > 5000:
            raise ValueError("ttl_ms must be between 10 and 5000")
        if self.max_depth < 1 or self.max_depth > 200:
            raise ValueError("max_depth must be between 1 and 200")
        if self.invalidate_on_ws_gap_ms < 50 or self.invalidate_on_ws_gap_ms > 10000:
            raise ValueError("invalidate_on_ws_gap_ms must be between 50 and 10000")
        if self.fresh_ms_for_pricing < 10 or self.fresh_ms_for_pricing > self.ttl_ms:
            raise ValueError(f"fresh_ms_for_pricing must be between 10 and {self.ttl_ms}")


@dataclass
class StageBudgetsConfig:
    """Stage performance budgets for CI gates."""
    enabled: bool = True
    regress_pct_threshold: float = 3.0  # Fail if regression > +3%
    baseline_path: str = "artifacts/baseline/stage_budgets.json"
    
    # Default p95 budgets (ms)
    fetch_md_p95_ms: float = 60.0
    spread_p95_ms: float = 15.0
    guards_p95_ms: float = 12.0
    inventory_p95_ms: float = 12.0
    queue_aware_p95_ms: float = 15.0
    emit_p95_ms: float = 35.0
    tick_total_p95_ms: float = 150.0
    
    def __post_init__(self):
        """Validate stage budgets configuration."""
        if self.regress_pct_threshold < 0.0 or self.regress_pct_threshold > 100.0:
            raise ValueError("regress_pct_threshold must be between 0.0 and 100.0")


@dataclass
class SymbolScoreboardConfig:
    """Symbol-level performance scoreboard configuration."""
    enabled: bool = False  # Feature flag
    rolling_window_sec: int = 300  # 5 minutes rolling window
    ema_alpha: float = 0.1  # EMA smoothing factor (0.0-1.0)
    min_samples: int = 10  # Minimum samples before score is valid
    
    # Score weights
    weight_net_bps: float = 0.4
    weight_fill_rate: float = 0.2
    weight_slippage: float = 0.2
    weight_queue_edge: float = 0.1
    weight_adverse_penalty: float = 0.1
    
    def __post_init__(self):
        """Validate scoreboard configuration."""
        if not (0.0 < self.ema_alpha <= 1.0):
            raise ValueError("ema_alpha must be between 0.0 and 1.0")
        if self.rolling_window_sec < 60:
            raise ValueError("rolling_window_sec must be at least 60")
        
        # Validate weights sum to 1.0
        total_weight = (
            self.weight_net_bps + self.weight_fill_rate + 
            self.weight_slippage + self.weight_queue_edge + 
            self.weight_adverse_penalty
        )
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Score weights must sum to 1.0, got {total_weight}")


@dataclass
class DynamicAllocatorConfig:
    """Dynamic allocator configuration for per-symbol limits."""
    enabled: bool = False  # Feature flag
    rebalance_period_s: int = 30  # Rebalance every 30 seconds
    min_weight: float = 0.1  # Minimum weight (clamp)
    max_weight: float = 3.0  # Maximum weight (clamp)
    hysteresis_threshold: float = 0.05  # Minimum change to trigger rebalance
    
    # Whitelist/Blacklist
    whitelist: List[str] = field(default_factory=list)  # Only trade these symbols
    blacklist: List[str] = field(default_factory=list)  # Never trade these symbols
    
    # Auto-blacklist thresholds
    auto_blacklist_net_bps: float = -5.0  # Blacklist if net_bps < -5.0 consistently
    auto_blacklist_window_min: int = 30  # Over 30 minute window
    
    def __post_init__(self):
        """Validate allocator configuration."""
        if self.rebalance_period_s < 10:
            raise ValueError("rebalance_period_s must be at least 10")
        if not (0.0 < self.min_weight < self.max_weight):
            raise ValueError("Must have 0 < min_weight < max_weight")
        if not (0.0 <= self.hysteresis_threshold <= 1.0):
            raise ValueError("hysteresis_threshold must be between 0.0 and 1.0")


@dataclass
class AllocatorConfig:
    smoothing: AllocatorSmoothingConfig = field(default_factory=AllocatorSmoothingConfig)


@dataclass
class RiskConfig:
    """Risk management configuration."""
    # Feature flags
    enable_kill_switch: bool = True
    
    # Kill switch thresholds
    drawdown_day_pct: float = 1.0
    max_consecutive_losses: int = 10
    max_reject_rate: float = 0.02
    max_latency_p95_ms: int = 300
    
    # Legacy parameters
    max_position_usd: float = 5000
    target_inventory_usd: float = 0
    inventory_skew_gamma: float = 0.1
    daily_max_loss_usd: float = 300
    max_cancels_per_min: int = 90
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.drawdown_day_pct < 0.1 or self.drawdown_day_pct > 10.0:
            raise ValueError("drawdown_day_pct must be between 0.1 and 10.0")
        if self.max_consecutive_losses < 1 or self.max_consecutive_losses > 100:
            raise ValueError("max_consecutive_losses must be between 1 and 100")
        if self.max_reject_rate < 0.001 or self.max_reject_rate > 0.1:
            raise ValueError("max_reject_rate must be between 0.001 and 0.1")
        if self.max_latency_p95_ms < 50 or self.max_latency_p95_ms > 1000:
            raise ValueError("max_latency_p95_ms must be between 50 and 1000")


@dataclass
class LimitsConfig:
    """Order and rate limiting configuration."""
    max_active_per_side: int = 3
    max_create_per_sec: float = 4.0
    max_cancel_per_sec: float = 4.0
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.max_active_per_side < 1 or self.max_active_per_side > 20:
            raise ValueError("max_active_per_side must be between 1 and 20")
        if self.max_create_per_sec < 0.1 or self.max_create_per_sec > 20.0:
            raise ValueError("max_create_per_sec must be between 0.1 and 20.0")
        if self.max_cancel_per_sec < 0.1 or self.max_cancel_per_sec > 20.0:
            raise ValueError("max_cancel_per_sec must be between 0.1 and 20.0")


@dataclass
class PortfolioConfig:
    """Portfolio allocation configuration."""
    budget_usd: float = 10000.0
    mode: str = "manual"  # "manual" | "inverse_vol" | "risk_parity"
    manual_weights: Dict[str, float] = field(default_factory=dict)
    min_weight: float = 0.02
    max_weight: float = 0.5
    rebalance_minutes: int = 5
    ema_alpha: float = 0.3
    risk_parity_max_iterations: int = 50
    risk_parity_tolerance: float = 1e-6
    vol_eps: float = 1e-9
    # Levels caps for targets → order manager
    levels_per_side_min: int = 1
    levels_per_side_max: int = 10

@dataclass
class PortfolioBudgetConfig:
    pnl_sensitivity: float = 0.5
    drawdown_soft_cap: float = 0.10
    budget_min_usd: float = 0.0

# Alias to satisfy nested dataclass detection by key name 'budget' -> 'BudgetConfig'
BudgetConfig = PortfolioBudgetConfig

@dataclass
class CostModelConfig:
    fee_bps_default: float = 1.0
    slippage_bps_base: float = 0.5
    slippage_k_bps_per_kusd: float = 0.1
    cost_sensitivity: float = 0.5  # 0..1
    use_shadow_spread: bool = True
    use_shadow_volume: bool = True
    min_volume_usd: float = 1000.0
    max_slippage_bps_cap: float = 50.0
    # L6.3 fill-rate aware attenuation (global defaults; can be overridden per symbol)
    fill_rate_half_life_sec: int = 600  # >= 10
    fill_rate_floor: float = 0.7        # 0..1
    fill_rate_sensitivity: float = 0.5  # 0..1
    # L6.4 liquidity-aware sizing (global defaults; can be overridden per symbol)
    liquidity_depth_usd_target: float = 0.0  # >=0, 0 disables
    liquidity_sensitivity: float = 0.0       # 0..1
    liquidity_min_floor: float = 0.0         # 0..1
    # L7 turnover-aware sizing (global defaults; can be overridden per symbol)
    turnover_half_life_sec: int = 600        # >= 10
    turnover_sensitivity: float = 0.0        # 0..1
    turnover_floor: float = 0.0              # 0..1
    per_symbol: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def __post_init__(self):
        # sanitize and validate ranges
        try:
            self.fee_bps_default = float(self.fee_bps_default)
        except Exception:
            self.fee_bps_default = 1.0
        if self.fee_bps_default < 0.0:
            self.fee_bps_default = 0.0
        try:
            self.slippage_bps_base = float(self.slippage_bps_base)
        except Exception:
            self.slippage_bps_base = 0.5
        if self.slippage_bps_base < 0.0:
            self.slippage_bps_base = 0.0
        try:
            self.slippage_k_bps_per_kusd = float(self.slippage_k_bps_per_kusd)
        except Exception:
            self.slippage_k_bps_per_kusd = 0.1
        if self.slippage_k_bps_per_kusd < 0.0:
            self.slippage_k_bps_per_kusd = 0.0
        try:
            self.cost_sensitivity = float(self.cost_sensitivity)
        except Exception:
            self.cost_sensitivity = 0.5
        if self.cost_sensitivity < 0.0:
            self.cost_sensitivity = 0.0
        if self.cost_sensitivity > 1.0:
            self.cost_sensitivity = 1.0
        try:
            self.use_shadow_spread = bool(self.use_shadow_spread)
        except Exception:
            self.use_shadow_spread = True
        try:
            self.use_shadow_volume = bool(self.use_shadow_volume)
        except Exception:
            self.use_shadow_volume = True
        try:
            self.min_volume_usd = float(self.min_volume_usd)
        except Exception:
            self.min_volume_usd = 1000.0
        if self.min_volume_usd < 0.0:
            self.min_volume_usd = 0.0
        try:
            self.max_slippage_bps_cap = float(self.max_slippage_bps_cap)
        except Exception:
            self.max_slippage_bps_cap = 50.0
        if self.max_slippage_bps_cap < 0.0:
            self.max_slippage_bps_cap = 0.0
        # L6.3 validation
        try:
            self.fill_rate_half_life_sec = int(self.fill_rate_half_life_sec)
        except Exception:
            self.fill_rate_half_life_sec = 600
        if self.fill_rate_half_life_sec < 10:
            self.fill_rate_half_life_sec = 10
        try:
            self.fill_rate_floor = float(self.fill_rate_floor)
        except Exception:
            self.fill_rate_floor = 0.7
        if self.fill_rate_floor < 0.0:
            self.fill_rate_floor = 0.0
        if self.fill_rate_floor > 1.0:
            self.fill_rate_floor = 1.0
        try:
            self.fill_rate_sensitivity = float(self.fill_rate_sensitivity)
        except Exception:
            self.fill_rate_sensitivity = 0.5
        if self.fill_rate_sensitivity < 0.0:
            self.fill_rate_sensitivity = 0.0
        if self.fill_rate_sensitivity > 1.0:
            self.fill_rate_sensitivity = 1.0
        # L6.4 validation
        try:
            self.liquidity_depth_usd_target = float(self.liquidity_depth_usd_target)
        except Exception:
            self.liquidity_depth_usd_target = 0.0
        if self.liquidity_depth_usd_target < 0.0:
            self.liquidity_depth_usd_target = 0.0
        try:
            self.liquidity_sensitivity = float(self.liquidity_sensitivity)
        except Exception:
            self.liquidity_sensitivity = 0.0
        if self.liquidity_sensitivity < 0.0:
            self.liquidity_sensitivity = 0.0
        if self.liquidity_sensitivity > 1.0:
            self.liquidity_sensitivity = 1.0
        try:
            self.liquidity_min_floor = float(self.liquidity_min_floor)
        except Exception:
            self.liquidity_min_floor = 0.0
        if self.liquidity_min_floor < 0.0:
            self.liquidity_min_floor = 0.0
        if self.liquidity_min_floor > 1.0:
            self.liquidity_min_floor = 1.0
        # L7 validation
        try:
            self.turnover_half_life_sec = int(self.turnover_half_life_sec)
        except Exception:
            self.turnover_half_life_sec = 600
        if self.turnover_half_life_sec < 10:
            self.turnover_half_life_sec = 10
        try:
            self.turnover_sensitivity = float(self.turnover_sensitivity)
        except Exception:
            self.turnover_sensitivity = 0.0
        if self.turnover_sensitivity < 0.0:
            self.turnover_sensitivity = 0.0
        if self.turnover_sensitivity > 1.0:
            self.turnover_sensitivity = 1.0
        try:
            self.turnover_floor = float(self.turnover_floor)
        except Exception:
            self.turnover_floor = 0.0
        if self.turnover_floor < 0.0:
            self.turnover_floor = 0.0
        if self.turnover_floor > 1.0:
            self.turnover_floor = 1.0

@dataclass
class PortfolioConfig(PortfolioConfig):  # type: ignore[misc]
    # Extend PortfolioConfig with budget subsection (backward-compatible)
    budget: PortfolioBudgetConfig = field(default_factory=PortfolioBudgetConfig)
    cost: CostModelConfig = field(default_factory=CostModelConfig)
@dataclass
class HolidayConfig:
    dates: List[str] = field(default_factory=list)  # 'YYYY-MM-DD'
    symbols: List[str] = field(default_factory=list)  # empty => global


@dataclass
class SchedulerConfig:
    """Time-of-day scheduler configuration."""
    tz: str = "UTC"
    windows: List[Dict[str, Any]] = field(default_factory=list)
    windows_by_symbol: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    cooldown_open_minutes: float = 0.0
    cooldown_close_minutes: float = 0.0
    block_in_cooldown: bool = True
    holidays: List[HolidayConfig] = field(default_factory=list)

    # legacy/misc fields retained to avoid breaking references
    levels_per_side_min: int = 1
    levels_per_side_max: int = 10
    
    def __post_init__(self):
        """Validate scheduler configuration values (non-strict)."""
        if not isinstance(self.tz, str) or not self.tz:
            raise ValueError("scheduler.tz must be a non-empty string")
        if self.cooldown_open_minutes < 0 or self.cooldown_close_minutes < 0:
            raise ValueError("scheduler cooldowns must be >= 0")
        if not isinstance(self.block_in_cooldown, bool):
            raise ValueError("scheduler.block_in_cooldown must be bool")


@dataclass
class SchedulerSuggestConfig:
    enabled: bool = False
    top_k: int = 6
    min_sample: int = 200
    mode: str = "neutral"  # conservative|neutral|aggressive

    def __post_init__(self):
        try:
            self.top_k = int(self.top_k)
        except Exception:
            self.top_k = 6
        if self.top_k < 1:
            self.top_k = 1
        try:
            self.min_sample = int(self.min_sample)
        except Exception:
            self.min_sample = 200
        if self.min_sample < 0:
            self.min_sample = 0
        m = str(self.mode).lower()
        if m not in ("conservative","neutral","aggressive"):
            m = "neutral"
        self.mode = m


@dataclass
class RuntimeGuardConfig:
    enabled: bool = True
    cancel_rate_pct_of_limit_max: float = 90.0
    rest_error_rate_max: float = 0.01
    pnl_slope_min_per_min: float = -0.1
    consecutive_breaches_to_pause: int = 2
    recovery_minutes: float = 5.0
    # L3.2 extensions
    max_position_notional_usd: float = 0.0
    max_gross_exposure_usd: float = 0.0
    max_position_pct_budget: float = 100.0
    cancel_p95_ms_max: float = 0.0
    ws_lag_ms_max: float = 0.0
    order_reject_rate_max: float = 0.0
    hysteresis_good_required: int = 1
    hysteresis_bad_required: int = 3
    window_seconds: int = 300
    max_cancel_latency_ms_p95: float = 60000.0
    per_symbol: Dict[str, Dict[str, float]] = field(default_factory=dict)
    dry_run: bool = False
    manual_override_pause: bool = False
    snapshot_path: str = "artifacts/runtime_guard.json"
    snapshot_period_sec: int = 60


@dataclass
class ThrottleConfig:
    window_sec: float = 10.0
    max_creates_per_sec: float = 5.0
    max_amends_per_sec: float = 10.0
    max_cancels_per_sec: float = 20.0
    per_symbol: bool = True
    backoff_base_ms: int = 200
    backoff_max_ms: int = 3000
    backoff_cap_ms: float = 5000.0
    jitter_pct: float = 0.10
    error_rate_trigger: float = 0.02
    ws_lag_trigger_ms: float = 500


@dataclass
class CircuitConfig:
    window_sec: float = 60.0
    err_rate_open: float = 0.5
    http_5xx_rate_open: float = 0.2
    http_429_rate_open: float = 0.2
    open_duration_sec: float = 30.0
    half_open_probes: int = 5
    cooldown_sec: float = 5.0


@dataclass
class RuntimeShadowConfig:
    enabled: bool = False
    max_price_diff_bps: float = 5.0
    max_size_diff_pct: float = 10.0
    min_count: int = 50


@dataclass
class RolloutConfig:
    """Blue/Green rollout configuration."""
    blue: Dict[str, Any] = field(default_factory=dict)
    green: Dict[str, Any] = field(default_factory=dict)
    traffic_split_pct: int = 0  # 0..100 percentage to route to GREEN
    active: str = "blue"       # baseline color reference: "blue"|"green"
    salt: str = "default"
    pinned_cids_green: List[str] = field(default_factory=list)

    def __post_init__(self):
        try:
            if not isinstance(self.traffic_split_pct, int):
                self.traffic_split_pct = int(self.traffic_split_pct)
        except Exception:
            self.traffic_split_pct = 0
        if self.traffic_split_pct < 0 or self.traffic_split_pct > 100:
            raise ValueError("rollout.traffic_split_pct must be between 0 and 100")
        if str(self.active) not in ("blue", "green"):
            raise ValueError("rollout.active must be 'blue' or 'green'")
        # sanitize salt
        try:
            s = str(getattr(self, 'salt', 'default'))
        except Exception:
            s = 'default'
        if len(s) > 64:
            s = s[:64]
        self.salt = s
        # normalize pinned list
        try:
            lst = list(getattr(self, 'pinned_cids_green', []) or [])
        except Exception:
            lst = []
        norm = []
        seen = set()
        for x in lst:
            try:
                c = str(x).strip()
            except Exception:
                continue
            if not c or c in seen:
                continue
            seen.add(c)
            norm.append(c)
            if len(norm) >= 10000:
                break
        self.pinned_cids_green = norm


@dataclass
class RolloutRampConfig:
    """Configuration for ramping traffic split to GREEN with health checks."""
    enabled: bool = False
    steps_pct: List[int] = field(default_factory=lambda: [0, 5, 10, 25, 50])
    step_interval_sec: int = 600
    max_reject_rate_delta_pct: float = 2.0
    max_latency_delta_ms: int = 50
    max_pnl_delta_usd: float = 0.0
    min_sample_fills: int = 200
    max_step_increase_pct: int = 10
    cooldown_after_rollback_sec: int = 900

    def __post_init__(self):
        # sanitize types and values
        try:
            self.step_interval_sec = int(self.step_interval_sec)
        except Exception:
            self.step_interval_sec = 600
        if self.step_interval_sec < 10:
            raise ValueError("rollout_ramp.step_interval_sec must be >= 10")
        try:
            steps = [int(x) for x in (self.steps_pct or [])]
        except Exception:
            steps = [0, 5, 10, 25, 50]
        steps = sorted(x for x in steps if 0 <= x <= 100)
        if not steps:
            steps = [0]
        self.steps_pct = steps
        # new fields validation
        try:
            self.min_sample_fills = int(self.min_sample_fills)
        except Exception:
            self.min_sample_fills = 200
        if self.min_sample_fills < 0:
            self.min_sample_fills = 0
        try:
            self.max_step_increase_pct = int(self.max_step_increase_pct)
        except Exception:
            self.max_step_increase_pct = 10
        if self.max_step_increase_pct < 0:
            self.max_step_increase_pct = 0
        if self.max_step_increase_pct > 100:
            self.max_step_increase_pct = 100
        try:
            self.cooldown_after_rollback_sec = int(self.cooldown_after_rollback_sec)
        except Exception:
            self.cooldown_after_rollback_sec = 900
        if self.cooldown_after_rollback_sec < 0:
            self.cooldown_after_rollback_sec = 0


@dataclass
class ChaosConfig:
    enabled: bool = False
    reject_inflate_pct: float = 0.0  # 0..1.0
    latency_inflate_ms: int = 0      # 0..10000

    def __post_init__(self):
        try:
            self.reject_inflate_pct = float(self.reject_inflate_pct)
        except Exception:
            self.reject_inflate_pct = 0.0
        if self.reject_inflate_pct < 0.0:
            self.reject_inflate_pct = 0.0
        if self.reject_inflate_pct > 1.0:
            self.reject_inflate_pct = 1.0
        try:
            self.latency_inflate_ms = int(self.latency_inflate_ms)
        except Exception:
            self.latency_inflate_ms = 0
        if self.latency_inflate_ms < 0:
            self.latency_inflate_ms = 0
        if self.latency_inflate_ms > 10000:
            self.latency_inflate_ms = 10000


@dataclass
class CanaryKillSwitchConfig:
    enabled: bool = False
    dry_run: bool = True
    max_reject_delta: float = 0.02
    max_latency_delta_ms: int = 50
    min_fills: int = 500
    action: str = "rollback"  # "rollback"|"freeze"

    def __post_init__(self):
        try:
            self.max_reject_delta = float(self.max_reject_delta)
        except Exception:
            self.max_reject_delta = 0.02
        if self.max_reject_delta < 0.0:
            self.max_reject_delta = 0.0
        try:
            self.max_latency_delta_ms = int(self.max_latency_delta_ms)
        except Exception:
            self.max_latency_delta_ms = 50
        if self.max_latency_delta_ms < 0:
            self.max_latency_delta_ms = 0
        if self.max_latency_delta_ms > 10000:
            self.max_latency_delta_ms = 10000
        try:
            self.min_fills = int(self.min_fills)
        except Exception:
            self.min_fills = 500
        if self.min_fills < 0:
            self.min_fills = 0
        a = str(self.action).lower()
        if a not in ("rollback","freeze"):
            a = "rollback"
        self.action = a


@dataclass
class AutoPromotionConfig:
    enabled: bool = False
    stable_steps_required: int = 6
    min_split_pct: int = 25

    def __post_init__(self):
        try:
            self.stable_steps_required = int(self.stable_steps_required)
        except Exception:
            self.stable_steps_required = 6
        if self.stable_steps_required < 0:
            self.stable_steps_required = 0
        try:
            self.min_split_pct = int(self.min_split_pct)
        except Exception:
            self.min_split_pct = 25
        if self.min_split_pct < 0:
            self.min_split_pct = 0
        if self.min_split_pct > 100:
            self.min_split_pct = 100


@dataclass
class LatencySLOConfig:
    enabled: bool = False
    p95_target_ms: int = 50
    p99_target_ms: int = 100
    window_sec: int = 60
    burn_alert_threshold: float = 1.0

    def __post_init__(self):
        try:
            self.p95_target_ms = int(self.p95_target_ms)
        except Exception:
            self.p95_target_ms = 50
        if self.p95_target_ms < 0:
            self.p95_target_ms = 0
        try:
            self.p99_target_ms = int(self.p99_target_ms)
        except Exception:
            self.p99_target_ms = 100
        if self.p99_target_ms < 0:
            self.p99_target_ms = 0
        try:
            self.window_sec = int(self.window_sec)
        except Exception:
            self.window_sec = 60
        if self.window_sec < 1:
            self.window_sec = 1
        try:
            self.burn_alert_threshold = float(self.burn_alert_threshold)
        except Exception:
            self.burn_alert_threshold = 1.0
        if self.burn_alert_threshold < 0.0:
            self.burn_alert_threshold = 0.0

@dataclass
class MonitoringConfig:
    """Monitoring and metrics configuration."""
    enable_prometheus: bool = True
    metrics_port: int = 8000
    health_port: int = 8001
    log_level: str = "INFO"
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.metrics_port < 1024 or self.metrics_port > 65535:
            raise ValueError("metrics_port must be between 1024 and 65535")
        if self.health_port < 1024 or self.health_port > 65535:
            raise ValueError("health_port must be between 1024 and 65535")
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")


@dataclass
class StorageConfig:
    """Storage configuration."""
    backend: str = "parquet"  # "parquet", "sqlite", "postgres"
    parquet_path: str = "./data"
    batch_size: int = 1000
    flush_ms: int = 200
    compress: Optional[str] = None  # "zstd" or None
    sqlite_path: str = "./data/market_maker.db"
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "market_maker"
    pg_username: str = "market_maker"
    pg_password: str = "market_maker_pass"
    pg_schema: str = "public"
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.backend not in ["parquet", "sqlite", "postgres"]:
            raise ValueError("backend must be one of: parquet, sqlite, postgres")
        if self.batch_size < 100 or self.batch_size > 10000:
            raise ValueError("batch_size must be between 100 and 10000")
        if self.flush_ms < 50 or self.flush_ms > 5000:
            raise ValueError("flush_ms must be between 50 and 5000")
    
    @property
    def pg_dsn(self) -> str:
        """Get PostgreSQL connection string."""
        return f"postgresql://{self.pg_username}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


@dataclass
class FastCancelConfig:
    """Fast-cancel configuration for adverse price moves."""
    enabled: bool = True
    cancel_threshold_bps: float = 3.0  # Cancel if price moves >N bps from order price
    cooldown_after_spike_ms: int = 500  # Cooldown period after volatile spike
    spike_threshold_bps: float = 10.0  # Threshold to detect volatile spike
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.cancel_threshold_bps = float(self.cancel_threshold_bps)
        except Exception:
            self.cancel_threshold_bps = 3.0
        if self.cancel_threshold_bps < 0.5:
            self.cancel_threshold_bps = 0.5
        if self.cancel_threshold_bps > 50.0:
            self.cancel_threshold_bps = 50.0
        
        try:
            self.cooldown_after_spike_ms = int(self.cooldown_after_spike_ms)
        except Exception:
            self.cooldown_after_spike_ms = 500
        if self.cooldown_after_spike_ms < 0:
            self.cooldown_after_spike_ms = 0
        if self.cooldown_after_spike_ms > 5000:
            self.cooldown_after_spike_ms = 5000
        
        try:
            self.spike_threshold_bps = float(self.spike_threshold_bps)
        except Exception:
            self.spike_threshold_bps = 10.0
        if self.spike_threshold_bps < 1.0:
            self.spike_threshold_bps = 1.0
        if self.spike_threshold_bps > 100.0:
            self.spike_threshold_bps = 100.0


@dataclass
class TakerCapConfig:
    """Taker cap configuration to limit slippage."""
    enabled: bool = True
    max_taker_fills_per_hour: int = 50  # Max number of taker fills per hour
    max_taker_share_pct: float = 10.0  # Max taker share as % of all fills
    rolling_window_sec: int = 3600  # Rolling window for tracking (1 hour)
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.max_taker_fills_per_hour = int(self.max_taker_fills_per_hour)
        except Exception:
            self.max_taker_fills_per_hour = 50
        if self.max_taker_fills_per_hour < 1:
            self.max_taker_fills_per_hour = 1
        if self.max_taker_fills_per_hour > 1000:
            self.max_taker_fills_per_hour = 1000
        
        try:
            self.max_taker_share_pct = float(self.max_taker_share_pct)
        except Exception:
            self.max_taker_share_pct = 10.0
        if self.max_taker_share_pct < 0.0:
            self.max_taker_share_pct = 0.0
        if self.max_taker_share_pct > 100.0:
            self.max_taker_share_pct = 100.0
        
        try:
            self.rolling_window_sec = int(self.rolling_window_sec)
        except Exception:
            self.rolling_window_sec = 3600
        if self.rolling_window_sec < 60:
            self.rolling_window_sec = 60
        if self.rolling_window_sec > 86400:
            self.rolling_window_sec = 86400


@dataclass
class QueueAwareConfig:
    """Queue-aware quoting configuration for optimal queue positioning."""
    enabled: bool = True
    max_reprice_bps: float = 0.5  # Max micro-adjustment in bps to improve queue position
    headroom_ms: int = 150  # Min interval between queue-based reprices
    join_threshold_pct: float = 30.0  # Nudge if queue position worse than X percentile
    book_depth_levels: int = 3  # Number of book levels to analyze for queue estimation
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.max_reprice_bps = float(self.max_reprice_bps)
        except Exception:
            self.max_reprice_bps = 0.5
        if self.max_reprice_bps < 0.1:
            self.max_reprice_bps = 0.1
        if self.max_reprice_bps > 5.0:
            self.max_reprice_bps = 5.0
        
        try:
            self.headroom_ms = int(self.headroom_ms)
        except Exception:
            self.headroom_ms = 150
        if self.headroom_ms < 50:
            self.headroom_ms = 50
        if self.headroom_ms > 5000:
            self.headroom_ms = 5000
        
        try:
            self.join_threshold_pct = float(self.join_threshold_pct)
        except Exception:
            self.join_threshold_pct = 30.0
        if self.join_threshold_pct < 0.0:
            self.join_threshold_pct = 0.0
        if self.join_threshold_pct > 100.0:
            self.join_threshold_pct = 100.0
        
        try:
            self.book_depth_levels = int(self.book_depth_levels)
        except Exception:
            self.book_depth_levels = 3
        if self.book_depth_levels < 1:
            self.book_depth_levels = 1
        if self.book_depth_levels > 10:
            self.book_depth_levels = 10


@dataclass
class InventorySkewConfig:
    """Inventory-skew configuration for automatic inventory management."""
    enabled: bool = True
    target_pct: float = 0.0  # Target inventory as % of max position
    max_skew_bps: float = 0.6  # Maximum bid/ask skew in bps
    slope_bps_per_1pct: float = 0.1  # Skew strength per 1% inventory deviation
    clamp_pct: float = 5.0  # Ignore noise below ±X% inventory
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.target_pct = float(self.target_pct)
        except Exception:
            self.target_pct = 0.0
        if self.target_pct < -100.0:
            self.target_pct = -100.0
        if self.target_pct > 100.0:
            self.target_pct = 100.0
        
        try:
            self.max_skew_bps = float(self.max_skew_bps)
        except Exception:
            self.max_skew_bps = 0.6
        if self.max_skew_bps < 0.0:
            self.max_skew_bps = 0.0
        if self.max_skew_bps > 10.0:
            self.max_skew_bps = 10.0
        
        try:
            self.slope_bps_per_1pct = float(self.slope_bps_per_1pct)
        except Exception:
            self.slope_bps_per_1pct = 0.1
        if self.slope_bps_per_1pct < 0.0:
            self.slope_bps_per_1pct = 0.0
        if self.slope_bps_per_1pct > 1.0:
            self.slope_bps_per_1pct = 1.0
        
        try:
            self.clamp_pct = float(self.clamp_pct)
        except Exception:
            self.clamp_pct = 5.0
        if self.clamp_pct < 0.0:
            self.clamp_pct = 0.0
        if self.clamp_pct > 50.0:
            self.clamp_pct = 50.0


@dataclass
class AdaptiveSpreadConfig:
    """Adaptive spread configuration for dynamic spread adjustment."""
    enabled: bool = True
    base_spread_bps: float = 1.0  # Base spread in bps
    min_spread_bps: float = 0.6  # Minimum allowed spread
    max_spread_bps: float = 2.5  # Maximum allowed spread
    vol_window_sec: int = 60  # EMA window for volatility
    depth_levels: int = 5  # Number of book levels for liquidity
    liquidity_sensitivity: float = 0.4  # Weight for liquidity score (0..1)
    vol_sensitivity: float = 0.6  # Weight for volatility score (0..1)
    latency_sensitivity: float = 0.3  # Weight for latency score (0..1)
    pnl_dev_sensitivity: float = 0.3  # Weight for PnL deviation score (0..1)
    clamp_step_bps: float = 0.2  # Max spread change per tick
    cooloff_ms: int = 200  # Cooldown after rapid change
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.base_spread_bps = float(self.base_spread_bps)
        except Exception:
            self.base_spread_bps = 1.0
        if self.base_spread_bps < 0.1:
            self.base_spread_bps = 0.1
        if self.base_spread_bps > 10.0:
            self.base_spread_bps = 10.0
        
        try:
            self.min_spread_bps = float(self.min_spread_bps)
        except Exception:
            self.min_spread_bps = 0.6
        if self.min_spread_bps < 0.1:
            self.min_spread_bps = 0.1
        
        try:
            self.max_spread_bps = float(self.max_spread_bps)
        except Exception:
            self.max_spread_bps = 2.5
        if self.max_spread_bps < self.min_spread_bps:
            self.max_spread_bps = self.min_spread_bps * 2
        
        try:
            self.vol_window_sec = int(self.vol_window_sec)
        except Exception:
            self.vol_window_sec = 60
        if self.vol_window_sec < 10:
            self.vol_window_sec = 10
        if self.vol_window_sec > 3600:
            self.vol_window_sec = 3600
        
        try:
            self.depth_levels = int(self.depth_levels)
        except Exception:
            self.depth_levels = 5
        if self.depth_levels < 1:
            self.depth_levels = 1
        if self.depth_levels > 20:
            self.depth_levels = 20
        
        # Validate sensitivities (0..1)
        for attr in ['liquidity_sensitivity', 'vol_sensitivity', 'latency_sensitivity', 'pnl_dev_sensitivity']:
            try:
                val = float(getattr(self, attr))
            except Exception:
                val = 0.5
            val = max(0.0, min(1.0, val))
            setattr(self, attr, val)
        
        try:
            self.clamp_step_bps = float(self.clamp_step_bps)
        except Exception:
            self.clamp_step_bps = 0.2
        if self.clamp_step_bps < 0.01:
            self.clamp_step_bps = 0.01
        if self.clamp_step_bps > 5.0:
            self.clamp_step_bps = 5.0
        
        try:
            self.cooloff_ms = int(self.cooloff_ms)
        except Exception:
            self.cooloff_ms = 200
        if self.cooloff_ms < 0:
            self.cooloff_ms = 0
        if self.cooloff_ms > 5000:
            self.cooloff_ms = 5000


@dataclass
class ChaosConfig:
    """Chaos engineering configuration for resilience testing."""
    enabled: bool = False  # Master switch: chaos.enabled
    dry_run: bool = True  # Shadow mode: no real orders
    
    # Scenario intensities (0.0-1.0)
    net_loss: float = 0.0  # Packet loss (0.3 = 30%)
    exch_429: float = 0.0  # HTTP 429 rate limit
    exch_5xx: float = 0.0  # HTTP 5xx errors
    lat_spike_ms: int = 0  # Latency burst duration
    ws_lag_ms: int = 0  # WebSocket lag
    ws_disconnect: float = 0.0  # WS disconnect probability per minute
    dns_flap: float = 0.0  # DNS failures
    clock_skew_ms: int = 0  # Clock drift
    mem_pressure: str = "none"  # Memory pressure: none/low/medium/high
    rate_limit_storm: float = 0.0  # Aggressive rate limits
    reconcile_mismatch: float = 0.0  # Order state mismatches
    
    # Burst control
    burst_on_sec: int = 30  # Burst on duration
    burst_off_sec: int = 90  # Burst off duration
    
    def __post_init__(self):
        """Validate configuration values."""
        # Clamp intensities to [0, 1]
        for attr in ['net_loss', 'exch_429', 'exch_5xx', 'ws_disconnect', 
                     'dns_flap', 'rate_limit_storm', 'reconcile_mismatch']:
            val = getattr(self, attr)
            setattr(self, attr, max(0.0, min(1.0, float(val))))
        
        # Validate latencies
        if self.lat_spike_ms < 0:
            self.lat_spike_ms = 0
        if self.lat_spike_ms > 5000:
            self.lat_spike_ms = 5000
        
        if self.ws_lag_ms < 0:
            self.ws_lag_ms = 0
        if self.ws_lag_ms > 5000:
            self.ws_lag_ms = 5000
        
        if self.clock_skew_ms < 0:
            self.clock_skew_ms = 0
        if self.clock_skew_ms > 1000:
            self.clock_skew_ms = 1000
        
        # Validate mem_pressure
        if self.mem_pressure not in ['none', 'low', 'medium', 'high']:
            self.mem_pressure = 'none'
        
        # Validate burst durations
        if self.burst_on_sec < 1:
            self.burst_on_sec = 1
        if self.burst_off_sec < 1:
            self.burst_off_sec = 1


@dataclass
class TraceConfig:
    """Performance tracing configuration for canary deployment."""
    enabled: bool = True  # Feature flag: trace.enabled
    sample_rate: float = 0.2  # Sampling rate (0.0-1.0), 0.2 = 1 in 5 ticks
    deadline_ms: float = 200.0  # Deadline for tick (for deadline_miss tracking)
    export_golden: bool = True  # Export golden traces to artifacts/traces/
    golden_trace_interval: int = 100  # Export golden trace every N ticks
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.sample_rate < 0.0:
            self.sample_rate = 0.0
        if self.sample_rate > 1.0:
            self.sample_rate = 1.0
        
        if self.deadline_ms < 50.0:
            self.deadline_ms = 50.0
        if self.deadline_ms > 1000.0:
            self.deadline_ms = 1000.0
        
        if self.golden_trace_interval < 1:
            self.golden_trace_interval = 1


@dataclass
class AsyncBatchConfig:
    """Async batching configuration for parallel execution and command coalescing."""
    enabled: bool = True  # Feature flag: async_batch
    max_parallel_symbols: int = 10  # Max concurrent symbols per tick
    coalesce_cancel: bool = True  # Coalesce N cancel → 1 batch-cancel
    coalesce_place: bool = True  # Coalesce M place → ≤2 calls
    max_batch_size: int = 20  # Max orders per batch (Bybit limit)
    tick_deadline_ms: int = 200  # Target P95 tick duration
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.max_parallel_symbols < 1:
            self.max_parallel_symbols = 1
        if self.max_parallel_symbols > 50:
            self.max_parallel_symbols = 50
        
        if self.max_batch_size < 1:
            self.max_batch_size = 1
        if self.max_batch_size > 20:
            self.max_batch_size = 20  # Bybit API limit
        
        if self.tick_deadline_ms < 50:
            self.tick_deadline_ms = 50
        if self.tick_deadline_ms > 1000:
            self.tick_deadline_ms = 1000


@dataclass
class RiskGuardsConfig:
    """Risk guards configuration for safety limits."""
    enabled: bool = True
    # Volatility guards
    vol_ema_sec: int = 60
    vol_hard_bps: float = 25.0  # Hard stop threshold
    vol_soft_bps: float = 15.0  # Soft warning threshold
    # Latency guards
    latency_p95_hard_ms: int = 450
    latency_p95_soft_ms: int = 300
    # PnL drawdown guards
    pnl_window_min: int = 60
    pnl_soft_z: float = -1.5  # Z-score threshold for soft
    pnl_hard_z: float = -2.5  # Z-score threshold for hard
    # Inventory guards
    inventory_pct_soft: float = 6.0
    inventory_pct_hard: float = 10.0
    # Taker series guard
    taker_fills_window_min: int = 15
    taker_fills_soft: int = 12
    taker_fills_hard: int = 20
    # Actions
    size_scale_soft: float = 0.5  # Size multiplier in SOFT mode
    halt_ms_hard: int = 2000  # Halt duration in HARD mode
    
    def __post_init__(self):
        """Validate configuration values."""
        try:
            self.vol_ema_sec = int(self.vol_ema_sec)
        except Exception:
            self.vol_ema_sec = 60
        if self.vol_ema_sec < 10:
            self.vol_ema_sec = 10
        
        try:
            self.vol_hard_bps = float(self.vol_hard_bps)
            self.vol_soft_bps = float(self.vol_soft_bps)
        except Exception:
            self.vol_hard_bps = 25.0
            self.vol_soft_bps = 15.0
        if self.vol_soft_bps >= self.vol_hard_bps:
            self.vol_soft_bps = self.vol_hard_bps * 0.6
        
        try:
            self.latency_p95_hard_ms = int(self.latency_p95_hard_ms)
            self.latency_p95_soft_ms = int(self.latency_p95_soft_ms)
        except Exception:
            self.latency_p95_hard_ms = 450
            self.latency_p95_soft_ms = 300
        if self.latency_p95_soft_ms >= self.latency_p95_hard_ms:
            self.latency_p95_soft_ms = self.latency_p95_hard_ms - 50
        
        try:
            self.pnl_window_min = int(self.pnl_window_min)
        except Exception:
            self.pnl_window_min = 60
        if self.pnl_window_min < 5:
            self.pnl_window_min = 5
        
        try:
            self.pnl_soft_z = float(self.pnl_soft_z)
            self.pnl_hard_z = float(self.pnl_hard_z)
        except Exception:
            self.pnl_soft_z = -1.5
            self.pnl_hard_z = -2.5
        if self.pnl_hard_z > self.pnl_soft_z:
            self.pnl_hard_z = self.pnl_soft_z - 0.5
        
        try:
            self.inventory_pct_soft = float(self.inventory_pct_soft)
            self.inventory_pct_hard = float(self.inventory_pct_hard)
        except Exception:
            self.inventory_pct_soft = 6.0
            self.inventory_pct_hard = 10.0
        if self.inventory_pct_soft >= self.inventory_pct_hard:
            self.inventory_pct_soft = self.inventory_pct_hard * 0.6
        
        try:
            self.taker_fills_window_min = int(self.taker_fills_window_min)
        except Exception:
            self.taker_fills_window_min = 15
        
        try:
            self.taker_fills_soft = int(self.taker_fills_soft)
            self.taker_fills_hard = int(self.taker_fills_hard)
        except Exception:
            self.taker_fills_soft = 12
            self.taker_fills_hard = 20
        if self.taker_fills_soft >= self.taker_fills_hard:
            self.taker_fills_soft = self.taker_fills_hard - 5
        
        try:
            self.size_scale_soft = float(self.size_scale_soft)
        except Exception:
            self.size_scale_soft = 0.5
        if self.size_scale_soft < 0.1:
            self.size_scale_soft = 0.1
        if self.size_scale_soft > 1.0:
            self.size_scale_soft = 1.0
        
        try:
            self.halt_ms_hard = int(self.halt_ms_hard)
        except Exception:
            self.halt_ms_hard = 2000
        if self.halt_ms_hard < 100:
            self.halt_ms_hard = 100
        if self.halt_ms_hard > 10000:
            self.halt_ms_hard = 10000


@dataclass
class DatabaseConfig:
    """Database configuration (legacy)."""
    storage_type: str = "parquet"
    parquet_path: str = "./data"
    sqlite_path: str = "./data/market_maker.db"
    postgres_url: str = "postgresql://user:pass@localhost:5432/market_maker"


@dataclass
class WebSocketConfig:
    """WebSocket configuration."""
    reconnect_delay_ms: int = 1000
    max_reconnect_attempts: int = 10
    ping_interval_sec: int = 30
    pong_timeout_sec: int = 10
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.reconnect_delay_ms < 100 or self.reconnect_delay_ms > 10000:
            raise ValueError("reconnect_delay_ms must be between 100 and 10000")
        if self.max_reconnect_attempts < 1 or self.max_reconnect_attempts > 100:
            raise ValueError("max_reconnect_attempts must be between 1 and 100")


@dataclass
class RESTConfig:
    """REST API configuration."""
    timeout_sec: int = 10
    max_retries: int = 3
    retry_delay_ms: int = 1000
    
    def __post_init__(self):
        """Validate configuration values."""
        if self.timeout_sec < 1 or self.timeout_sec > 60:
            raise ValueError("timeout_sec must be between 1 and 60")
        if self.max_retries < 0 or self.max_retries > 10:
            raise ValueError("max_retries must be between 0 and 10")


@dataclass
class TradingConfig:
    """Trading configuration."""
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    use_testnet: bool = True
    base_spread_bps: float = 1.0
    ladder_levels: int = 3
    ladder_step_bps: float = 0.5
    quote_refresh_ms: int = 100
    max_active_orders_per_side: int = 10
    price_band_tolerance_bps: float = 2.0
    max_retry_attempts: int = 3
    post_only: bool = True
    min_notional_usd: float = 10
    maker_fee_bps: float = 1.0
    taker_fee_bps: float = 1.0
    
    def __post_init__(self):
        """Validate configuration values."""
        if not self.symbols:
            raise ValueError("At least one symbol must be specified")
        self.symbols = [s.upper() for s in self.symbols]
        if self.base_spread_bps < 0.1 or self.base_spread_bps > 100.0:
            raise ValueError("base_spread_bps must be between 0.1 and 100.0")
        if self.ladder_levels < 1 or self.ladder_levels > 10:
            raise ValueError("ladder_levels must be between 1 and 10")


@dataclass
class BybitConfig:
    """Bybit-specific configuration."""
    rest_url: str = "https://api-testnet.bybit.com"
    ws_url: str = "wss://stream-testnet.bybit.com"
    api_key: str = ""
    api_secret: str = ""
    use_testnet: bool = True  # Legacy support
    
    def __post_init__(self):
        """Validate configuration values."""
        if not self.api_key and not self.api_secret:
            # Allow empty for public-only access
            pass


@dataclass
class Config:
    """Main configuration class."""
    # Core configurations
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: 'SchedulerConfig' = field(default_factory=lambda: SchedulerConfig())
    runtime_guard: 'RuntimeGuardConfig' = field(default_factory=RuntimeGuardConfig)
    throttle: ThrottleConfig = field(default_factory=ThrottleConfig)
    circuit: CircuitConfig = field(default_factory=CircuitConfig)
    shadow: RuntimeShadowConfig = field(default_factory=RuntimeShadowConfig)
    rollout: RolloutConfig = field(default_factory=RolloutConfig)
    rollout_ramp: RolloutRampConfig = field(default_factory=RolloutRampConfig)
    chaos: ChaosConfig = field(default_factory=ChaosConfig)
    killswitch: CanaryKillSwitchConfig = field(default_factory=CanaryKillSwitchConfig)
    autopromote: AutoPromotionConfig = field(default_factory=AutoPromotionConfig)
    latency_slo: LatencySLOConfig = field(default_factory=LatencySLOConfig)
    guards: 'GuardsConfig' = field(default_factory=lambda: GuardsConfig())
    allocator: 'AllocatorConfig' = field(default_factory=AllocatorConfig)
    fees: 'FeesConfig' = field(default_factory=FeesConfig)
    
    # New pipeline and allocator configs
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    stage_budgets: StageBudgetsConfig = field(default_factory=StageBudgetsConfig)
    symbol_scoreboard: SymbolScoreboardConfig = field(default_factory=SymbolScoreboardConfig)
    dynamic_allocator: DynamicAllocatorConfig = field(default_factory=DynamicAllocatorConfig)
    
    # Legacy configurations (kept for backward compatibility)
    storage: StorageConfig = field(default_factory=StorageConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    rest: RESTConfig = field(default_factory=RESTConfig)
    connection_pool: ConnectionPoolConfig = field(default_factory=ConnectionPoolConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    bybit: BybitConfig = field(default_factory=BybitConfig)
    
    # Feature flags summary
    @property
    def feature_flags(self) -> Dict[str, bool]:
        """Get all feature flags as a dictionary."""
        return {
            "dynamic_spread": self.strategy.enable_dynamic_spread,
            "inventory_skew": self.strategy.enable_inventory_skew,
            "adverse_guard": self.strategy.enable_adverse_guard,
            "kill_switch": self.risk.enable_kill_switch,
            "prometheus": self.monitoring.enable_prometheus,
        }
    
    def validate(self) -> None:
        """Validate the entire configuration."""
        # This will trigger __post_init__ validation on all dataclasses
        pass


class ConfigLoader:
    """Configuration loader with YAML and environment variable support."""
    
    def __init__(self, config_path: Optional[str] = None, env_prefix: str = ""):
        """Initialize the config loader."""
        self.config_path = config_path or "config.yaml"
        self._config: Optional[Config] = None
        self._app_config: Optional["AppConfig"] = None
        self.env_prefix = env_prefix
    
    def load(self) -> "AppConfig":
        """Load configuration from YAML and environment variables as AppConfig."""
        if self._app_config is not None:
            return self._app_config
        
        # Load environment variables
        load_dotenv()
        
        # Load YAML config if it exists
        yaml_config = self._load_yaml()
        # Migrate legacy flat keys to new nested structure
        yaml_config = _migrate_legacy_yaml(yaml_config)
        # Normalize fees-section (best-effort, deepcopy to avoid mutating shared refs)
        try:
            yaml_config = _normalize_fees_section(deepcopy(yaml_config))
        except Exception:
            yaml_config = _normalize_fees_section(yaml_config)
        
        # Create low-level Config with YAML overrides
        config = self._create_config_from_yaml(yaml_config)

        # Override with environment variables (prefixed if provided)
        config = self._apply_env_overrides(config)

        # Build AppConfig from Config (preserves legacy fields)
        app_cfg = AppConfig(
            strategy=config.strategy,
            risk=config.risk,
            limits=config.limits,
            portfolio=config.portfolio,
            monitoring=config.monitoring,
            storage=config.storage,
            database=config.database,
            websocket=config.websocket,
            rest=config.rest,
            trading=config.trading,
            bybit=config.bybit,
            guards=config.guards,
            allocator=config.allocator,
            fees=config.fees,
        )

        # Validate invariants
        validate_invariants(app_cfg)

        self._config = config
        self._app_config = app_cfg
        return app_cfg
    
    def _load_yaml(self) -> Dict:
        """Load YAML configuration file."""
        try:
            if Path(self.config_path).exists():
                with open(self.config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            else:
                logger.info("Config file not found, using defaults path=%s", self.config_path)
                return {}
        except Exception as e:
            logger.info("Error loading config file, using defaults err=%s", e)
            return {}
    
    def _create_config_from_yaml(self, yaml_config: Dict) -> Config:
        """Create Config instance from YAML data."""
        # Validate unknown keys for each section before creating configs
        _validate_unknown_keys_obj(StrategyConfig, yaml_config.get('strategy', {}), ['strategy'])
        _validate_unknown_keys_obj(RiskConfig, yaml_config.get('risk', {}), ['risk'])
        _validate_unknown_keys_obj(LimitsConfig, yaml_config.get('limits', {}), ['limits'])
        _validate_unknown_keys_obj(PortfolioConfig, yaml_config.get('portfolio', {}), ['portfolio'])
        _validate_unknown_keys_obj(MonitoringConfig, yaml_config.get('monitoring', {}), ['monitoring'])
        _validate_unknown_keys_obj(SchedulerConfig, yaml_config.get('scheduler', {}), ['scheduler'])
        _validate_unknown_keys_obj(RuntimeGuardConfig, yaml_config.get('runtime_guard', {}), ['runtime_guard'])
        _validate_unknown_keys_obj(ThrottleConfig, yaml_config.get('throttle', {}), ['throttle'])
        _validate_unknown_keys_obj(CircuitConfig, yaml_config.get('circuit', {}), ['circuit'])
        _validate_unknown_keys_obj(RuntimeShadowConfig, yaml_config.get('shadow', {}), ['shadow'])
        _validate_unknown_keys_obj(RolloutConfig, yaml_config.get('rollout', {}), ['rollout'])
        _validate_unknown_keys_obj(RolloutRampConfig, yaml_config.get('rollout_ramp', {}), ['rollout_ramp'])
        _validate_unknown_keys_obj(CanaryKillSwitchConfig, yaml_config.get('killswitch', {}), ['killswitch'])
        _validate_unknown_keys_obj(AutoPromotionConfig, yaml_config.get('autopromote', {}), ['autopromote'])
        _validate_unknown_keys_obj(ChaosConfig, yaml_config.get('chaos', {}), ['chaos'])
        _validate_unknown_keys_obj(StorageConfig, yaml_config.get('storage', {}), ['storage'])
        _validate_unknown_keys_obj(AllocatorConfig, yaml_config.get('allocator', {}), ['allocator'])
        _validate_unknown_keys_obj(GuardsConfig, yaml_config.get('guards', {}), ['guards'])
        _validate_unknown_keys_obj(DatabaseConfig, yaml_config.get('database', {}), ['database'])
        _validate_unknown_keys_obj(WebSocketConfig, yaml_config.get('websocket', {}), ['websocket'])
        _validate_unknown_keys_obj(RESTConfig, yaml_config.get('rest', {}), ['rest'])
        _validate_unknown_keys_obj(TradingConfig, yaml_config.get('trading', {}), ['trading'])
        _validate_unknown_keys_obj(BybitConfig, yaml_config.get('bybit', {}), ['bybit'])
        
        # Fees normalization handled earlier

        # Extract nested configurations
        strategy_config = StrategyConfig(**yaml_config.get('strategy', {}))
        risk_config = RiskConfig(**yaml_config.get('risk', {}))
        limits_config = LimitsConfig(**yaml_config.get('limits', {}))
        portfolio_config = PortfolioConfig(**yaml_config.get('portfolio', {}))
        monitoring_config = MonitoringConfig(**yaml_config.get('monitoring', {}))
        scheduler_raw = yaml_config.get('scheduler', {})
        scheduler_config = SchedulerConfig(**scheduler_raw)
        runtime_guard_config = RuntimeGuardConfig(**yaml_config.get('runtime_guard', {}))
        throttle_config = ThrottleConfig(**yaml_config.get('throttle', {}))
        circuit_config = CircuitConfig(**yaml_config.get('circuit', {}))
        shadow_config = RuntimeShadowConfig(**yaml_config.get('shadow', {}))
        rollout_config = RolloutConfig(**yaml_config.get('rollout', {}))
        rollout_ramp_config = RolloutRampConfig(**yaml_config.get('rollout_ramp', {}))
        killswitch_config = CanaryKillSwitchConfig(**yaml_config.get('killswitch', {}))
        autopromote_config = AutoPromotionConfig(**yaml_config.get('autopromote', {}))
        chaos_config = ChaosConfig(**yaml_config.get('chaos', {}))
        guards_raw = yaml_config.get('guards', {})
        pos_skew_raw = guards_raw.get('pos_skew', {})
        pos_skew_config = PosSkewConfig(**pos_skew_raw)
        intraday_raw = guards_raw.get('intraday_caps', {})
        intraday_config = IntradayCapsConfig(**intraday_raw)
        guards_config = GuardsConfig(pos_skew=pos_skew_config, intraday_caps=intraday_config)
        # Normalize holidays into dataclass instances if provided as dicts
        try:
            holidays_list = getattr(scheduler_config, 'holidays', []) or []
            normalized = []
            for h in holidays_list:
                if isinstance(h, HolidayConfig):
                    normalized.append(h)
                elif isinstance(h, dict):
                    dates = list(h.get('dates', []) or [])
                    symbols = list(h.get('symbols', []) or [])
                    normalized.append(HolidayConfig(dates=dates, symbols=symbols))
            scheduler_config.holidays = normalized
        except Exception:
            pass
        storage_config = StorageConfig(**yaml_config.get('storage', {}))
        database_config = DatabaseConfig(**yaml_config.get('database', {}))
        websocket_config = WebSocketConfig(**yaml_config.get('websocket', {}))
        rest_config = RESTConfig(**yaml_config.get('rest', {}))
        trading_config = TradingConfig(**yaml_config.get('trading', {}))
        bybit_config = BybitConfig(**yaml_config.get('bybit', {}))
        allocator_raw = yaml_config.get('allocator', {})
        smoothing_raw = allocator_raw.get('smoothing', {})
        # Legacy aliases normalization for smoothing
        try:
            # Normalize and then drop alias keys so dataclass init doesn't see unexpected kwargs
            if 'bias_cap_ratio' in smoothing_raw and 'bias_cap' not in smoothing_raw:
                smoothing_raw['bias_cap'] = smoothing_raw.get('bias_cap_ratio')
            if 'fee_bias_cap_ratio' in smoothing_raw and 'fee_bias_cap' not in smoothing_raw:
                smoothing_raw['fee_bias_cap'] = smoothing_raw.get('fee_bias_cap_ratio')
            if 'fee_bias_cap_bps' in smoothing_raw and 'fee_bias_cap' not in smoothing_raw:
                try:
                    v = float(smoothing_raw.get('fee_bias_cap_bps'))
                except Exception:
                    v = 0.0
                smoothing_raw['fee_bias_cap'] = v / 10000.0
            # Remove aliases to avoid unexpected keyword errors
            for alias in ('bias_cap_ratio', 'fee_bias_cap_ratio', 'fee_bias_cap_bps'):
                if alias in smoothing_raw:
                    smoothing_raw.pop(alias, None)
        except Exception:
            pass
        smoothing_config = AllocatorSmoothingConfig(**smoothing_raw)
        allocator_config = AllocatorConfig(smoothing=smoothing_config)
        fees_config = FeesConfig(**yaml_config.get('fees', {}))
        
        return Config(
            strategy=strategy_config,
            risk=risk_config,
            limits=limits_config,
            portfolio=portfolio_config,
            monitoring=monitoring_config,
            scheduler=scheduler_config,
            runtime_guard=runtime_guard_config,
            throttle=throttle_config,
            circuit=circuit_config,
            shadow=shadow_config,
            rollout=rollout_config,
            rollout_ramp=rollout_ramp_config,
            killswitch=killswitch_config,
            autopromote=autopromote_config,
            chaos=chaos_config,
            storage=storage_config,
            database=database_config,
            websocket=websocket_config,
            rest=rest_config,
            trading=trading_config,
            bybit=bybit_config,
            guards=guards_config,
            allocator=allocator_config,
            fees=fees_config,
        )
    
    def _apply_env_overrides(self, config: Config) -> Config:
        """Apply environment variable overrides."""
        # Strategy overrides
        if os.getenv('STRATEGY_ENABLE_DYNAMIC_SPREAD'):
            config.strategy.enable_dynamic_spread = os.getenv('STRATEGY_ENABLE_DYNAMIC_SPREAD').lower() == 'true'
        if os.getenv('STRATEGY_ENABLE_INVENTORY_SKEW'):
            config.strategy.enable_inventory_skew = os.getenv('STRATEGY_ENABLE_INVENTORY_SKEW').lower() == 'true'
        if os.getenv('STRATEGY_ENABLE_ADVERSE_GUARD'):
            config.strategy.enable_adverse_guard = os.getenv('STRATEGY_ENABLE_ADVERSE_GUARD').lower() == 'true'
        if os.getenv('STRATEGY_K_VOLA_SPREAD'):
            config.strategy.k_vola_spread = float(os.getenv('STRATEGY_K_VOLA_SPREAD'))
        if os.getenv('STRATEGY_MIN_SPREAD_BPS'):
            config.strategy.min_spread_bps = int(os.getenv('STRATEGY_MIN_SPREAD_BPS'))
        if os.getenv('STRATEGY_MAX_SPREAD_BPS'):
            config.strategy.max_spread_bps = int(os.getenv('STRATEGY_MAX_SPREAD_BPS'))
        
        # Risk overrides
        if os.getenv('RISK_ENABLE_KILL_SWITCH'):
            config.risk.enable_kill_switch = os.getenv('RISK_ENABLE_KILL_SWITCH').lower() == 'true'
        if os.getenv('RISK_DRAWDOWN_DAY_PCT'):
            config.risk.drawdown_day_pct = float(os.getenv('RISK_DRAWDOWN_DAY_PCT'))
        if os.getenv('RISK_MAX_CONSECUTIVE_LOSSES'):
            config.risk.max_consecutive_losses = int(os.getenv('RISK_MAX_CONSECUTIVE_LOSSES'))
        
        # Limits overrides
        if os.getenv('LIMITS_MAX_ACTIVE_PER_SIDE'):
            config.limits.max_active_per_side = int(os.getenv('LIMITS_MAX_ACTIVE_PER_SIDE'))
        if os.getenv('LIMITS_MAX_CREATE_PER_SEC'):
            config.limits.max_create_per_sec = float(os.getenv('LIMITS_MAX_CREATE_PER_SEC'))
        if os.getenv('LIMITS_MAX_CANCEL_PER_SEC'):
            config.limits.max_cancel_per_sec = float(os.getenv('LIMITS_MAX_CANCEL_PER_SEC'))
        
        # Monitoring overrides
        if os.getenv('MONITORING_ENABLE_PROMETHEUS'):
            config.monitoring.enable_prometheus = os.getenv('MONITORING_ENABLE_PROMETHEUS').lower() == 'true'
        if os.getenv('MONITORING_METRICS_PORT'):
            config.monitoring.metrics_port = int(os.getenv('MONITORING_METRICS_PORT'))
        if os.getenv('MONITORING_HEALTH_PORT'):
            config.monitoring.health_port = int(os.getenv('MONITORING_HEALTH_PORT'))
        
        # Bybit overrides - SECURE: Use _load_secret to read from Docker Secrets or env
        api_key = _load_secret('BYBIT_API_KEY')
        if api_key:
            config.bybit.api_key = api_key
        
        api_secret = _load_secret('BYBIT_API_SECRET')
        if api_secret:
            config.bybit.api_secret = api_secret
        
        if os.getenv('BYBIT_USE_TESTNET'):
            use_testnet = os.getenv('BYBIT_USE_TESTNET').lower() == 'true'
            if use_testnet:
                config.bybit.rest_url = "https://api-testnet.bybit.com"
                config.bybit.ws_url = "wss://stream-testnet.bybit.com"
            else:
                config.bybit.rest_url = "https://api.bybit.com"
                config.bybit.ws_url = "wss://stream.bybit.com"
        
        # Storage overrides - SECURE: Use _load_secret for passwords
        pg_password = _load_secret('STORAGE_PG_PASSWORD')
        if pg_password:
            config.storage.pg_password = pg_password
        
        return config
    
    def reload(self) -> "AppConfig":
        """Reload configuration from disk."""
        self._config = None
        self._app_config = None
        return self.load()


# Global config instance (backward-compat). Prefer DI/AppContext for new code
_global_config: Optional[Config] = None
_global_app_config: Optional["AppConfig"] = None


def get_config(config_path: Optional[str] = None) -> "AppConfig":
    """Get global configuration instance."""
    global _global_app_config
    if _global_app_config is None:
        loader = ConfigLoader(config_path)
        _global_app_config = loader.load()
    return _global_app_config


def reload_config(config_path: Optional[str] = None) -> "AppConfig":
    """Reload global configuration."""
    global _global_app_config
    loader = ConfigLoader(config_path)
    _global_app_config = loader.reload()
    return _global_app_config


# ===== AppConfig with versioning and helpers =====

@dataclass
class AppConfig:
    """Versioned, strictly validated application config.

    Contains all existing sections for backward compatibility.
    """
    config_version: int = 1
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: 'SchedulerConfig' = field(default_factory=lambda: SchedulerConfig())
    runtime_guard: 'RuntimeGuardConfig' = field(default_factory=RuntimeGuardConfig)
    throttle: ThrottleConfig = field(default_factory=ThrottleConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    rest: RESTConfig = field(default_factory=RESTConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    bybit: BybitConfig = field(default_factory=BybitConfig)
    rollout: RolloutConfig = field(default_factory=RolloutConfig)
    rollout_ramp: RolloutRampConfig = field(default_factory=RolloutRampConfig)
    killswitch: CanaryKillSwitchConfig = field(default_factory=CanaryKillSwitchConfig)
    chaos: ChaosConfig = field(default_factory=ChaosConfig)
    latency_slo: LatencySLOConfig = field(default_factory=LatencySLOConfig)
    guards: GuardsConfig = field(default_factory=GuardsConfig)
    allocator: AllocatorConfig = field(default_factory=AllocatorConfig)
    fees: FeesConfig = field(default_factory=FeesConfig)
    
    # New pipeline and allocator configs
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    stage_budgets: StageBudgetsConfig = field(default_factory=StageBudgetsConfig)
    symbol_scoreboard: SymbolScoreboardConfig = field(default_factory=SymbolScoreboardConfig)
    dynamic_allocator: DynamicAllocatorConfig = field(default_factory=DynamicAllocatorConfig)
    md_cache: MDCacheConfig = field(default_factory=MDCacheConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sanitized(self) -> Dict[str, Any]:
        data = asdict(self)
        # mask secrets
        try:
            if "bybit" in data:
                if "api_key" in data["bybit"]:
                    data["bybit"]["api_key"] = "***"
                if "api_secret" in data["bybit"]:
                    data["bybit"]["api_secret"] = "***"
        except Exception:
            pass
        try:
            if "storage" in data and "pg_password" in data["storage"]:
                data["storage"]["pg_password"] = "***"
        except Exception:
            pass
        return data

    def describe(self) -> str:
        """Return stable ASCII dump of config as key=value lines, sorted lexicographically, ending with \n."""
        data = self.to_sanitized()
        flat: Dict[str, str] = {}

        def _fmt_val(v: Any) -> str:
            try:
                if isinstance(v, float):
                    return f"{v:.6f}"
                if isinstance(v, (int, bool)):
                    return str(v)
                if v is None:
                    return "null"
                return str(v)
            except Exception:
                return str(v)

        def _walk(prefix: str, obj: Any) -> None:
            if isinstance(obj, dict):
                for k in sorted(obj.keys()):
                    _walk(f"{prefix}.{k}" if prefix else k, obj[k])
            elif isinstance(obj, list):
                # Represent lists deterministically as comma-separated values
                vals = ",".join(_fmt_val(x) for x in obj)
                flat[prefix] = vals
            else:
                flat[prefix] = _fmt_val(obj)

        _walk("", data)
        # Exclude secrets by mask
        secrets = ["api_key", "api_secret", "password", "token", "secret"]
        items = []
        for k in sorted(flat.keys()):
            if any(s in k for s in secrets):
                continue
            items.append(f"{k}={flat[k]}")
        return "\n".join(items) + "\n"


# Runtime mutability whitelist
RUNTIME_MUTABLE: set[Tuple[str, str]] = {
    ("strategy", "k_vola_spread"),
    ("strategy", "min_spread_bps"),
    ("strategy", "max_spread_bps"),
    ("strategy", "skew_coeff"),
    ("strategy", "levels_per_side"),
    ("strategy", "level_spacing_coeff"),
    ("strategy", "min_time_in_book_ms"),
    ("strategy", "replace_threshold_bps"),
    ("strategy", "imbalance_cutoff"),
    ("risk", "drawdown_day_pct"),
    ("risk", "max_consecutive_losses"),
    ("risk", "max_reject_rate"),
    ("risk", "max_latency_p95_ms"),
    ("limits", "max_active_per_side"),
    ("limits", "max_create_per_sec"),
    ("limits", "max_cancel_per_sec"),
}


def diff_runtime_safe(old: AppConfig, new: AppConfig) -> Dict[str, Dict[str, Any]]:
    """Return runtime-safe changes as {"section.key": {"old":..., "new":...}}."""
    changes: Dict[str, Dict[str, Any]] = {}
    for section, key in RUNTIME_MUTABLE:
        old_val = getattr(getattr(old, section), key, None)
        new_val = getattr(getattr(new, section), key, None)
        if old_val != new_val:
            changes[f"{section}.{key}"] = {"old": old_val, "new": new_val}
    return changes


def apply_runtime_overrides(dst: AppConfig, src: AppConfig, allowed: set[Tuple[str, str]]) -> AppConfig:
    """Apply runtime-safe fields from src to dst, in-place, and return dst."""
    for section, key in allowed:
        if hasattr(dst, section) and hasattr(src, section):
            setattr(getattr(dst, section), key, getattr(getattr(src, section), key))
    return dst


def cfg_hash_sanitized(cfg: AppConfig) -> str:
    """Compute sha256 hash of sanitized config."""
    data = cfg.to_sanitized()
    payload = orjson.dumps(data, option=orjson.OPT_SORT_KEYS)
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def get_git_sha() -> str:
    """Get git SHA from env or return 'unknown'."""
    return os.getenv("GIT_SHA", "unknown")


def validate_invariants(cfg: AppConfig) -> None:
    """Validate config invariants; raise ValueError on violation."""
    s = cfg.strategy
    l = cfg.limits
    if not (s.min_spread_bps <= s.max_spread_bps):
        raise ValueError("strategy.min_spread_bps must be <= strategy.max_spread_bps")
    if not (s.levels_per_side >= 1):
        raise ValueError("strategy.levels_per_side must be >= 1")
    if not (0 < s.k_vola_spread <= 2):
        raise ValueError("strategy.k_vola_spread must be in (0, 2]")
    if not (0 < l.max_create_per_sec <= 20):
        raise ValueError("limits.max_create_per_sec must be in (0, 20]")
    if not (0 < l.max_cancel_per_sec <= 20):
        raise ValueError("limits.max_cancel_per_sec must be in (0, 20]")
    if not (100 <= s.min_time_in_book_ms <= 3000):
        raise ValueError("strategy.min_time_in_book_ms must be between 100 and 3000")


def _validate_unknown_keys_obj(dc_cls: Any, data: Any, path: List[str]) -> None:
    """Recursively validate that data only contains known keys for dataclass fields."""
    if not is_dataclass(dc_cls):
        return
    if not isinstance(data, dict):
        return
    field_names = {f.name for f in dc_cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    for key, val in data.items():
        if key not in field_names:
            raise ValueError("Unknown config key: " + ".".join(path + [key]))
        # Recurse if nested dataclass
        sub_cls = getattr(globals(), ''.join(word.capitalize() for word in key.split('_')) + 'Config', None)
        # Fallback: infer by attribute on a dummy instance if available
        target_cls = None
        if hasattr(dc_cls, key):
            target_cls = type(getattr(dc_cls, key))
        if sub_cls and is_dataclass(sub_cls):
            _validate_unknown_keys_obj(sub_cls, val, path + [key])
        elif is_dataclass(target_cls):
            _validate_unknown_keys_obj(target_cls, val, path + [key])


def _validate_unknown_keys(yaml_dict: Dict[str, Any]) -> None:
    _validate_unknown_keys_obj(AppConfig, yaml_dict, [])


def _migrate_legacy_yaml(d: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate legacy top-level keys (e.g., symbols) into nested sections for compatibility."""
    if not isinstance(d, dict):
        return {}
    d = dict(d)
    # Move some legacy keys under trading/monitoring if present
    trading = d.get("trading", {})
    monitoring = d.get("monitoring", {})
    # legacy top-level trading keys
    for k in ["symbols", "use_testnet", "base_spread_bps", "ladder_levels", "ladder_step_bps", "quote_refresh_ms",
              "max_active_orders_per_side", "price_band_tolerance_bps", "max_retry_attempts", "post_only",
              "min_notional_usd", "maker_fee_bps", "taker_fee_bps"]:
        if k in d and k not in trading:
            trading[k] = d.pop(k)
    if trading:
        d["trading"] = trading
    # legacy strategy keys
    strategy = d.get("strategy", {})
    for k in [
        "volatility_lookback_sec", "imbalance_weight", "microprice_weight", "k_vola", "k_imb", "t_imb",
        "risk_buffer_bps", "skew_k", "max_skew_bps", "max_quote_levels", "max_active_orders_per_symbol",
        "max_new_orders_per_sec", "quote_refresh_ms", "amend_price_threshold_bps", "amend_size_threshold",
        "cancel_stale_ms", "backoff_on_reject_ms"
    ]:
        if k in d and k not in strategy:
            strategy[k] = d.pop(k)
    if strategy:
        d["strategy"] = strategy

    # legacy monitoring ports
    for k in ["metrics_port", "health_port", "log_level"]:
        if k in d and k not in monitoring:
            monitoring[k] = d.pop(k)
    if monitoring:
        d["monitoring"] = monitoring
    # legacy risk keys
    risk = d.get("risk", {})
    for k in ["max_position_usd", "target_inventory_usd", "inventory_skew_gamma", "daily_max_loss_usd", "max_cancels_per_min"]:
        if k in d and k not in risk:
            risk[k] = d.pop(k)
    if risk:
        d["risk"] = risk
    # legacy database keys
    database = d.get("database", {})
    for k in ["storage_type", "parquet_path", "sqlite_path", "postgres_url"]:
        if k in d and k not in database:
            database[k] = d.pop(k)
    if database:
        d["database"] = database
    
    # legacy websocket keys (with ws_ prefix)
    websocket = d.get("websocket", {})
    ws_mappings = {
        "ws_reconnect_delay_ms": "reconnect_delay_ms",
        "ws_max_reconnect_attempts": "max_reconnect_attempts", 
        "ws_ping_interval_sec": "ping_interval_sec",
        "ws_pong_timeout_sec": "pong_timeout_sec"
    }
    for old_key, new_key in ws_mappings.items():
        if old_key in d and new_key not in websocket:
            websocket[new_key] = d.pop(old_key)
    if websocket:
        d["websocket"] = websocket
    
    # legacy rest keys (with rest_ prefix)
    rest = d.get("rest", {})
    rest_mappings = {
        "rest_timeout_sec": "timeout_sec",
        "rest_max_retries": "max_retries",
        "rest_retry_delay_ms": "retry_delay_ms"
    }
    for old_key, new_key in rest_mappings.items():
        if old_key in d and new_key not in rest:
            rest[new_key] = d.pop(old_key)
    if rest:
        d["rest"] = rest
    
    # legacy bybit keys
    bybit = d.get("bybit", {})
    for k in ["rest_url", "ws_url", "api_key", "api_secret", "use_testnet"]:
        if k in d and k not in bybit:
            bybit[k] = d.pop(k)
    if bybit:
        d["bybit"] = bybit
    
    return d
