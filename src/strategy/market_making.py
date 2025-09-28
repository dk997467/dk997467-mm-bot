"""
Market making strategy implementation with EnhancedQuoter integration.
"""

from typing import Any, Callable, Dict, Optional, Union
from decimal import Decimal

from src.common.di import AppContext
from src.common.models import OrderBook, QuoteRequest, Side, TimeInForce
from src.strategy.enhanced_quoting import EnhancedQuoter


class MarketMakingStrategy:
    """Market making strategy with optional EnhancedQuoter integration."""
    
    def __init__(self, config, data_recorder, metrics_exporter=None, ctx: Optional[AppContext] = None):
        """Initialize strategy with config and recorder."""
        self.config = config
        self.data_recorder = data_recorder
        self.metrics_exporter = metrics_exporter
        self.ctx = ctx
        self.order_callback = None
        self.quote_callback = None
        
        # Initialize EnhancedQuoter if feature flag is enabled
        self.enhanced_quoter = None
        if hasattr(config, 'strategy') and hasattr(config.strategy, 'enable_enhanced_quoting') and config.strategy.enable_enhanced_quoting:
            if ctx is None:
                raise ValueError("AppContext is required when enable_enhanced_quoting is True")
            self.enhanced_quoter = EnhancedQuoter(ctx)
            print("EnhancedQuoter initialized")
        else:
            print("Using legacy quoting strategy")
    
    def set_order_callback(self, callback: Callable):
        """Set order placement callback."""
        self.order_callback = callback
    
    def set_quote_callback(self, callback: Callable):
        """Set quote generation callback."""
        self.quote_callback = callback
    
    async def start(self):
        """Start the strategy."""
        if self.enhanced_quoter:
            print("EnhancedQuoter strategy started")
        else:
            print("Legacy strategy started")
    
    async def stop(self):
        """Stop the strategy."""
        if self.enhanced_quoter:
            print("EnhancedQuoter strategy stopped")
        else:
            print("Legacy strategy stopped")
    
    async def on_orderbook_update(self, orderbook: Union[Dict[str, Any], OrderBook]):
        """Handle orderbook updates."""
        if self.enhanced_quoter:
            # Use EnhancedQuoter for quote generation
            await self._handle_orderbook_with_enhanced_quoter(orderbook)
        else:
            # Fall back to legacy behavior
            await self._handle_orderbook_legacy(orderbook)
    
    async def _handle_orderbook_with_enhanced_quoter(self, orderbook: Union[Dict[str, Any], OrderBook]):
        """Handle orderbook updates using EnhancedQuoter."""
        try:
            # Convert dict to OrderBook if needed
            if isinstance(orderbook, dict):
                # Extract symbol and orderbook data
                symbol = orderbook.get('symbol', 'UNKNOWN')
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                # Create simplified orderbook for EnhancedQuoter
                # Note: EnhancedQuoter expects specific format, adjust as needed
                processed_orderbook = {
                    'symbol': symbol,
                    'bids': bids,
                    'asks': asks,
                    'timestamp': orderbook.get('timestamp')
                }
            else:
                processed_orderbook = orderbook
            
            # Generate quotes using EnhancedQuoter
            symbol = processed_orderbook.get('symbol', 'UNKNOWN')
            raw_quotes = self.enhanced_quoter.generate_quotes(symbol, processed_orderbook)
            
            # Convert EnhancedQuoter quotes to standard QuoteRequest format
            quotes = []
            for raw_quote in raw_quotes:
                try:
                    # Convert side from "bid"/"ask" to Side.BUY/Side.SELL
                    side = Side.BUY if raw_quote.side == "bid" else Side.SELL
                    
                    # Convert size to qty and ensure proper format
                    qty = raw_quote.size if hasattr(raw_quote, 'size') else raw_quote.qty
                    
                    # Create standard QuoteRequest
                    quote = QuoteRequest(
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        price=raw_quote.price,
                        post_only=True,
                        time_in_force=TimeInForce.GTC
                    )
                    quotes.append(quote)
                except Exception as e:
                    print(f"Error converting quote: {e}")
                    continue
            
            # Send quotes through the same order pipeline
            if quotes and self.quote_callback:
                for quote in quotes:
                    await self.quote_callback(quote)
                    
        except Exception as e:
            print(f"Error in EnhancedQuoter orderbook handling: {e}")
    
    async def _handle_orderbook_legacy(self, orderbook: Union[Dict[str, Any], OrderBook]):
        """Handle orderbook updates using legacy strategy."""
        # Legacy implementation - can be empty or contain fallback logic
        pass
    
    def get_strategy_state(self) -> Dict[str, Any]:
        """Get current strategy state."""
        return {
            "status": "running",
            "quoting_engine": "enhanced" if self.enhanced_quoter else "legacy",
            "enhanced_features": {
                "dynamic_spread": getattr(self.config.strategy, 'enable_dynamic_spread', False),
                "inventory_skew": getattr(self.config.strategy, 'enable_inventory_skew', False),
                "adverse_guard": getattr(self.config.strategy, 'enable_adverse_guard', False)
            } if hasattr(self.config, 'strategy') else {}
        }
