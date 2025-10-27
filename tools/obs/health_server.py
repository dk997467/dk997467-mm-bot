"""
Health and Readiness HTTP server (stdlib-only).

Provides:
- GET /health: Always returns 200 OK (liveness check)
- GET /ready: Returns 200/503 based on readiness providers (readiness check)
- GET /metrics: Prometheus-compatible metrics (when integrated with metrics.py)

Uses http.server in a background thread for non-blocking operation.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Protocol


class HealthProviders(Protocol):
    """Protocol for health/readiness providers."""
    
    def state_ready(self) -> bool:
        """Check if state layer is ready."""
        ...
    
    def risk_ready(self) -> bool:
        """Check if risk monitor is ready."""
        ...
    
    def exchange_ready(self) -> bool:
        """Check if exchange connection is ready."""
        ...


class DefaultHealthProviders:
    """Default health providers (always ready)."""
    
    def state_ready(self) -> bool:
        return True
    
    def risk_ready(self) -> bool:
        return True
    
    def exchange_ready(self) -> bool:
        return True


class HealthServer:
    """
    Health/Ready/Metrics HTTP server.
    
    Runs in background thread, does not block main process.
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        providers: HealthProviders | None = None,
        metrics_renderer: Callable[[], str] | None = None,
    ):
        """
        Initialize health server.
        
        Args:
            host: Bind host (e.g. "0.0.0.0" or "127.0.0.1")
            port: Bind port
            providers: Health/readiness providers
            metrics_renderer: Optional callable that renders Prometheus metrics text
        """
        self.host = host
        self.port = port
        self.providers = providers or DefaultHealthProviders()
        self.metrics_renderer = metrics_renderer
        
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
    
    def start(self) -> None:
        """Start server in background thread (non-blocking)."""
        if self._thread is not None:
            raise RuntimeError("Server already started")
        
        # Create request handler with closure over self
        server_instance = self
        
        class Handler(BaseHTTPRequestHandler):
            """HTTP request handler with access to HealthServer instance."""
            
            def log_message(self, format: str, *args: Any) -> None:
                """Suppress default logging (we use structured logs instead)."""
                pass
            
            def do_GET(self) -> None:
                """Handle GET requests."""
                if self.path == "/health":
                    server_instance._handle_health(self)
                elif self.path == "/ready":
                    server_instance._handle_ready(self)
                elif self.path == "/metrics":
                    server_instance._handle_metrics(self)
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Not Found\n")
        
        # Create and start server
        self._server = HTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
    
    def _run(self) -> None:
        """Run server loop (called in background thread)."""
        if self._server is None:
            return
        
        # Serve until shutdown requested
        while not self._shutdown_event.is_set():
            self._server.handle_request()
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop server gracefully.
        
        Args:
            timeout: Maximum time to wait for shutdown (seconds)
        """
        if self._server is None or self._thread is None:
            return
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Close server socket to unblock handle_request()
        self._server.server_close()
        
        # Wait for thread to exit
        self._thread.join(timeout=timeout)
        
        self._server = None
        self._thread = None
    
    def _handle_health(self, handler: BaseHTTPRequestHandler) -> None:
        """
        Handle GET /health (liveness check).
        
        Always returns 200 OK - process is alive.
        """
        response = {"status": "ok"}
        self._send_json_response(handler, 200, response)
    
    def _handle_ready(self, handler: BaseHTTPRequestHandler) -> None:
        """
        Handle GET /ready (readiness check).
        
        Returns 200 if all checks pass, 503 otherwise.
        """
        checks = {
            "state": self.providers.state_ready(),
            "risk": self.providers.risk_ready(),
            "exchange": self.providers.exchange_ready(),
        }
        
        all_ready = all(checks.values())
        status_code = 200 if all_ready else 503
        
        response = {
            "status": "ok" if all_ready else "fail",
            "checks": checks,
        }
        
        self._send_json_response(handler, status_code, response)
    
    def _handle_metrics(self, handler: BaseHTTPRequestHandler) -> None:
        """
        Handle GET /metrics (Prometheus metrics).
        
        Renders metrics using the configured metrics_renderer.
        """
        if self.metrics_renderer is None:
            handler.send_response(501)
            handler.send_header("Content-Type", "text/plain")
            handler.end_headers()
            handler.wfile.write(b"Metrics not configured\n")
            return
        
        try:
            metrics_text = self.metrics_renderer()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/plain; version=0.0.4")
            handler.end_headers()
            handler.wfile.write(metrics_text.encode("utf-8"))
        except Exception as e:
            handler.send_response(500)
            handler.send_header("Content-Type", "text/plain")
            handler.end_headers()
            handler.wfile.write(f"Error rendering metrics: {e}\n".encode("utf-8"))
    
    def _send_json_response(
        self,
        handler: BaseHTTPRequestHandler,
        status_code: int,
        data: dict[str, Any],
    ) -> None:
        """Send JSON response with sorted keys (deterministic)."""
        body = json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body.encode("utf-8"))


def start_server(
    host: str,
    port: int,
    providers: HealthProviders | None = None,
    metrics_renderer: Callable[[], str] | None = None,
) -> HealthServer:
    """
    Start health/ready/metrics server in background thread.
    
    Args:
        host: Bind host (e.g. "0.0.0.0" or "127.0.0.1")
        port: Bind port
        providers: Health/readiness providers
        metrics_renderer: Optional callable that renders Prometheus metrics text
    
    Returns:
        HealthServer instance (already started)
    
    Example:
        >>> providers = MyHealthProviders()
        >>> server = start_server("127.0.0.1", 8080, providers)
        >>> # Server is now running in background
        >>> # ... do work ...
        >>> server.stop()
    """
    server = HealthServer(host, port, providers, metrics_renderer)
    server.start()
    return server

