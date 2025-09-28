"""
Prometheus metrics exporter for market making bot.

Enhanced with:
- Rich flow, risk, market, system metrics
- Config gauges (cfg_*) updated on reload
- DI-based design using AppContext
- No global singletons
"""

import asyncio
import time
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, List

from prometheus_client import (
    Counter, Gauge, Histogram, Summary, generate_latest, CONTENT_TYPE_LATEST,
    REGISTRY, start_http_server
)

from functools import lru_cache
from src.common.config import Config, AppConfig
from src.common.models import RiskMetrics
from src.common.di import AppContext


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
    """Production-ready metrics with exact names/labels; no globals."""
    
    def __init__(self, ctx: AppContext):
        """Initialize metrics with AppContext."""
        self.ctx = ctx
        self._rate_logger = RateLimitedLogger()
        
        # Flow metrics - EXACT names/labels
        self.orders_active = Gauge('orders_active', 'Active orders by symbol and side', ['symbol', 'side'])
        self.creates_total = Counter('creates_total', 'Total orders created', ['symbol'])
        self.cancels_total = Counter('cancels_total', 'Total orders cancelled', ['symbol'])
        self.replaces_total = Counter('replaces_total', 'Total orders replaced/amended', ['symbol'])
        self.quotes_placed_total = Counter('quotes_placed_total', 'Total quotes placed', ['symbol'])
        
        # Rate metrics (computed from timestamps)
        self.create_rate = Gauge('create_rate', 'Orders created per second', ['symbol'])
        self.cancel_rate = Gauge('cancel_rate', 'Orders cancelled per second', ['symbol'])
        
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
        self.risk_paused = Gauge('risk_paused', 'Risk management paused (0/1)', [])
        self.drawdown_day = Gauge('drawdown_day', 'Daily drawdown percentage', [])
        
        # Market metrics
        self.spread_bps = Gauge('spread_bps', 'Current spread in basis points', ['symbol'])
        self.vola_1m = Gauge('vola_1m', '1-minute volatility', ['symbol'])
        self.ob_imbalance = Gauge('ob_imbalance', 'Order book imbalance', ['symbol'])
        
        # Config gauges (updated on reload) - EXACT names
        self.cfg_levels_per_side = Gauge('cfg_levels_per_side', 'Configured levels per side', [])
        self.cfg_min_time_in_book_ms = Gauge('cfg_min_time_in_book_ms', 'Configured min time in book (ms)', [])
        self.cfg_k_vola_spread = Gauge('cfg_k_vola_spread', 'Configured volatility spread coefficient', [])
        self.cfg_skew_coeff = Gauge('cfg_skew_coeff', 'Configured inventory skew coefficient', [])
        self.cfg_imbalance_cutoff = Gauge('cfg_imbalance_cutoff', 'Configured imbalance cutoff', [])
        self.cfg_max_create_per_sec = Gauge('cfg_max_create_per_sec', 'Configured max create rate per second', [])
        self.cfg_max_cancel_per_sec = Gauge('cfg_max_cancel_per_sec', 'Configured max cancel rate per second', [])
        
        # Initialize config gauges
        self.export_cfg_gauges(ctx.cfg)
    
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
        elif action == "cancel":
            self.cancels_total.labels(symbol=symbol).inc(count)
        elif action == "replace":
            self.replaces_total.labels(symbol=symbol).inc(count)
    
    def update_quote_metrics(self, symbol: str, count: int = 1) -> None:
        """Update quote-related metrics."""
        self.quotes_placed_total.labels(symbol=symbol).inc(count)
    
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
        self.position_size = Gauge('market_maker_position_size', 'Current position size', ['symbol', 'side'])
        
        # Initialize config gauges
        self.export_cfg_gauges(ctx.cfg)
    
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
        
        # Rate tracking (per-symbol deque timestamps)
        self._create_timestamps = {}  # symbol -> deque of timestamps
        self._cancel_timestamps = {}  # symbol -> deque of timestamps
    
    def record_order_created(self, symbol: str) -> None:
        """Record order creation and update rate."""
        from collections import deque
        import time
        
        if symbol not in self._create_timestamps:
            self._create_timestamps[symbol] = deque(maxlen=100)  # Keep last 100 timestamps
        
        now = time.time()
        self._create_timestamps[symbol].append(now)
        self.creates_total.labels(symbol=symbol).inc()
        
        # Update rate (orders per second over last 10 seconds)
        recent = [ts for ts in self._create_timestamps[symbol] if now - ts <= 10.0]
        rate = len(recent) / 10.0 if recent else 0.0
        self.create_rate.labels(symbol=symbol).set(rate)
    
    def record_order_cancelled(self, symbol: str) -> None:
        """Record order cancellation and update rate."""
        from collections import deque
        import time
        
        if symbol not in self._cancel_timestamps:
            self._cancel_timestamps[symbol] = deque(maxlen=100)
        
        now = time.time()
        self._cancel_timestamps[symbol].append(now)
        self.cancels_total.labels(symbol=symbol).inc()
        
        # Update rate
        recent = [ts for ts in self._cancel_timestamps[symbol] if now - ts <= 10.0]
        rate = len(recent) / 10.0 if recent else 0.0
        self.cancel_rate.labels(symbol=symbol).set(rate)
    
    def record_order_replaced(self, symbol: str) -> None:
        """Record order replacement/amendment."""
        self.replaces_total.labels(symbol=symbol).inc()
    
    def record_quote_placed(self, symbol: str) -> None:
        """Record quote placement."""
        self.quotes_placed_total.labels(symbol=symbol).inc()
    
    def update_active_orders(self, symbol: str, side: str, count: int) -> None:
        """Update active orders count."""
        self.orders_active.labels(symbol=symbol, side=side).set(count)
    
    def update_maker_pnl(self, symbol: str, pnl: float) -> None:
        """Update maker P&L."""
        self.maker_pnl.labels(symbol=symbol).set(pnl)
    
    def update_taker_fees(self, symbol: str, fees: float) -> None:
        """Update taker fees."""
        self.taker_fees.labels(symbol=symbol).set(fees)
    
    def update_inventory_abs(self, symbol: str, value: float) -> None:
        """Update absolute inventory value."""
        self.inventory_abs.labels(symbol=symbol).set(value)
    
    def observe_latency(self, stage: str, latency_ms: float) -> None:
        """Observe latency for a stage."""
        self.latency_ms.labels(stage=stage).observe(latency_ms)
    
    def update_ws_reconnects(self, exchange: str, count: int) -> None:
        """Update WebSocket reconnection count."""
        self.ws_reconnects_total.labels(exchange=exchange).set(count)
    
    def update_rest_error_rate(self, exchange: str, rate: float) -> None:
        """Update REST API error rate."""
        self.rest_error_rate.labels(exchange=exchange).set(rate)
    
    def update_risk_paused(self, paused: bool) -> None:
        """Update risk management paused status."""
        self.risk_paused.set(1 if paused else 0)
    
    def update_drawdown_day(self, drawdown: float) -> None:
        """Update daily drawdown percentage."""
        self.drawdown_day.set(drawdown)
    
    def update_spread_bps(self, symbol: str, spread: float) -> None:
        """Update current spread in basis points."""
        self.spread_bps.labels(symbol=symbol).set(spread)
    
    def update_vola_1m(self, symbol: str, vola: float) -> None:
        """Update 1-minute volatility."""
        self.vola_1m.labels(symbol=symbol).set(vola)
    
    def update_ob_imbalance(self, symbol: str, imbalance: float) -> None:
        """Update order book imbalance."""
        self.ob_imbalance.labels(symbol=symbol).set(imbalance)


class MetricsExporter:
    """Prometheus metrics exporter for market making bot.
    
    Now uses Metrics class for DI-based design.
    """
    
    def __init__(self, config: Config | AppConfig, recorder=None):
        """Initialize the metrics exporter."""
        self.config = config
        self.port = config.monitoring.metrics_port
        self.recorder = recorder
        self._rate_logger = RateLimitedLogger()
        
        # Create Metrics instance if AppConfig is provided
        self.metrics = None
        if hasattr(config, 'config_version'):  # AppConfig
            from src.common.di import AppContext
            ctx = AppContext(cfg=config)
            self.metrics = Metrics(ctx)
        
        # Trading metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.orders_placed = Counter(
        #     'market_maker_orders_placed_total',
        #     'Total orders placed',
        #     ['symbol', 'side', 'status']
        # )
        # 
        # self.orders_cancelled = Counter(
        #     'market_maker_orders_cancelled_total',
        #     'Total orders cancelled',
        #     ['symbol', 'side']
        # )
        # 
        # self.orders_filled = Counter(
        #     'market_maker_orders_filled_total',
        #     'Total orders filled',
        #     ['symbol', 'side']
        # )
        # 
        # self.orders_rejected = Counter(
        #     'market_maker_orders_rejected_total',
        #     'Total orders rejected',
        #     ['symbol', 'side', 'reason']
        # )
        
        # P&L metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.realized_pnl = Gauge(
        #     'market_maker_realized_pnl_usd',
        #     'Realized P&L in USD',
        #     ['symbol']
        # )
        # 
        # self.unrealized_pnl = Gauge(
        #     'market_maker_unrealized_pnl_usd',
        #     'Unrealized P&L in USD',
        #     ['symbol']
        # )
        # 
        # self.total_pnl = Gauge(
        #     'market_maker_total_pnl_usd',
        #     'Total P&L in USD',
        #     ['symbol']
        # )
        # 
        # self.daily_pnl = Gauge(
        #     'market_maker_daily_pnl_usd',
        #     'Daily P&L in USD',
        #     ['symbol']
        # )
        
        # Position metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.position_size = Gauge(
        #     'market_maker_position_size',
        #     'Current position size',
        #     ['symbol', 'side']
        # )
        # 
        # self.position_value_usd = Gauge(
        #     'market_maker_position_value_usd',
        #     'Current position value in USD',
        #     ['symbol']
        # )
        # 
        # self.total_exposure_usd = Gauge(
        #     'market_maker_total_exposure_usd',
        #     'Total exposure across all positions',
        #     ['symbol']
        # )
        
        # Risk metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.max_drawdown_usd = Gauge(
        #     'market_maker_max_drawdown_usd',
        #     'Maximum drawdown in USD',
        #     ['symbol']
        # )
        # 
        # self.cancel_rate_per_min = Gauge(
        #     'market_maker_cancel_rate_per_min',
        #     'Cancel rate per minute',
        #     ['symbol']
        # )
        # 
        # self.risk_alerts = Counter(
        #     'market_maker_risk_alerts_total',
        #     'Total risk alerts',
        #     ['symbol', 'alert_type']
        # )
        
        # Performance metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.fill_rate = Gauge(
        #     'market_maker_fill_rate',
        #     'Order fill rate (0-1)',
        #     ['symbol']
        # )
        # 
        # self.avg_spread_bps = Gauge(
        #     'market_maker_avg_spread_bps',
        #     'Average spread in basis points',
        #     ['symbol']
        # )
        # 
        # self.inventory_skew = Gauge(
        #     'market_maker_inventory_skew',
        #     'Inventory skew (-1 to 1)',
        #     ['symbol']
        # )
        # 
        # self.volatility = Gauge(
        #     'market_maker_volatility',
        #     'Price volatility',
        #     ['symbol']
        # )
        
        # Latency metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.order_latency = Histogram(
        #     'market_maker_order_latency_seconds',
        #     'Order placement latency in seconds',
        #     ['symbol', 'side'],
        #     buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
        # )
        # 
        # self.websocket_latency = Histogram(
        #     'market_maker_websocket_latency_seconds',
        #     'WebSocket message processing latency in seconds',
        #     ['symbol', 'message_type'],
        #     buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
        # )
        
        # REST API metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.rest_api_latency = Histogram(
        #     'market_maker_rest_api_latency_seconds',
        #     'REST API call latency in seconds',
        #     ['endpoint', 'method'],
        #     buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
        # )
        
        # Connection metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.websocket_connected = Gauge(
        #     'market_maker_websocket_connected',
        #     'WebSocket connection status (1=connected, 0=disconnected)',
        #     ['connection_type']
        # )
        # 
        # self.websocket_reconnects = Counter(
        #     'market_maker_websocket_reconnects_total',
        #     'Total WebSocket reconnections',
        #     ['connection_type']
        # )
        
        # System metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.memory_usage_mb = Gauge(
        #     'market_maker_memory_usage_mb',
        #     'Memory usage in MB'
        # )
        # 
        # self.cpu_usage_percent = Gauge(
        #     'market_maker_cpu_usage_percent',
        #     'CPU usage percentage'
        # )
        
        # Uptime metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.uptime_seconds = Gauge(
        #     'market_maker_uptime_seconds',
        #     'Bot uptime in seconds'
        # )
        
        # Market data metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.orderbook_depth = Gauge(
        #     'market_maker_orderbook_depth',
        #     'Order book depth at price level',
        #     ['symbol', 'side', 'level']
        # )
        # 
        # self.orderbook_spread_bps = Gauge(
        #     'market_maker_orderbook_spread_bps',
        #     'Current order book spread in basis points',
        #     ['symbol']
        # )
        # 
        # self.orderbook_imbalance = Gauge(
        #     'market_maker_orderbook_imbalance',
        #     'Order book imbalance (-1 to 1)',
        #     ['symbol']
        # )
        # 
        # self.market_data_updates = Counter(
        #     'market_maker_market_data_updates_total',
        #     'Total market data updates',
        #     ['symbol', 'data_type']
        # )
        
        # Strategy metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.quotes_generated = Counter(
        #     'market_maker_quotes_generated_total',
        #     'Total quotes generated by strategy',
        #     ['symbol', 'side']
        # )
        # 
        # self.quotes_active = Gauge(
        #     'market_maker_quotes_active',
        #     'Number of active quotes',
        #     ['symbol', 'side']
        # )
        # 
        # self.strategy_update_latency = Histogram(
        #     'market_maker_strategy_update_latency_seconds',
        #     'Strategy update latency in seconds',
        #     ['symbol'],
        #     buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
        # )
        
        # Storage metrics (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.records_written = Counter(
        #     'market_maker_records_written_total',
        #     'Total records written to storage',
        #     ['data_type']
        # )
        # 
        # self.storage_buffer_size = Gauge(
        #     'market_maker_storage_buffer_size',
        #     'Current storage buffer size',
        #     ['data_type']
        # )
        # 
        # self.storage_flush_duration = Histogram(
        #     'market_maker_storage_flush_duration_seconds',
        #     'Storage flush duration in seconds',
        #     ['data_type'],
        #     buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
        # )
        
        # Start time for uptime calculation
        self.start_time = time.time()
        
        # Performance counters (legacy, kept for backward compatibility)
        # Commented out to avoid conflicts with Metrics class
        # self.quotes_generated_total = Counter("quotes_generated_total", "Total quotes generated", ["symbol"])
        # self.fills_total = Counter("fills_total", "Total fills", ["symbol"])
        # self.recorder_flush_seconds = Histogram("recorder_flush_seconds", "Recorder flush duration (s)", ["symbol"])
        
        # Global metrics (no labels)
        # Commented out to avoid conflicts with Metrics class
        # self.recorder_queue_size = Gauge("recorder_queue_size", "Recorder queue length")
        # self.errors_total = Counter("errors_total", "Runtime errors total")
        
        # HTTP server
        self.server_started = False
    
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
    
    def _safe_symbol(self, s):
        """Return safe symbol or 'ALL' if None/empty."""
        return str(s) if s is not None else "ALL"
    
    @lru_cache(maxsize=256)
    def _labels(self, metric_name: str, symbol: str):
        """Get labeled metric by name and symbol."""
        # symbol should already be processed through _safe_symbol
        if not hasattr(self, 'metrics') or self.metrics is None:
            raise AttributeError("Metrics not initialized. Use AppConfig to enable new metrics.")
        
        if metric_name == "quotes":
            return self.metrics.quotes_placed_total.labels(symbol=symbol)
        if metric_name == "orders":
            return self.metrics.creates_total.labels(symbol=symbol)
        if metric_name == "fills":
            return self.metrics.creates_total.labels(symbol=symbol)  # Use creates as fallback
        if metric_name == "flush":
            # Use a simple counter as fallback since recorder_flush_seconds is commented out
            raise KeyError("flush metrics not available in new Metrics class")
        raise KeyError(metric_name)
    
    async def start(self):
        """Start the metrics HTTP server."""
        try:
            start_http_server(self.port)
            self.server_started = True
            print(f"Metrics server started on port {self.port}")
        except Exception as e:
            print(f"Failed to start metrics server: {e}")
    
    def stop(self):
        """Stop the metrics server."""
        # Prometheus client doesn't provide a stop method
        # The server will continue running until the process exits
        print("Metrics server stopped")

    def export_cfg_gauges(self, cfg: AppConfig):
        """Export configuration values to gauges."""
        try:
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                self.metrics.export_cfg_gauges(cfg)
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
        except Exception as e:
            self._rate_logger.warn_once(f"Error exporting cfg gauges: {e}")
    
    def update_order_metrics(self, symbol: str, side: str, status: str, reason: str = ""):
        """Update order-related metrics."""
        try:
            # Validate inputs
            if not isinstance(status, str):
                self._rate_logger.warn_once(f"Expected str for order status, got {type(status)}")
                return
            
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                if status == "Cancelled":
                    self.metrics.record_order_cancelled(symbol)
                elif status == "Filled":
                    # Use creates as fallback for fills
                    pass
                elif status == "Rejected":
                    # Use creates as fallback for rejects
                    pass
                # Always increment creates for placed orders
                self.metrics.record_order_created(symbol)
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "order_metrics",
                        "symbol": symbol,
                        "side": side,
                        "status": status,
                        "reason": reason,
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error updating order metrics: {e}")
    
    def update_pnl_metrics(self, symbol: str, realized: Decimal, unrealized: Decimal, total: Decimal, daily: Decimal):
        """Update P&L metrics."""
        try:
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                # Use maker_pnl as fallback for total P&L
                self.metrics.update_maker_pnl(symbol, float(total))
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "pnl_metrics",
                        "symbol": symbol,
                        "realized": float(realized),
                        "unrealized": float(unrealized),
                        "total": float(total),
                        "daily": float(daily),
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error updating P&L metrics: {e}")
    
    def update_position_metrics(self, symbol: str, side: str, size: Decimal, value: Decimal, total_exposure: Decimal):
        """Update position metrics."""
        try:
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                # Use inventory_abs as fallback for position value
                self.metrics.update_inventory_abs(symbol, float(value))
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "position_metrics",
                        "symbol": symbol,
                        "side": side,
                        "size": float(size),
                        "value": float(value),
                        "total_exposure": float(total_exposure),
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating position metrics: {e}")
    
    def increment_quotes_generated(self, symbol: str = None):
        """Increment quotes generated counter."""
        try:
            self._labels("quotes", self._safe_symbol(symbol)).inc()
        except Exception as e:
            self._rate_logger.warn_once(f"Error incrementing quotes_generated_total: {e}")
    
    def increment_orders_placed(self, symbol: str = None):
        """Increment orders placed counter."""
        try:
            self._labels("orders", self._safe_symbol(symbol)).inc()
        except Exception as e:
            self._rate_logger.warn_once(f"Error incrementing orders_placed_total: {e}")
    
    def increment_fills_total(self, symbol: str = None):
        """Increment fills total counter."""
        try:
            self._labels("fills", self._safe_symbol(symbol)).inc()
        except Exception as e:
            self._rate_logger.warn_once(f"Error incrementing fills_total: {e}")
    
    def update_recorder_queue_size(self, size: int):
        """Update recorder queue size gauge."""
        try:
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                # No direct equivalent in new Metrics class
                pass
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
        except Exception as e:
            self._rate_logger.warn_once(f"Error updating recorder_queue_size: {e}")
    
    def observe_flush_duration(self, duration_seconds: float, symbol: str = None):
        """Observe recorder flush duration."""
        try:
            self._labels("flush", self._safe_symbol(symbol)).observe(duration_seconds)
        except Exception as e:
            self._rate_logger.warn_once(f"Error observing flush duration: {e}")
    
    def increment_errors_total(self):
        """Increment errors total counter."""
        try:
            # Use new Metrics class if available
            if hasattr(self, 'metrics') and self.metrics is not None:
                # No direct equivalent in new Metrics class
                pass
            else:
                # Fallback to legacy behavior (metrics commented out)
                pass
        except Exception as e:
            self._rate_logger.warn_once(f"Error incrementing errors_total: {e}")
    
    def update_risk_metrics(self, symbol: str, max_drawdown: Decimal, cancel_rate: Decimal, risk_alerts: int):
        """Update risk metrics."""
        try:
            self.max_drawdown_usd.labels(symbol=symbol).set(float(max_drawdown))
            self.cancel_rate_per_min.labels(symbol=symbol).set(float(cancel_rate))
            
            # Update risk alerts counter
            if risk_alerts > 0:
                self.risk_alerts.labels(symbol=symbol, alert_type="general").inc(risk_alerts)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "risk_metrics",
                        "symbol": symbol,
                        "max_drawdown": float(max_drawdown),
                        "cancel_rate": float(cancel_rate),
                        "risk_alerts": risk_alerts,
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error updating risk metrics: {e}")
    
    def update_performance_metrics(self, symbol: str, fill_rate: Decimal, avg_spread: Decimal, inventory_skew: Decimal, volatility: Decimal):
        """Update performance metrics."""
        try:
            self.fill_rate.labels(symbol=symbol).set(float(fill_rate))
            self.avg_spread_bps.labels(symbol=symbol).set(float(avg_spread))
            self.inventory_skew.labels(symbol=symbol).set(float(inventory_skew))
            self.volatility.labels(symbol=symbol).set(float(volatility))
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "performance_metrics",
                        "symbol": symbol,
                        "fill_rate": float(fill_rate),
                        "avg_spread": float(avg_spread),
                        "inventory_skew": float(inventory_skew),
                        "volatility": float(volatility),
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating performance metrics: {e}")
    
    def record_order_latency(self, symbol: str, side: str, latency_seconds: float):
        """Record order placement latency."""
        try:
            self.order_latency.labels(symbol=symbol, side=side).observe(latency_seconds)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "order_latency",
                        "symbol": symbol,
                        "side": side,
                        "latency_seconds": latency_seconds,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error recording order latency: {e}")
    
    def record_websocket_latency(self, symbol: str, message_type: str, latency_seconds: float):
        """Record WebSocket message processing latency."""
        try:
            self.websocket_latency.labels(symbol=symbol, message_type=message_type).observe(latency_seconds)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "websocket_latency",
                        "symbol": symbol,
                        "message_type": message_type,
                        "latency_seconds": latency_seconds,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error recording WebSocket latency: {e}")
    
    def record_rest_api_latency(self, endpoint: str, method: str, latency_seconds: float):
        """Record REST API call latency."""
        try:
            self.rest_api_latency.labels(endpoint=endpoint, method=method).observe(latency_seconds)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "rest_api_latency",
                        "endpoint": endpoint,
                        "method": method,
                        "latency_seconds": latency_seconds,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error recording REST API latency: {e}")
    
    def update_connection_status(self, status):
        """Update connection status from status dict."""
        try:
            if not isinstance(status, dict):
                self._rate_logger.warn_once(f"Expected dict for connection status, got {type(status)}")
                return
            
            # Update WebSocket status if available
            if "ws" in status:
                ws_connected = status["ws"] == "up"
                self.websocket_connected.labels(connection_type="public").set(1 if ws_connected else 0)
            
            # Update REST status if available
            if "rest" in status:
                rest_connected = status["rest"] == "up"
                # Note: No REST-specific metrics currently defined
            
            # Update recorder queue size if available
            if "rec_q" in status:
                self.recorder_queue_size.set(status["rec_q"])
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "connection_status",
                        "status": status,
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            self._rate_logger.warn_once(f"Error updating connection status: {e}")
    
    def update_websocket_status(self, connection_type: str, connected: bool, reconnected: bool = False):
        """Update WebSocket connection status."""
        try:
            self.websocket_connected.labels(connection_type=connection_type).set(1 if connected else 0)
            
            if reconnected:
                self.websocket_reconnects.labels(connection_type=connection_type).inc()
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "websocket_status",
                        "connection_type": connection_type,
                        "connected": connected,
                        "reconnected": reconnected,
                        "timestamp": datetime.now()
                    }
                ))
                
        except Exception as e:
            print(f"Error updating WebSocket status: {e}")
    
    def update_system_metrics(self, memory_mb: float, cpu_percent: float):
        """Update system metrics."""
        try:
            # Validate inputs
            if not isinstance(memory_mb, (int, float)) or not isinstance(cpu_percent, (int, float)):
                self._rate_logger.warn_once(f"Expected numeric values for system metrics, got {type(memory_mb)}, {type(cpu_percent)}")
                return
            
            self.memory_usage_mb.set(memory_mb)
            self.cpu_usage_percent.set(cpu_percent)
            
            # Update uptime
            uptime = time.time() - self.start_time
            self.uptime_seconds.set(uptime)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "system_metrics",
                        "memory_mb": memory_mb,
                        "cpu_percent": cpu_percent,
                        "uptime_seconds": uptime,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating system metrics: {e}")
    
    def update_orderbook_metrics(self, symbol: str, depth_data: Dict, spread_bps: Decimal, imbalance: Decimal):
        """Update order book metrics."""
        try:
            # Validate inputs
            if not isinstance(depth_data, dict):
                self._rate_logger.warn_once(f"Expected dict for depth_data, got {type(depth_data)}")
                return
            
            # Update depth at different levels
            for side in ["bid", "ask"]:
                for level, depth in enumerate(depth_data.get(side, [])[:5]):  # Top 5 levels
                    self.orderbook_depth.labels(symbol=symbol, side=side, level=level).set(float(depth))
            
            # Update spread and imbalance
            self.orderbook_spread_bps.labels(symbol=symbol).set(float(spread_bps))
            self.orderbook_imbalance.labels(symbol=symbol).set(float(imbalance))
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "orderbook_metrics",
                        "symbol": symbol,
                        "spread_bps": float(spread_bps),
                        "imbalance": float(imbalance),
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating orderbook metrics: {e}")
    
    def increment_market_data_updates(self, symbol: str, data_type: str):
        """Increment market data update counter."""
        try:
            self.market_data_updates.labels(symbol=symbol, data_type=data_type).inc()
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "market_data_updates",
                        "symbol": symbol,
                        "data_type": data_type,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error incrementing market data updates: {e}")
    
    def update_strategy_metrics(self, symbol: str, quotes_generated: int, quotes_active: int, update_latency: float):
        """Update strategy metrics."""
        try:
            # Update quote counts
            for side in ["buy", "sell"]:
                self.quotes_generated.labels(symbol=symbol, side=side).inc(quotes_generated // 2)  # Approximate split
                self.quotes_active.labels(symbol=symbol, side=side).set(quotes_active // 2)
            
            # Record update latency
            self.strategy_update_latency.labels(symbol=symbol).observe(update_latency)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "strategy_metrics",
                        "symbol": symbol,
                        "quotes_generated": quotes_generated,
                        "quotes_active": quotes_active,
                        "update_latency": update_latency,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating strategy metrics: {e}")
    
    def update_storage_metrics(self, data_type: str, records_written: int, buffer_size: int, flush_duration: float):
        """Update storage metrics."""
        try:
            self.records_written.labels(data_type=data_type).inc(records_written)
            self.storage_buffer_size.labels(data_type=data_type).set(buffer_size)
            self.storage_flush_duration.labels(data_type=data_type).observe(flush_duration)
            
            # Record metrics update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "metrics_update",
                    {
                        "type": "storage_metrics",
                        "data_type": data_type,
                        "records_written": records_written,
                        "buffer_size": buffer_size,
                        "flush_duration": flush_duration,
                        "timestamp": datetime.now()
                    }
                ))
            
        except Exception as e:
            print(f"Error updating storage metrics: {e}")
    
    def update_from_risk_metrics(self, metrics: RiskMetrics):
        """Update metrics from RiskMetrics object."""
        try:
            # Validate input
            if not isinstance(metrics, RiskMetrics):
                self._rate_logger.warn_once(f"Expected RiskMetrics object, got {type(metrics)}")
                return
            
            # This would be called periodically to sync all metrics
            # Implementation depends on how RiskMetrics is structured
            pass
            
        except Exception as e:
            self._rate_logger.warn_once(f"Error updating from risk metrics: {e}")
    
    def get_metrics_summary(self) -> Dict:
        """Get a summary of current metrics."""
        try:
            summary = {}
            
            # Collect metrics from registry
            metrics_data = generate_latest(REGISTRY).decode('utf-8')
            
            # Parse metrics data
            for line in metrics_data.split('\n'):
                if line and not line.startswith('#'):
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        metric_value = parts[1]
                        
                        # Extract metric name without labels
                        base_name = metric_name.split('{')[0]
                        if base_name not in summary:
                            summary[base_name] = {}
                        
                        # Store metric value
                        summary[base_name][metric_name] = metric_value
            
            return summary
            
        except Exception as e:
            print(f"Error getting metrics summary: {e}")
            return {}
    
    def reset_metrics(self):
        """Reset all metrics (useful for testing)."""
        try:
            # Reset all counters and gauges
            for metric in REGISTRY._collector_to_names.keys():
                if hasattr(metric, '_value'):
                    metric._value.clear()
                elif hasattr(metric, '_sum'):
                    metric._sum.clear()
                elif hasattr(metric, '_count'):
                    metric._count.clear()
            
            print("All metrics reset")
            
        except Exception as e:
            print(f"Error resetting metrics: {e}")
    
    def get_metrics_endpoint(self):
        """Get the metrics endpoint for health checks."""
        return f"http://localhost:{self.port}/metrics"
    
    def is_healthy(self) -> bool:
        """Check if metrics server is healthy."""
        return self.server_started
