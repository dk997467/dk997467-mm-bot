"""
Unit tests for Health Server (tools/obs/health_server.py).

Tests:
- GET /health returns 200 OK always
- GET /ready returns 200/503 based on providers
- GET /metrics returns Prometheus text
- Server start/stop lifecycle
- JSON response determinism (sorted keys)
"""

from __future__ import annotations

import json
import time
from http.client import HTTPConnection
from typing import Any

import pytest

from tools.obs.health_server import HealthServer, start_server


class FakeHealthProviders:
    """Fake health providers for testing."""
    
    def __init__(self, state_ready=True, risk_ready=True, exchange_ready=True):
        self._state_ready = state_ready
        self._risk_ready = risk_ready
        self._exchange_ready = exchange_ready
    
    def state_ready(self) -> bool:
        return self._state_ready
    
    def risk_ready(self) -> bool:
        return self._risk_ready
    
    def exchange_ready(self) -> bool:
        return self._exchange_ready


def test_health_endpoint_always_ok():
    """Test that /health always returns 200 OK."""
    providers = FakeHealthProviders(
        state_ready=False,
        risk_ready=False,
        exchange_ready=False,
    )
    
    server = start_server("127.0.0.1", 18080, providers)
    
    try:
        # Wait for server to start
        time.sleep(0.1)
        
        # Make request
        conn = HTTPConnection("127.0.0.1", 18080, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        
        assert resp.status == 200
        
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        
        assert data["status"] == "ok"
        
        conn.close()
    finally:
        server.stop()


def test_ready_endpoint_all_ready():
    """Test /ready returns 200 when all checks pass."""
    providers = FakeHealthProviders(
        state_ready=True,
        risk_ready=True,
        exchange_ready=True,
    )
    
    server = start_server("127.0.0.1", 18081, providers)
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18081, timeout=5)
        conn.request("GET", "/ready")
        resp = conn.getresponse()
        
        assert resp.status == 200
        
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        
        assert data["status"] == "ok"
        assert data["checks"]["state"] is True
        assert data["checks"]["risk"] is True
        assert data["checks"]["exchange"] is True
        
        conn.close()
    finally:
        server.stop()


def test_ready_endpoint_not_ready():
    """Test /ready returns 503 when any check fails."""
    providers = FakeHealthProviders(
        state_ready=True,
        risk_ready=False,  # Risk not ready
        exchange_ready=True,
    )
    
    server = start_server("127.0.0.1", 18082, providers)
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18082, timeout=5)
        conn.request("GET", "/ready")
        resp = conn.getresponse()
        
        assert resp.status == 503
        
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        
        assert data["status"] == "fail"
        assert data["checks"]["state"] is True
        assert data["checks"]["risk"] is False
        assert data["checks"]["exchange"] is True
        
        conn.close()
    finally:
        server.stop()


def test_metrics_endpoint():
    """Test /metrics returns Prometheus text format."""
    def fake_metrics_renderer():
        return "# HELP test_metric Test metric\n# TYPE test_metric counter\ntest_metric 42\n"
    
    server = start_server(
        "127.0.0.1",
        18083,
        metrics_renderer=fake_metrics_renderer,
    )
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18083, timeout=5)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/plain; version=0.0.4"
        
        body = resp.read().decode("utf-8")
        
        assert "test_metric" in body
        assert "# HELP test_metric" in body
        assert "test_metric 42" in body
        
        conn.close()
    finally:
        server.stop()


def test_metrics_endpoint_not_configured():
    """Test /metrics returns 501 when metrics_renderer is None."""
    server = start_server("127.0.0.1", 18084)
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18084, timeout=5)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        
        assert resp.status == 501
        
        body = resp.read().decode("utf-8")
        assert "not configured" in body.lower()
        
        conn.close()
    finally:
        server.stop()


def test_not_found_endpoint():
    """Test that unknown endpoints return 404."""
    server = start_server("127.0.0.1", 18085)
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18085, timeout=5)
        conn.request("GET", "/unknown")
        resp = conn.getresponse()
        
        assert resp.status == 404
        
        body = resp.read().decode("utf-8")
        assert "Not Found" in body
        
        conn.close()
    finally:
        server.stop()


def test_json_response_determinism():
    """Test that JSON responses have sorted keys."""
    providers = FakeHealthProviders()
    
    server = start_server("127.0.0.1", 18086, providers)
    
    try:
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18086, timeout=5)
        conn.request("GET", "/ready")
        resp = conn.getresponse()
        
        body = resp.read().decode("utf-8")
        
        # Parse and re-serialize to check key order
        data = json.loads(body)
        
        # Should be able to re-serialize with sorted keys and get same output
        expected = json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
        assert body == expected
        
        conn.close()
    finally:
        server.stop()


def test_server_lifecycle():
    """Test server start and stop."""
    server = HealthServer("127.0.0.1", 18087)
    
    # Start server
    server.start()
    time.sleep(0.1)
    
    # Verify it's running
    conn = HTTPConnection("127.0.0.1", 18087, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()
    
    # Stop server
    server.stop()
    time.sleep(0.1)
    
    # Verify it's stopped (connection should fail)
    with pytest.raises(Exception):
        conn = HTTPConnection("127.0.0.1", 18087, timeout=1)
        conn.request("GET", "/health")
        conn.getresponse()


def test_start_server_helper():
    """Test start_server helper function."""
    server = start_server("127.0.0.1", 18088)
    
    try:
        # Should be already started
        time.sleep(0.1)
        
        conn = HTTPConnection("127.0.0.1", 18088, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
    finally:
        server.stop()


def test_multiple_requests():
    """Test that server can handle multiple sequential requests."""
    server = start_server("127.0.0.1", 18089)
    
    try:
        time.sleep(0.1)
        
        for i in range(5):
            conn = HTTPConnection("127.0.0.1", 18089, timeout=5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()  # Drain response
            conn.close()
    finally:
        server.stop()

