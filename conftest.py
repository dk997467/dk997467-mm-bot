import os, sys, io, builtins, asyncio
import pytest

import socket as _socket

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


