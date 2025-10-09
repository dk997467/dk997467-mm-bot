"""
Async Tick Orchestrator - параллельная обработка символов с коалесингом команд.

Цель: P95(tick) < 200ms за счёт:
- Параллельной обработки символов (asyncio.gather)
- Коалесинга cancel/place операций через CommandBus
- Batch API вызовов к бирже
"""
import time
import asyncio
from typing import Dict, List, Optional, Any
from collections import defaultdict

from src.common.di import AppContext
from src.execution.command_bus import CommandBus, Command, CmdType
from src.connectors.bybit_rest import BybitRESTConnector
from src.metrics.exporter import Metrics


class AsyncTickOrchestrator:
    """
    Async orchestrator для параллельной обработки тиков.
    
    Features:
    - Parallel symbol processing (asyncio.gather)
    - Command coalescing (cancel/place batching)
    - Metrics: tick_duration_ms, cmd_coalesced_total, exchange_req_ms
    """
    
    def __init__(self, ctx: AppContext, connector: BybitRESTConnector, metrics: Optional[Metrics] = None):
        """
        Инициализация.
        
        Args:
            ctx: Application context с конфигурацией
            connector: REST connector для batch API
            metrics: Metrics exporter (optional)
        """
        self.ctx = ctx
        self.connector = connector
        self.metrics = metrics
        
        # Load async_batch config
        async_batch_cfg = getattr(ctx.cfg, 'async_batch', None)
        if async_batch_cfg:
            self.enabled = async_batch_cfg.enabled
            self.max_parallel = async_batch_cfg.max_parallel_symbols
            self.coalesce_cancel = async_batch_cfg.coalesce_cancel
            self.coalesce_place = async_batch_cfg.coalesce_place
            self.tick_deadline_ms = async_batch_cfg.tick_deadline_ms
        else:
            # Defaults
            self.enabled = True
            self.max_parallel = 10
            self.coalesce_cancel = True
            self.coalesce_place = True
            self.tick_deadline_ms = 200
        
        # Command bus для коалесинга
        self.cmd_bus = CommandBus(feature_enabled=self.enabled)
        
        # Metrics tracking
        self.tick_durations: List[float] = []  # для P95 расчёта
        self.total_ticks = 0
        self.total_coalesced_cancels = 0
        self.total_coalesced_places = 0
        
        print(f"[ASYNC-ORCH] Initialized: enabled={self.enabled}, max_parallel={self.max_parallel}")
    
    async def process_tick(self, symbols: List[str], orderbooks: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обработать один тик для всех символов (parallel + coalescing).
        
        Args:
            symbols: List of symbols to process
            orderbooks: {symbol: orderbook_data}
        
        Returns:
            Tick result with stats
        """
        tick_start = time.time()
        self.total_ticks += 1
        
        if not self.enabled:
            # Legacy sequential mode (rollback)
            result = await self._process_sequential(symbols, orderbooks)
        else:
            # Async parallel mode
            result = await self._process_parallel(symbols, orderbooks)
        
        tick_duration_ms = (time.time() - tick_start) * 1000
        self.tick_durations.append(tick_duration_ms)
        
        # Trim durations buffer (keep last 1000)
        if len(self.tick_durations) > 1000:
            self.tick_durations = self.tick_durations[-1000:]
        
        # Export metrics
        if self.metrics:
            self.metrics.histogram("mm_tick_duration_ms", tick_duration_ms)
            
            # Export coalescing stats
            stats = self.cmd_bus.get_stats()
            for op, count in stats.get("coalesce_stats", {}).items():
                self.metrics.counter_inc("mm_cmd_coalesced_total", labels={"op": op}, value=count)
        
        result["tick_duration_ms"] = tick_duration_ms
        result["p95_tick_ms"] = self._compute_p95()
        
        return result
    
    async def _process_sequential(self, symbols: List[str], orderbooks: Dict[str, Any]) -> Dict[str, Any]:
        """Legacy sequential processing (fallback when async_batch=false)."""
        results = []
        
        for symbol in symbols:
            ob = orderbooks.get(symbol)
            if not ob:
                continue
            
            # Process symbol sequentially (old behavior)
            result = await self._process_symbol(symbol, ob)
            results.append(result)
        
        return {
            "mode": "sequential",
            "symbols_processed": len(results),
            "results": results
        }
    
    async def _process_parallel(self, symbols: List[str], orderbooks: Dict[str, Any]) -> Dict[str, Any]:
        """Parallel processing with command coalescing."""
        # Clear command bus for new tick
        self.cmd_bus.clear()
        
        # Step 1: Process symbols in parallel (quote generation)
        tasks = []
        for symbol in symbols[:self.max_parallel]:  # Limit parallel symbols
            ob = orderbooks.get(symbol)
            if ob:
                tasks.append(self._process_symbol_async(symbol, ob))
        
        # Wait for all symbol processing to complete
        symbol_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Step 2: Coalesce commands and flush to exchange
        flush_result = await self._flush_commands()
        
        return {
            "mode": "parallel",
            "symbols_processed": len([r for r in symbol_results if not isinstance(r, Exception)]),
            "symbol_errors": len([r for r in symbol_results if isinstance(r, Exception)]),
            "flush_result": flush_result
        }
    
    async def _process_symbol(self, symbol: str, orderbook: Any) -> Dict[str, Any]:
        """Process single symbol (legacy non-async)."""
        # Placeholder: implement actual quote generation logic
        # This would call into quote_loop or strategy
        return {"symbol": symbol, "status": "processed"}
    
    async def _process_symbol_async(self, symbol: str, orderbook: Any) -> Dict[str, Any]:
        """
        Process single symbol asynchronously (enqueue commands to bus).
        
        This method generates quotes and enqueues cancel/place commands
        instead of executing them immediately.
        """
        try:
            # Example: generate quotes (pseudo-code)
            # quotes = self.strategy.generate_quotes(symbol, orderbook)
            
            # For demo: enqueue some cancel/place commands
            # In real implementation, this would come from quote_loop
            
            # Cancel old orders
            # for order_id in old_orders:
            #     self.cmd_bus.enqueue(Command(
            #         cmd_type=CmdType.CANCEL,
            #         symbol=symbol,
            #         params={"order_id": order_id}
            #     ))
            
            # Place new orders
            # for quote in quotes:
            #     self.cmd_bus.enqueue(Command(
            #         cmd_type=CmdType.PLACE,
            #         symbol=symbol,
            #         params={
            #             "side": quote.side,
            #             "qty": quote.qty,
            #             "price": quote.price
            #         }
            #     ))
            
            return {"symbol": symbol, "status": "ok"}
        except Exception as e:
            print(f"[ERROR] Symbol {symbol} processing failed: {e}")
            return {"symbol": symbol, "status": "error", "error": str(e)}
    
    async def _flush_commands(self) -> Dict[str, Any]:
        """
        Flush коалесированных команд к бирже (batch API).
        
        Returns:
            Flush statistics
        """
        coalesced_ops = self.cmd_bus.get_coalesced_ops()
        
        flush_start = time.time()
        total_success = 0
        total_failed = 0
        
        # Execute batch operations per symbol
        for symbol, commands in coalesced_ops.items():
            for cmd in commands:
                req_start = time.time()
                
                try:
                    if cmd.cmd_type == CmdType.CANCEL and cmd.params.get("batch"):
                        # Batch cancel
                        order_ids = cmd.params.get("order_ids", [])
                        client_order_ids = cmd.params.get("client_order_ids", [])
                        
                        if order_ids or client_order_ids:
                            result = await self.connector.batch_cancel_orders(
                                symbol=symbol,
                                order_ids=order_ids if order_ids else None,
                                client_order_ids=client_order_ids if client_order_ids else None
                            )
                            total_success += result.get("success_count", 0)
                            total_failed += result.get("failed_count", 0)
                            self.total_coalesced_cancels += len(order_ids) + len(client_order_ids)
                    
                    elif cmd.cmd_type == CmdType.PLACE and cmd.params.get("batch"):
                        # Batch place
                        orders = cmd.params.get("orders", [])
                        
                        if orders:
                            result = await self.connector.batch_place_orders(
                                symbol=symbol,
                                orders=orders
                            )
                            total_success += result.get("success_count", 0)
                            total_failed += result.get("failed_count", 0)
                            self.total_coalesced_places += len(orders)
                    
                    else:
                        # Non-batch command (amend or individual)
                        # Execute individually
                        pass
                    
                    # Record request latency
                    req_latency_ms = (time.time() - req_start) * 1000
                    if self.metrics:
                        self.metrics.histogram("mm_exchange_req_ms", req_latency_ms, 
                                             labels={"verb": cmd.cmd_type.value, "api": "batch"})
                
                except Exception as e:
                    print(f"[ERROR] Flush command failed for {symbol}: {e}")
                    total_failed += 1
        
        flush_duration_ms = (time.time() - flush_start) * 1000
        
        return {
            "flush_duration_ms": flush_duration_ms,
            "total_success": total_success,
            "total_failed": total_failed,
            "coalesced_cancels": self.total_coalesced_cancels,
            "coalesced_places": self.total_coalesced_places
        }
    
    def _compute_p95(self) -> float:
        """Compute P95 tick duration from recent history."""
        if not self.tick_durations:
            return 0.0
        
        sorted_durations = sorted(self.tick_durations)
        p95_idx = int(len(sorted_durations) * 0.95)
        
        return sorted_durations[p95_idx] if p95_idx < len(sorted_durations) else sorted_durations[-1]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return {
            "total_ticks": self.total_ticks,
            "p95_tick_ms": self._compute_p95(),
            "avg_tick_ms": sum(self.tick_durations) / max(1, len(self.tick_durations)),
            "total_coalesced_cancels": self.total_coalesced_cancels,
            "total_coalesced_places": self.total_coalesced_places,
            "command_bus_stats": self.cmd_bus.get_stats()
        }

