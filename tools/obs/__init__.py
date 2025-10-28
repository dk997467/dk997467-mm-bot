"""
Observability package for MM-Bot.

Includes:
- jsonlog: Structured JSON logging with determinism and secret masking
- health_server: Health/Ready HTTP endpoints
- metrics: Prometheus-compatible metrics (Counter, Gauge, Histogram)
"""

__all__ = ["jsonlog", "health_server", "metrics"]

