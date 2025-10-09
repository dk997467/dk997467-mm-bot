"""
Command Bus для коалесинга операций в рамках одного тика.

Цель: сшивать N cancel → 1 batch-cancel; M place → ≤2 вызова.
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class CmdType(Enum):
    """Тип команды."""
    PLACE = "place"
    CANCEL = "cancel"
    AMEND = "amend"


@dataclass
class Command:
    """Атомарная команда для биржи."""
    cmd_type: CmdType
    symbol: str
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class BatchResult:
    """Результат батч-операции."""
    success_count: int = 0
    failed_count: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0


class CommandBus:
    """
    Командная шина для коалесинга операций.
    
    Собирает команды в буфер и сшивает их в batch-операции при flush().
    """
    
    def __init__(self, feature_enabled: bool = True):
        """
        Инициализация.
        
        Args:
            feature_enabled: Если False, работает в legacy-режиме (без батчинга).
        """
        self.feature_enabled = feature_enabled
        self.buffer: Dict[str, List[Command]] = defaultdict(list)  # symbol -> [commands]
        self.coalesce_stats: Dict[str, int] = defaultdict(int)  # op -> count
        
        # Метрики (для экспорта)
        self.total_commands = 0
        self.total_batches = 0
        self.total_latency_ms = 0.0
    
    def enqueue(self, cmd: Command) -> None:
        """
        Добавить команду в буфер.
        
        Args:
            cmd: Команда для постановки в очередь.
        """
        self.buffer[cmd.symbol].append(cmd)
        self.total_commands += 1
    
    def get_coalesced_ops(self) -> Dict[str, List[Command]]:
        """
        Получить сшитые операции по символам.
        
        Returns:
            {symbol: [команды для batch-обработки]}
        """
        if not self.feature_enabled:
            # Legacy: возвращаем все команды как есть
            return dict(self.buffer)
        
        # Группируем по типу операции для коалесинга
        result: Dict[str, List[Command]] = {}
        
        for symbol, commands in self.buffer.items():
            # Разделяем по типу
            by_type: Dict[CmdType, List[Command]] = defaultdict(list)
            for cmd in commands:
                by_type[cmd.cmd_type].append(cmd)
            
            # Коалесинг cancel
            if by_type[CmdType.CANCEL]:
                # Все cancel для символа сшиваем в одну batch-cancel команду
                batch_cancel = Command(
                    cmd_type=CmdType.CANCEL,
                    symbol=symbol,
                    params={
                        "order_ids": [c.params.get("order_id") for c in by_type[CmdType.CANCEL] if c.params.get("order_id")],
                        "client_order_ids": [c.params.get("client_order_id") for c in by_type[CmdType.CANCEL] if c.params.get("client_order_id")],
                        "batch": True
                    }
                )
                if not result.get(symbol):
                    result[symbol] = []
                result[symbol].append(batch_cancel)
                self.coalesce_stats["cancel"] += len(by_type[CmdType.CANCEL])
            
            # Коалесинг place (до 20 ордеров в одном batch-запросе)
            if by_type[CmdType.PLACE]:
                max_batch_size = 20
                place_cmds = by_type[CmdType.PLACE]
                
                for i in range(0, len(place_cmds), max_batch_size):
                    batch_chunk = place_cmds[i:i+max_batch_size]
                    batch_place = Command(
                        cmd_type=CmdType.PLACE,
                        symbol=symbol,
                        params={
                            "orders": [c.params for c in batch_chunk],
                            "batch": True
                        }
                    )
                    if not result.get(symbol):
                        result[symbol] = []
                    result[symbol].append(batch_place)
                    self.coalesce_stats["place"] += len(batch_chunk)
            
            # Amend не коалесится (редкая операция)
            if by_type[CmdType.AMEND]:
                if not result.get(symbol):
                    result[symbol] = []
                result[symbol].extend(by_type[CmdType.AMEND])
        
        return result
    
    def clear(self) -> None:
        """Очистить буфер после flush."""
        self.buffer.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику коалесинга."""
        return {
            "total_commands": self.total_commands,
            "total_batches": self.total_batches,
            "coalesce_stats": dict(self.coalesce_stats),
            "avg_latency_ms": self.total_latency_ms / max(1, self.total_batches)
        }

