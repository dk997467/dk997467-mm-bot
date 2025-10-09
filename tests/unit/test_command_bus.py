"""
Unit tests для CommandBus - коалесинг и idempotency.
"""
import pytest
from src.execution.command_bus import CommandBus, Command, CmdType


def test_command_bus_coalesce_cancel():
    """
    Test: N cancel → 1 batch-cancel.
    
    Acceptance:
    - В одном тике ≤1 batch-cancel на символ
    """
    bus = CommandBus(feature_enabled=True)
    
    # Enqueue 5 cancel commands for same symbol
    for i in range(5):
        bus.enqueue(Command(CmdType.CANCEL, "BTCUSDT", {"order_id": f"order_{i}"}))
    
    coalesced = bus.get_coalesced_ops()
    
    # Should have 1 batch-cancel command for BTCUSDT
    assert "BTCUSDT" in coalesced
    assert len(coalesced["BTCUSDT"]) == 1
    
    batch_cancel = coalesced["BTCUSDT"][0]
    assert batch_cancel.cmd_type == CmdType.CANCEL
    assert batch_cancel.params["batch"] is True
    assert len(batch_cancel.params["order_ids"]) == 5


def test_command_bus_coalesce_place():
    """
    Test: M place → ≤2 batch-place вызова (если M > 20).
    
    Acceptance:
    - До 20 ордеров = 1 batch-place
    - 21-40 ордеров = 2 batch-place
    """
    bus = CommandBus(feature_enabled=True)
    
    # Enqueue 25 place commands (should split into 2 batches: 20 + 5)
    for i in range(25):
        bus.enqueue(Command(CmdType.PLACE, "BTCUSDT", {"side": "Buy", "qty": 1.0, "price": 50000 + i}))
    
    coalesced = bus.get_coalesced_ops()
    
    # Should have 2 batch-place commands (20 + 5)
    assert "BTCUSDT" in coalesced
    assert len(coalesced["BTCUSDT"]) == 2
    
    batch1 = coalesced["BTCUSDT"][0]
    batch2 = coalesced["BTCUSDT"][1]
    
    assert batch1.cmd_type == CmdType.PLACE
    assert batch2.cmd_type == CmdType.PLACE
    assert len(batch1.params["orders"]) == 20
    assert len(batch2.params["orders"]) == 5


def test_command_bus_legacy_mode():
    """
    Test: legacy mode (feature_enabled=false) не коалесит.
    
    Acceptance:
    - Все команды возвращаются как есть (без batching)
    """
    bus = CommandBus(feature_enabled=False)
    
    # Enqueue 5 cancel commands
    for i in range(5):
        bus.enqueue(Command(CmdType.CANCEL, "BTCUSDT", {"order_id": f"order_{i}"}))
    
    coalesced = bus.get_coalesced_ops()
    
    # In legacy mode, should return all commands individually
    assert "BTCUSDT" in coalesced
    assert len(coalesced["BTCUSDT"]) == 5  # No coalescing


def test_command_bus_idempotency():
    """
    Test: повторный flush не дублирует команды.
    
    Acceptance:
    - После clear() буфер пуст
    - Повторный get_coalesced_ops() возвращает пустой dict
    """
    bus = CommandBus(feature_enabled=True)
    
    # Enqueue commands
    bus.enqueue(Command(CmdType.CANCEL, "BTCUSDT", {"order_id": "order_1"}))
    bus.enqueue(Command(CmdType.PLACE, "ETHUSDT", {"side": "Buy", "qty": 1.0, "price": 3000}))
    
    # Get coalesced (flush)
    coalesced1 = bus.get_coalesced_ops()
    assert len(coalesced1) == 2  # BTCUSDT, ETHUSDT
    
    # Clear buffer
    bus.clear()
    
    # Get coalesced again (should be empty)
    coalesced2 = bus.get_coalesced_ops()
    assert len(coalesced2) == 0, "Buffer not cleared after flush"


def test_command_bus_stats():
    """
    Test: статистика коалесинга.
    
    Acceptance:
    - stats содержит total_commands, coalesce_stats
    """
    bus = CommandBus(feature_enabled=True)
    
    # Enqueue commands
    for i in range(10):
        bus.enqueue(Command(CmdType.CANCEL, "BTCUSDT", {"order_id": f"order_{i}"}))
    for i in range(5):
        bus.enqueue(Command(CmdType.PLACE, "ETHUSDT", {"side": "Buy", "qty": 1.0, "price": 3000}))
    
    # Trigger coalescing
    bus.get_coalesced_ops()
    
    stats = bus.get_stats()
    
    assert stats["total_commands"] == 15
    assert "coalesce_stats" in stats
    assert stats["coalesce_stats"]["cancel"] == 10
    assert stats["coalesce_stats"]["place"] == 5


def test_command_bus_multi_symbol():
    """
    Test: коалесинг работает для нескольких символов.
    
    Acceptance:
    - Каждый символ получает свой batch-cancel/place
    """
    bus = CommandBus(feature_enabled=True)
    
    # Enqueue for multiple symbols
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        for i in range(3):
            bus.enqueue(Command(CmdType.CANCEL, symbol, {"order_id": f"{symbol}_order_{i}"}))
    
    coalesced = bus.get_coalesced_ops()
    
    assert len(coalesced) == 3  # 3 symbols
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        assert symbol in coalesced
        assert len(coalesced[symbol]) == 1  # 1 batch-cancel per symbol
        assert coalesced[symbol][0].params["batch"] is True

