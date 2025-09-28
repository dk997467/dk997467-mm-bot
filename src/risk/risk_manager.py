"""
Risk management system with position limits, loss monitoring, and kill-switch.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

try:
    from common.config import Config
    from common.models import Order, Position, Side, RiskMetrics
    from common.utils import clamp
except ImportError:
    from src.common.config import Config
    from src.common.models import Order, Position, Side, RiskMetrics
    from src.common.utils import clamp


class RiskManager:
    """Risk management system with real-time monitoring and controls."""
    
    def __init__(self, config: Config, recorder=None):
        """Initialize the risk manager."""
        self.config = config
        self.recorder = recorder
        
        # Risk limits
        self.max_position_usd = Decimal(str(config.risk.max_position_usd))
        self.target_inventory_usd = Decimal(str(config.risk.target_inventory_usd))
        self.daily_max_loss_usd = Decimal(str(config.risk.daily_max_loss_usd))
        self.max_cancels_per_min = config.risk.max_cancels_per_min
        
        # Current state
        self.positions: Dict[str, Position] = {}
        self.daily_pnl = Decimal(0)
        self.daily_start_time = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.max_drawdown = Decimal(0)
        self.peak_pnl = Decimal(0)
        
        # Risk flags
        self.kill_switch_triggered = False
        self.kill_switch_reason = ""
        self.risk_warnings: List[str] = []
        self.risk_paused = False
        self.risk_pause_reason = ""
        self.risk_pause_until = None
        
        # Cancel rate monitoring
        self.cancel_counts = defaultdict(int)
        self.cancel_reset_times = defaultdict(datetime)
        
        # Performance tracking
        self.total_turnover = Decimal(0)
        self.total_fees = Decimal(0)
        self.fill_rate = Decimal(0)
        self.avg_spread_bps = Decimal(0)
        
        # Callbacks
        self.on_risk_alert = None
        self.on_kill_switch = None
        self.on_position_update = None
        
        # Initialize cancel rate tracking
        for symbol in config.trading.symbols:
            self.cancel_reset_times[symbol] = datetime.now(timezone.utc)
    
    def pause_risk(self, reason: str, duration_ms: Optional[int] = None):
        """
        Pause risk temporarily to block creates/replaces.
        
        Args:
            reason: Reason for risk pause
            duration_ms: Optional duration in milliseconds
        """
        self.risk_paused = True
        self.risk_pause_reason = reason
        
        if duration_ms:
            self.risk_pause_until = datetime.now(timezone.utc) + timedelta(milliseconds=duration_ms)
        else:
            self.risk_pause_until = None
            
        print(f"Risk paused: {reason}")
        
        if self.recorder:
            asyncio.create_task(self.recorder.record_custom_event(
                "risk_paused",
                {
                    "reason": reason,
                    "duration_ms": duration_ms,
                    "paused_until": self.risk_pause_until.isoformat() if self.risk_pause_until else None,
                    "timestamp": datetime.now(timezone.utc)
                }
            ))
    
    def resume_risk(self):
        """Resume risk operations."""
        if self.risk_paused:
            print(f"Risk resumed from pause: {self.risk_pause_reason}")
            
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "risk_resumed",
                    {
                        "previous_reason": self.risk_pause_reason,
                        "timestamp": datetime.now(timezone.utc)
                    }
                ))
        
        self.risk_paused = False
        self.risk_pause_reason = ""
        self.risk_pause_until = None
    
    def check_risk_pause_status(self) -> bool:
        """
        Check if risk pause has expired.
        
        Returns:
            True if risk is paused, False otherwise
        """
        if not self.risk_paused:
            return False
            
        # Check if pause has expired
        if self.risk_pause_until and datetime.now(timezone.utc) >= self.risk_pause_until:
            self.resume_risk()
            return False
            
        return True
    
    def is_risk_paused(self) -> bool:
        """Check if risk is currently paused."""
        return self.check_risk_pause_status()
    
    def update_position(self, symbol: str, side: Side, size: Decimal, price: Decimal):
        """Update position after a trade."""
        try:
            current_position = self.positions.get(symbol)
            
            if current_position:
                # Update existing position
                if side == Side.BUY:
                    # Buying increases position
                    new_size = current_position.size + size
                    if new_size != 0:
                        # Calculate new average price
                        total_cost = (current_position.size * current_position.avg_price) + (size * price)
                        new_avg_price = total_cost / new_size
                    else:
                        new_avg_price = Decimal(0)
                else:
                    # Selling decreases position
                    new_size = current_position.size - size
                    new_avg_price = current_position.avg_price
                
                # Update position
                current_position.size = new_size
                current_position.avg_price = new_avg_price
                current_position.timestamp = datetime.now(timezone.utc)
                
                # Remove position if size is zero
                if new_size == 0:
                    del self.positions[symbol]
                else:
                    # Update side based on new size
                    current_position.side = Side.BUY if new_size > 0 else Side.SELL
            else:
                # Create new position
                if side == Side.BUY:
                    new_position = Position(
                        symbol=symbol,
                        side=Side.BUY,
                        size=size,
                        avg_price=price,
                        unrealized_pnl=Decimal(0),
                        realized_pnl=Decimal(0),
                        margin=Decimal(0),
                        leverage=Decimal(1),
                        timestamp=datetime.now(timezone.utc)
                    )
                    self.positions[symbol] = new_position
                else:
                    # Selling without position creates short
                    new_position = Position(
                        symbol=symbol,
                        side=Side.SELL,
                        size=size,
                        avg_price=price,
                        unrealized_pnl=Decimal(0),
                        realized_pnl=Decimal(0),
                        margin=Decimal(0),
                        leverage=Decimal(1),
                        timestamp=datetime.now(timezone.utc)
                    )
                    self.positions[symbol] = new_position
            
            # Check risk limits
            self._check_position_limits()
            
            # Record position update if recorder is available
            if self.recorder:
                current_position = self.positions.get(symbol)
                if current_position:
                    asyncio.create_task(self.recorder.record_custom_event(
                        "position_update",
                        {
                            "symbol": symbol,
                            "side": current_position.side.value,
                            "size": float(current_position.size),
                            "avg_price": float(current_position.avg_price),
                            "unrealized_pnl": float(current_position.unrealized_pnl),
                            "realized_pnl": float(current_position.realized_pnl),
                            "timestamp": datetime.now()
                        }
                    ))
            
            # Call callback
            if self.on_position_update:
                self.on_position_update(symbol, self.positions.get(symbol))
                
        except Exception as e:
            print(f"Error updating position: {e}")
    
    def update_pnl(self, realized_pnl: Decimal, unrealized_pnl: Decimal = Decimal(0)):
        """Update P&L tracking."""
        try:
            # Update daily P&L
            self.daily_pnl += realized_pnl
            
            # Track peak P&L and drawdown
            if self.daily_pnl > self.peak_pnl:
                self.peak_pnl = self.daily_pnl
            
            current_drawdown = self.peak_pnl - self.daily_pnl
            if current_drawdown > self.max_drawdown:
                self.max_drawdown = current_drawdown
            
            # Check daily loss limit
            if self.daily_pnl < -self.daily_max_loss_usd:
                self._trigger_kill_switch(f"Daily loss limit exceeded: {self.daily_pnl}")
            
            # Check drawdown limit (optional)
            max_drawdown_limit = self.daily_max_loss_usd * Decimal("2")  # 2x daily loss limit
            if self.max_drawdown > max_drawdown_limit:
                self._trigger_kill_switch(f"Maximum drawdown exceeded: {self.max_drawdown}")
            
            # Record P&L update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "pnl_update",
                    {
                        "daily_pnl": float(self.daily_pnl),
                        "realized_pnl": float(realized_pnl),
                        "unrealized_pnl": float(unrealized_pnl),
                        "peak_pnl": float(self.peak_pnl),
                        "max_drawdown": float(self.max_drawdown),
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error updating P&L: {e}")
    
    def record_cancel(self, symbol: str):
        """Record a cancel for rate limiting."""
        try:
            current_time = datetime.now(timezone.utc)
            
            # Reset counter if minute has passed
            if (current_time - self.cancel_reset_times[symbol]).total_seconds() >= 60:
                self.cancel_counts[symbol] = 0
                self.cancel_reset_times[symbol] = current_time
            
            self.cancel_counts[symbol] += 1
            
            # Check if cancel limit exceeded
            if self.cancel_counts[symbol] > self.max_cancels_per_min:
                self._add_risk_warning(f"Cancel rate limit exceeded for {symbol}: {self.cancel_counts[symbol]}")
            
            # Record cancel event if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "cancel_event",
                    {
                        "symbol": symbol,
                        "cancel_count": self.cancel_counts[symbol],
                        "max_cancels_per_min": self.max_cancels_per_min,
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error recording cancel: {e}")
    
    def can_place_order(self, symbol: str, side: Side, size: Decimal, price: Decimal) -> Tuple[bool, str]:
        """Check if order placement is allowed."""
        try:
            # Check kill switch
            if self.kill_switch_triggered:
                return False, f"Kill switch active: {self.kill_switch_reason}"
            
            # Check position limits
            position_check = self._check_position_limit(symbol, side, size, price)
            if not position_check[0]:
                return False, position_check[1]
            
            # Check cancel budget
            if self.cancel_counts[symbol] >= self.max_cancels_per_min:
                return False, f"Cancel budget exceeded for {symbol}"
            
            return True, "Order allowed"
            
        except Exception as e:
            return False, f"Risk check error: {e}"
    
    def can_cancel_order(self, symbol: str) -> bool:
        """Check if order cancellation is allowed."""
        try:
            # Check kill switch
            if self.kill_switch_triggered:
                return False
            
            # Check cancel budget
            return self.cancel_counts[symbol] < self.max_cancels_per_min
            
        except Exception as e:
            print(f"Error checking cancel permission: {e}")
            return False
    
    def _check_position_limits(self):
        """Check all position-related risk limits."""
        try:
            total_exposure = self._calculate_total_exposure()
            
            # Check maximum position size
            if total_exposure > self.max_position_usd:
                self._trigger_kill_switch(f"Maximum position size exceeded: {total_exposure}")
                return
            
            # Check individual symbol limits
            for symbol, position in self.positions.items():
                position_value = abs(position.size * position.avg_price)
                if position_value > self.max_position_usd * Decimal("0.5"):  # 50% per symbol
                    self._add_risk_warning(f"Large position in {symbol}: {position_value}")
                    
        except Exception as e:
            print(f"Error checking position limits: {e}")
    
    def _check_position_limit(self, symbol: str, side: Side, size: Decimal, price: Decimal) -> Tuple[bool, str]:
        """Check if a specific order would exceed position limits."""
        try:
            # Calculate new position size
            current_position = self.positions.get(symbol)
            current_size = current_position.size if current_position else Decimal(0)
            
            if side == Side.BUY:
                new_size = current_size + size
            else:
                new_size = current_size - size
            
            # Calculate new position value
            new_value = abs(new_size * price)
            
            # Check against limits
            if new_value > self.max_position_usd:
                return False, f"Position value {new_value} exceeds limit {self.max_position_usd}"
            
            # Check total exposure
            total_exposure = self._calculate_total_exposure()
            if side == Side.BUY:
                additional_exposure = size * price
            else:
                additional_exposure = Decimal(0)  # Selling reduces exposure
            
            new_total_exposure = total_exposure + additional_exposure
            if new_total_exposure > self.max_position_usd:
                return False, f"Total exposure {new_total_exposure} exceeds limit {self.max_position_usd}"
            
            return True, "Position limit check passed"
            
        except Exception as e:
            return False, f"Position limit check error: {e}"
    
    def _calculate_total_exposure(self) -> Decimal:
        """Calculate total exposure across all positions."""
        try:
            total_exposure = Decimal(0)
            
            for position in self.positions.values():
                position_value = abs(position.size * position.avg_price)
                total_exposure += position_value
            
            return total_exposure
            
        except Exception as e:
            print(f"Error calculating total exposure: {e}")
            return Decimal(0)
    
    def _trigger_kill_switch(self, reason: str):
        """Trigger the kill switch."""
        try:
            if not self.kill_switch_triggered:
                self.kill_switch_triggered = True
                self.kill_switch_reason = reason
                
                print(f"KILL SWITCH TRIGGERED: {reason}")
                
                # Record kill switch event if recorder is available
                if self.recorder:
                    asyncio.create_task(self.recorder.record_custom_event(
                        "kill_switch_triggered",
                        {
                            "reason": reason,
                            "timestamp": datetime.now()
                        }
                    ))
                
                # Call callback
                if self.on_kill_switch:
                    self.on_kill_switch(reason)
                
                # Add to risk warnings
                self._add_risk_warning(f"KILL SWITCH: {reason}")
                
        except Exception as e:
            print(f"Error triggering kill switch: {e}")
    
    def _add_risk_warning(self, warning: str):
        """Add a risk warning."""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            warning_msg = f"[{timestamp}] {warning}"
            self.risk_warnings.append(warning_msg)
            
            # Keep only last 100 warnings
            if len(self.risk_warnings) > 100:
                self.risk_warnings.pop(0)
            
            # Record risk warning if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "risk_warning",
                    {
                        "warning": warning,
                        "timestamp": datetime.now()
                    }
                ))
            
            # Call callback
            if self.on_risk_alert:
                self.on_risk_alert(warning)
                
        except Exception as e:
            print(f"Error adding risk warning: {e}")
    
    def reset_daily_metrics(self):
        """Reset daily metrics (called at start of new day)."""
        try:
            self.daily_pnl = Decimal(0)
            self.daily_start_time = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            self.max_drawdown = Decimal(0)
            self.peak_pnl = Decimal(0)
            
            # Clear old risk warnings
            self.risk_warnings.clear()
            
            print("Daily risk metrics reset")
            
        except Exception as e:
            print(f"Error resetting daily metrics: {e}")
    
    def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics."""
        try:
            total_exposure = self._calculate_total_exposure()
            
            # Calculate inventory skew
            inventory_skew = Decimal(0)
            if total_exposure > 0:
                target_inventory = self.target_inventory_usd
                current_inventory = sum(
                    position.size * position.avg_price for position in self.positions.values()
                )
                inventory_skew = (current_inventory - target_inventory) / total_exposure
            
            # Calculate cancel rate
            total_cancels = sum(self.cancel_counts.values())
            cancel_rate_per_min = total_cancels / max(len(self.config.trading.symbols), 1)
            
            return RiskMetrics(
                timestamp=datetime.now(timezone.utc),
                total_pnl=self.daily_pnl,
                unrealized_pnl=Decimal(0),  # Would need mark-to-market calculation
                realized_pnl=self.daily_pnl,
                total_exposure_usd=total_exposure,
                max_drawdown=self.max_drawdown,
                cancel_rate_per_min=cancel_rate_per_min,
                fill_rate=self.fill_rate,
                avg_spread_bps=self.avg_spread_bps,
                inventory_skew=inventory_skew
            )
            
        except Exception as e:
            print(f"Error getting risk metrics: {e}")
            return RiskMetrics(
                timestamp=datetime.now(timezone.utc),
                total_pnl=Decimal(0),
                unrealized_pnl=Decimal(0),
                realized_pnl=Decimal(0),
                total_exposure_usd=Decimal(0),
                max_drawdown=Decimal(0),
                cancel_rate_per_min=Decimal(0),
                fill_rate=Decimal(0),
                avg_spread_bps=Decimal(0),
                inventory_skew=Decimal(0)
            )
    
    def get_risk_state(self) -> Dict:
        """Get current risk state."""
        return {
            "kill_switch_triggered": self.kill_switch_triggered,
            "kill_switch_reason": self.kill_switch_reason,
            "daily_pnl": str(self.daily_pnl),
            "daily_max_loss": str(self.daily_max_loss_usd),
            "max_drawdown": str(self.max_drawdown),
            "total_exposure": str(self._calculate_total_exposure()),
            "max_position_limit": str(self.max_position_usd),
            "positions": {
                symbol: {
                    "side": position.side.value,
                    "size": str(position.size),
                    "avg_price": str(position.avg_price),
                    "value": str(position.size * position.avg_price)
                }
                for symbol, position in self.positions.items()
            },
            "cancel_counts": dict(self.cancel_counts),
            "risk_warnings": self.risk_warnings[-10:],  # Last 10 warnings
            "can_place_orders": not self.kill_switch_triggered,
            "can_cancel_orders": not self.kill_switch_triggered
        }
    
    def reset(self):
        """Reset risk manager state."""
        self.positions.clear()
        self.daily_pnl = Decimal(0)
        self.max_drawdown = Decimal(0)
        self.peak_pnl = Decimal(0)
        self.kill_switch_triggered = False
        self.kill_switch_reason = ""
        self.risk_warnings.clear()
        self.cancel_counts.clear()
        self.total_turnover = Decimal(0)
        self.total_fees = Decimal(0)
        self.fill_rate = Decimal(0)
        self.avg_spread_bps = Decimal(0)
        
        # Reset cancel rate tracking
        for symbol in self.config.trading.symbols:
            self.cancel_reset_times[symbol] = datetime.now(timezone.utc)
    
    def set_callbacks(self, on_risk_alert=None, on_kill_switch=None, on_position_update=None):
        """Set risk manager callbacks."""
        self.on_risk_alert = on_risk_alert
        self.on_kill_switch = on_kill_switch
        self.on_position_update = on_position_update
