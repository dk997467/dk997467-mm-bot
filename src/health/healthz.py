"""
Health check endpoint for the market maker bot.
"""

import time
from typing import Dict, Any
from aiohttp import web
from src.common.di import AppContext


async def healthz_handler(request: web.Request) -> web.Response:
    """Health check endpoint."""
    ctx: AppContext = request.app['ctx']
    
    # Basic health status
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0"
    }
    
    # Circuit breaker state
    if hasattr(ctx, 'bybit_rest') and ctx.bybit_rest:
        circuit_state = ctx.bybit_rest.get_circuit_state()
        circuit_breaker_open = circuit_state["open"]
        health_status["circuit_breaker"] = {
            "rest": {
                "open": circuit_breaker_open,
                "error_count": circuit_state["error_count"],
                "last_error_time": circuit_state["last_error_time"],
                "open_time": circuit_state["open_time"]
            }
        }
        
        # Update circuit breaker metric
        if hasattr(ctx, 'metrics') and ctx.metrics:
            ctx.metrics.set_circuit_breaker_state(circuit_breaker_open)
        
        # Overall health based on circuit breaker
        if circuit_breaker_open:
            health_status["status"] = "degraded"
            health_status["details"] = "REST circuit breaker is open"
    
    # Risk management state
    if hasattr(ctx, 'order_reconciler') and ctx.order_reconciler:
        risk_paused = ctx.order_reconciler.is_risk_paused()
        risk_reason = ctx.order_reconciler.get_risk_pause_reason()
        
        health_status["risk_management"] = {
            "paused": risk_paused,
            "reason": risk_reason
        }
        
        if risk_paused:
            health_status["status"] = "degraded"
            if "details" not in health_status:
                health_status["details"] = ""
            health_status["details"] += f"; Risk management paused: {risk_reason}"
    
    # Connection status
    if hasattr(ctx, 'bybit_websocket') and ctx.bybit_websocket:
        health_status["connections"] = {
            "websocket": ctx.bybit_websocket.connected if hasattr(ctx.bybit_websocket, 'connected') else False
        }
    
    # Determine HTTP status code
    if health_status["status"] == "healthy":
        status_code = 200
    elif health_status["status"] == "degraded":
        status_code = 200  # Still responding, but with warnings
    else:
        status_code = 503  # Service unavailable
    
    return web.json_response(health_status, status=status_code)


async def readiness_handler(request: web.Request) -> web.Response:
    """Readiness probe endpoint."""
    ctx: AppContext = request.app['ctx']
    
    # Check if all required components are ready
    ready = True
    details = []
    
    # Check REST connector
    if hasattr(ctx, 'bybit_rest') and ctx.bybit_rest:
        if ctx.bybit_rest.is_circuit_open():
            ready = False
            details.append("REST circuit breaker is open")
    else:
        ready = False
        details.append("REST connector not available")
    
    # Check WebSocket connector
    if hasattr(ctx, 'bybit_websocket') and ctx.bybit_websocket:
        if not getattr(ctx.bybit_websocket, 'connected', False):
            ready = False
            details.append("WebSocket not connected")
    else:
        ready = False
        details.append("WebSocket connector not available")
    
    # Check order manager
    if not hasattr(ctx, 'order_manager') or not ctx.order_manager:
        ready = False
        details.append("Order manager not available")
    
    # Check order reconciler
    if not hasattr(ctx, 'order_reconciler') or not ctx.order_reconciler:
        ready = False
        details.append("Order reconciler not available")
    
    readiness_status = {
        "ready": ready,
        "timestamp": time.time(),
        "details": details
    }
    
    status_code = 200 if ready else 503
    return web.json_response(readiness_status, status=status_code)


def setup_health_routes(app: web.Application):
    """Setup health check routes."""
    app.router.add_get('/healthz', healthz_handler)
    app.router.add_get('/ready', readiness_handler)
