"""
Пример интеграции AsyncTickOrchestrator в существующий quote_loop.

Показывает, как переключиться с sequential на async batching.
"""
import asyncio
from typing import Dict, List, Any, Optional

from src.common.di import AppContext
from src.strategy.quote_loop import QuoteLoop
from src.strategy.async_tick_orchestrator import AsyncTickOrchestrator
from src.execution.command_bus import Command, CmdType
from src.execution.order_manager import OrderManager
from src.connectors.bybit_rest import BybitRESTConnector


class AsyncQuoteLoop(QuoteLoop):
    """
    Enhanced QuoteLoop с async batch processing.
    
    Наследует от QuoteLoop и добавляет async orchestrator.
    """
    
    def __init__(self, ctx: AppContext, order_manager: OrderManager, connector: BybitRESTConnector):
        """
        Инициализация.
        
        Args:
            ctx: Application context
            order_manager: Order manager
            connector: REST connector для batch API
        """
        super().__init__(ctx, order_manager)
        
        # Initialize async orchestrator
        self.orchestrator = AsyncTickOrchestrator(
            ctx=ctx,
            connector=connector,
            metrics=getattr(ctx, 'metrics', None)
        )
        
        self.async_enabled = getattr(ctx.cfg, 'async_batch', None) and ctx.cfg.async_batch.enabled
        
        print(f"[ASYNC-QUOTE-LOOP] Initialized: async_batch={self.async_enabled}")
    
    async def process_tick_async(self, symbols: List[str], orderbooks: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process tick with async batching.
        
        Args:
            symbols: List of symbols to process
            orderbooks: {symbol: orderbook_data}
        
        Returns:
            Tick result
        """
        if not self.async_enabled:
            # Rollback: use legacy sequential processing
            return await self._process_tick_sequential(symbols, orderbooks)
        
        # Step 1: Generate quotes for all symbols (parallel)
        await self._generate_quotes_parallel(symbols, orderbooks)
        
        # Step 2: Orchestrator flushes coalesced commands
        result = await self.orchestrator.process_tick(symbols, orderbooks)
        
        return result
    
    async def _generate_quotes_parallel(self, symbols: List[str], orderbooks: Dict[str, Any]) -> None:
        """
        Generate quotes for all symbols in parallel.
        
        Instead of executing orders immediately, enqueue commands to orchestrator.
        """
        tasks = []
        for symbol in symbols:
            ob = orderbooks.get(symbol)
            if ob:
                tasks.append(self._generate_quotes_for_symbol(symbol, ob))
        
        # Wait for all quote generation to complete
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _generate_quotes_for_symbol(self, symbol: str, orderbook: Any) -> None:
        """
        Generate quotes for single symbol and enqueue commands.
        
        This is where the magic happens: instead of calling
        connector.place_order() or connector.cancel_order() directly,
        we enqueue commands to the orchestrator's command bus.
        """
        try:
            # Example: Check if we need to cancel old orders
            active_orders = self.order_manager.get_active_orders(symbol)
            
            for order in active_orders:
                # Check if order needs to be cancelled (e.g., price moved)
                if self._should_cancel_order(order, orderbook):
                    # Enqueue cancel command
                    self.orchestrator.cmd_bus.enqueue(
                        Command(
                            cmd_type=CmdType.CANCEL,
                            symbol=symbol,
                            params={"order_id": order.order_id}
                        )
                    )
            
            # Example: Generate new quotes
            quotes = self._calculate_quotes(symbol, orderbook)
            
            for quote in quotes:
                # Enqueue place command
                self.orchestrator.cmd_bus.enqueue(
                    Command(
                        cmd_type=CmdType.PLACE,
                        symbol=symbol,
                        params={
                            "side": quote.side,
                            "qty": quote.qty,
                            "price": quote.price,
                            "order_type": "Limit",
                            "time_in_force": "GTC"
                        }
                    )
                )
        
        except Exception as e:
            print(f"[ERROR] Quote generation failed for {symbol}: {e}")
    
    def _should_cancel_order(self, order: Any, orderbook: Any) -> bool:
        """
        Check if order should be cancelled.
        
        Uses existing fast-cancel logic from QuoteLoop.
        """
        # Check fast-cancel threshold
        if not self.fast_cancel_enabled:
            return False
        
        mid_price = self._get_mid_price(orderbook)
        if not mid_price:
            return False
        
        # Calculate price deviation
        order_price = float(order.price)
        deviation_bps = abs((mid_price - order_price) / mid_price) * 10000
        
        return deviation_bps > self.cancel_threshold_bps
    
    def _calculate_quotes(self, symbol: str, orderbook: Any) -> List[Any]:
        """
        Calculate quotes for symbol.
        
        Uses existing quote logic from QuoteLoop (adaptive spread, inventory skew, etc.).
        """
        # Placeholder: implement actual quote calculation
        # This would use adaptive_spread, risk_guards, inventory_skew, etc.
        
        # Example: simple quote generation
        mid_price = self._get_mid_price(orderbook)
        if not mid_price:
            return []
        
        # Use adaptive spread if enabled
        if self.adaptive_spread_enabled and self.adaptive_spread:
            spread_bps = self.adaptive_spread.compute_spread_bps(
                liquidity_bid=1000.0,
                liquidity_ask=1000.0
            )
        else:
            spread_bps = 1.0
        
        half_spread = mid_price * spread_bps / 10000 / 2
        
        quotes = [
            # Buy quote
            type('Quote', (), {
                'side': 'Buy',
                'qty': 1.0,
                'price': mid_price - half_spread
            })(),
            # Sell quote
            type('Quote', (), {
                'side': 'Sell',
                'qty': 1.0,
                'price': mid_price + half_spread
            })()
        ]
        
        return quotes
    
    def _get_mid_price(self, orderbook: Any) -> Optional[float]:
        """Get mid price from orderbook."""
        try:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return None
            
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            
            return (best_bid + best_ask) / 2
        except Exception:
            return None
    
    async def _process_tick_sequential(self, symbols: List[str], orderbooks: Dict[str, Any]) -> Dict[str, Any]:
        """
        Legacy sequential processing (rollback).
        
        Uses original QuoteLoop logic.
        """
        results = []
        
        for symbol in symbols:
            ob = orderbooks.get(symbol)
            if not ob:
                continue
            
            # Process symbol sequentially (old behavior)
            # This would call connector.place_order() / cancel_order() directly
            result = {"symbol": symbol, "status": "processed_sequential"}
            results.append(result)
        
        return {
            "mode": "sequential",
            "symbols_processed": len(results),
            "results": results
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics.
        
        Returns:
            Stats including P95 tick duration, coalescing stats, etc.
        """
        return self.orchestrator.get_stats()


# Example usage:
async def example_usage():
    """Example of how to use AsyncQuoteLoop."""
    # Initialize (pseudo-code)
    # ctx = AppContext(config)
    # order_manager = OrderManager(ctx)
    # connector = BybitRESTConnector(ctx)
    # 
    # quote_loop = AsyncQuoteLoop(ctx, order_manager, connector)
    # 
    # # Process tick
    # symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    # orderbooks = {
    #     "BTCUSDT": {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]},
    #     "ETHUSDT": {"bids": [[3000, 1.0]], "asks": [[3010, 1.0]]},
    #     "SOLUSDT": {"bids": [[100, 1.0]], "asks": [[101, 1.0]]}
    # }
    # 
    # result = await quote_loop.process_tick_async(symbols, orderbooks)
    # 
    # # Check performance
    # stats = quote_loop.get_performance_stats()
    # print(f"P95 tick duration: {stats['p95_tick_ms']:.2f}ms")
    # print(f"Coalesced cancels: {stats['total_coalesced_cancels']}")
    # print(f"Coalesced places: {stats['total_coalesced_places']}")
    
    pass

