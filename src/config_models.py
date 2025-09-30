from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, ValidationError, field_validator


class StrategySettings(BaseModel):
    model_config = {"extra": "forbid"}

    enable_enhanced_quoting: bool = True
    enable_dynamic_spread: bool = True
    enable_inventory_skew: bool = True
    enable_adverse_guard: bool = True

    volatility_lookback_sec: int = Field(30, ge=1)
    imbalance_weight: float = Field(0.4, ge=0)
    microprice_weight: float = Field(0.6, ge=0)
    k_vola: float = Field(0.5, ge=0)
    k_imb: float = Field(0.2, ge=0)
    t_imb: float = Field(0.1, ge=0)
    risk_buffer_bps: float = Field(2.0, ge=0)
    skew_k: float = Field(0.1, ge=0)
    max_skew_bps: float = Field(30.0, ge=0)


class GuardsPosSkewSettings(BaseModel):
    model_config = {"extra": "forbid"}

    per_symbol_abs_limit: float = Field(0.0, ge=0)
    per_color_abs_limit: float = Field(0.0, ge=0)


class GuardsIntradayCapsSettings(BaseModel):
    model_config = {"extra": "forbid"}

    daily_pnl_stop: float = Field(0.0, ge=0)
    daily_turnover_cap: float = Field(0.0, ge=0)
    daily_vol_cap: float = Field(0.0, ge=0)


class GuardsSettings(BaseModel):
    model_config = {"extra": "forbid"}

    pos_skew: GuardsPosSkewSettings = GuardsPosSkewSettings()
    intraday_caps: GuardsIntradayCapsSettings = GuardsIntradayCapsSettings()


class AllocatorSmoothingSettings(BaseModel):
    model_config = {"extra": "forbid"}

    bias_cap_ratio: float = Field(0.20, ge=0.0, le=1.0)


class AllocatorSettings(BaseModel):
    model_config = {"extra": "forbid"}

    smoothing: AllocatorSmoothingSettings = AllocatorSmoothingSettings()


class Settings(BaseModel):
    """Strict schema mirroring config.yaml. Extra keys are forbidden."""

    model_config = {"extra": "forbid"}

    # Top-level trading keys
    symbols: List[str] = Field(..., min_length=1)
    use_testnet: bool = True
    base_spread_bps: float = Field(1.0, ge=0)
    ladder_levels: int = Field(3, ge=1)
    ladder_step_bps: float = Field(0.5, ge=0)
    quote_refresh_ms: int = Field(100, ge=1)

    # Risk-like/top-level guardrails (as in YAML)
    max_position_usd: float = Field(5000, ge=0)
    target_inventory_usd: float = Field(0, ge=0)
    inventory_skew_gamma: float = Field(0.1, ge=0)
    daily_max_loss_usd: float = Field(300, ge=0)
    max_cancels_per_min: int = Field(90, ge=0)

    # Order management
    post_only: bool = True
    min_notional_usd: float = Field(10, gt=0)
    maker_fee_bps: float = Field(1.0, ge=0)
    taker_fee_bps: float = Field(1.0, ge=0)

    # Nested sections
    strategy: StrategySettings = StrategySettings()
    guards: GuardsSettings = GuardsSettings()
    allocator: AllocatorSettings = AllocatorSettings()

    @field_validator("symbols")
    @classmethod
    def _symbols_upper_nonempty(cls, v: List[str]) -> List[str]:
        symbols = [str(s).strip().upper() for s in v if str(s).strip()]
        if not symbols:
            raise ValueError("symbols must contain at least one non-empty symbol")
        return symbols


__all__ = [
    "Settings",
    "StrategySettings",
    "GuardsSettings",
    "GuardsPosSkewSettings",
    "GuardsIntradayCapsSettings",
    "AllocatorSettings",
    "AllocatorSmoothingSettings",
    "ValidationError",
]


