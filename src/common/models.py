"""
Core data models for the market maker bot.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class Side(str, Enum):
    """Order side enumeration."""
    BUY = "Buy"
    SELL = "Sell"


class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "Market"
    LIMIT = "Limit"


class TimeInForce(str, Enum):
    """Time in force enumeration."""
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "Pending"
    NEW = "New"
    PARTIALLY_FILLED = "PartiallyFilled"
    FILLED = "Filled"
    CANCELED = "Canceled"
    REJECTED = "Rejected"


class InstrumentInfo(BaseModel):
    """Instrument information from Bybit."""
    symbol: str
    base_coin: str
    quote_coin: str
    tick_size: Decimal
    lot_size: Decimal
    min_order_qty: Decimal
    min_order_amt: Decimal
    max_order_qty: Decimal
    max_order_amt: Decimal
    qty_step: Decimal
    price_scale: int
    qty_scale: int
    contract_type: str
    status: str
    launch_time: Optional[int] = None
    delivery_time: Optional[int] = None
    delivery_fee_rate: Optional[Decimal] = None
    contract_size: Optional[Decimal] = None


class PriceLevel(BaseModel):
    """Price level in the order book."""
    price: Decimal
    size: Decimal
    sequence: int = 0

    model_config = {"arbitrary_types_allowed": True}


class OrderBook(BaseModel):
    """Level 2 order book representation."""
    symbol: str
    timestamp: datetime
    sequence: int
    bids: List[PriceLevel]
    asks: List[PriceLevel]
    
    @field_validator('bids', 'asks')
    @classmethod
    def validate_price_levels(cls, v):
        """Ensure price levels are sorted correctly."""
        if v:
            # Bids should be sorted descending, asks ascending
            # Note: This is a simplified validation for now
            pass
        return v

    @property
    def mid_price(self) -> Optional[Decimal]:
        """Calculate mid price."""
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return None

    @property
    def spread_bps(self) -> Optional[Decimal]:
        """Calculate spread in basis points."""
        if self.mid_price and self.bids and self.asks:
            spread = self.asks[0].price - self.bids[0].price
            return (spread / self.mid_price) * 10000
        return None

    @property
    def best_bid(self) -> Optional[PriceLevel]:
        """Get best bid."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[PriceLevel]:
        """Get best ask."""
        return self.asks[0] if self.asks else None


class Order(BaseModel):
    """Order representation."""
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    client_order_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    side: Side
    order_type: OrderType
    qty: Decimal
    price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: Decimal = Decimal(0)
    avg_price: Optional[Decimal] = None
    created_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    post_only: bool = True
    reduce_only: bool = False
    close_on_trigger: bool = False

    model_config = {"arbitrary_types_allowed": True}

    @property
    def remaining_qty(self) -> Decimal:
        """Calculate remaining quantity."""
        return self.qty - self.filled_qty

    @property
    def is_active(self) -> bool:
        """Check if order is active."""
        return self.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]

    @property
    def notional_value(self) -> Optional[Decimal]:
        """Calculate notional value."""
        if self.price:
            return self.qty * self.price
        return None


class Trade(BaseModel):
    """Trade execution representation."""
    trade_id: str
    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_rate: Decimal
    timestamp: datetime
    exec_time: datetime
    is_maker: bool = False

    model_config = {"arbitrary_types_allowed": True}


class Position(BaseModel):
    """Position representation."""
    symbol: str
    side: Side
    size: Decimal
    avg_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    margin: Decimal
    leverage: Decimal
    timestamp: datetime

    model_config = {"arbitrary_types_allowed": True}

    @property
    def notional_value(self) -> Decimal:
        """Calculate notional value."""
        return self.size * self.avg_price


class Balance(BaseModel):
    """Account balance representation."""
    coin: str
    wallet_balance: Decimal
    available_balance: Decimal
    used_margin: Decimal
    order_margin: Decimal
    position_margin: Decimal
    timestamp: datetime

    model_config = {"arbitrary_types_allowed": True}


class QuoteRequest(BaseModel):
    """Quote request from strategy."""
    symbol: str
    side: Side
    order_type: OrderType = OrderType.LIMIT
    qty: Decimal
    price: Decimal
    post_only: bool = True
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


class QuoteResponse(BaseModel):
    """Quote response from execution."""
    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketDataEvent(BaseModel):
    """Market data event wrapper."""
    event_type: str
    symbol: str
    timestamp: datetime
    data: Union[OrderBook, Trade, Dict]
    sequence: Optional[int] = None


class RiskMetrics(BaseModel):
    """Risk metrics snapshot."""
    timestamp: datetime
    total_pnl: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_exposure_usd: Decimal
    max_drawdown: Decimal
    cancel_rate_per_min: Decimal
    fill_rate: Decimal
    avg_spread_bps: Decimal
    inventory_skew: Decimal

    model_config = {"arbitrary_types_allowed": True}
