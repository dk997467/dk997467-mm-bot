import os, sys, io, builtins, asyncio
from pathlib import Path
import pytest

import socket as _socket

# ============================================================================
# CRITICAL FIX #1: Establish project root for fixture/golden file resolution
# ============================================================================
# Many tests use `Path(__file__).resolve().parents[1]` to find project root,
# then access fixtures via `root / "fixtures"` or `root / "golden"`.
# However, fixtures are actually in `tests/fixtures/` and `tests/golden/`.
# This creates symlinks in project root to resolve paths correctly.
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parent
FIXTURES_TARGET = PROJECT_ROOT / "tests" / "fixtures"
GOLDEN_TARGET = PROJECT_ROOT / "tests" / "golden"
FIXTURES_LINK = PROJECT_ROOT / "fixtures"
GOLDEN_LINK = PROJECT_ROOT / "golden"

def _ensure_fixture_links():
    """Ensure fixtures/ and golden/ symlinks exist in project root."""
    for link, target in [(FIXTURES_LINK, FIXTURES_TARGET), (GOLDEN_LINK, GOLDEN_TARGET)]:
        if not link.exists():
            try:
                # Try creating symlink (works on Linux/Mac, admin on Windows)
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                # Fallback: Create junction on Windows (no admin needed)
                import subprocess
                try:
                    subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                        check=True,
                        capture_output=True
                    )
                except subprocess.CalledProcessError:
                    # Last fallback: Just ensure target exists
                    pass

# Create links at module import time (before any tests run)
_ensure_fixture_links()

# ============================================================================
# CRITICAL FIX #2: Prevent Prometheus Registry Memory Leak
# ============================================================================
# Problem: Each test creates a new Metrics() object via mk_ctx fixture.
# Metrics.__init__() registers 100+ collectors in the global REGISTRY.
# Without cleanup, REGISTRY accumulates collectors across all tests,
# causing OOM (exit 143) on GitHub Actions runners (7GB RAM limit).
#
# Solution: Auto-clear REGISTRY before each test to prevent accumulation.
# ============================================================================

@pytest.fixture(autouse=True)
def _clear_prometheus_registry():
    """Clear Prometheus registry before each test to prevent memory leaks."""
    try:
        from prometheus_client import REGISTRY
        # Unregister all collectors to prevent accumulation
        for collector in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass
        # Clear internal dictionaries for clean slate
        REGISTRY._collector_to_names.clear()
        REGISTRY._names_to_collectors.clear()
    except ImportError:
        # prometheus_client not installed (shouldn't happen, but safe fallback)
        pass
    yield
    # Optional: cleanup after test too (belt-and-suspenders approach)
    try:
        from prometheus_client import REGISTRY
        for collector in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass
    except Exception:
        pass

if not isinstance(sys.stdout, io.TextIOBase):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="ascii", newline="\n")  # type: ignore
if not isinstance(sys.stderr, io.TextIOBase):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="ascii", newline="\n")  # type: ignore

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("TZ", "UTC")
    try:
        import time as _t
        _t.tzset()
    except Exception:
        pass

@pytest.fixture(autouse=True)
def _deny_network_calls(monkeypatch):
    def _deny_connect(*args, **kwargs):
        raise RuntimeError("Network disabled in tests")
    def _deny_create_connection(*args, **kwargs):
        raise RuntimeError("Network disabled in tests")
    try:
        monkeypatch.setattr(_socket.socket, "connect", _deny_connect, raising=True)
    except Exception:
        pass
    try:
        monkeypatch.setattr(_socket, "create_connection", _deny_create_connection, raising=True)
    except Exception:
        pass
    yield

@pytest.fixture(autouse=True)
def _force_ascii_newline(monkeypatch):
    def _open_patch(file, mode="r", *a, **kw):
        if "b" not in mode:
            kw.setdefault("encoding", "ascii")
            kw.setdefault("newline", "\n")
        return builtins.open_orig(file, mode, *a, **kw)  # type: ignore
    if not hasattr(builtins, "open_orig"):
        builtins.open_orig = builtins.open  # type: ignore
    monkeypatch.setattr(builtins, "open", _open_patch)  # type: ignore
    yield
    monkeypatch.setattr(builtins, "open", builtins.open_orig)  # type: ignore

@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    test_function = pyfuncitem.obj
    if asyncio.iscoroutinefunction(test_function):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(test_function(**pyfuncitem.funcargs))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)
        return True
    return None


def pytest_collection_modifyitems(config, items):
    # Если установлен CI_QUARANTINE=1 — пропускаем тесты, помеченные @pytest.mark.quarantine
    if os.environ.get("CI_QUARANTINE") == "1":
        skip_q = pytest.mark.skip(reason="quarantined in CI")
        for it in items:
            if it.get_closest_marker("quarantine"):
                it.add_marker(skip_q)


