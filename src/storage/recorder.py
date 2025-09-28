"""
Data recorder using SQLAlchemy Core 2.0 for persisting market data and system events.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import polars as pl
from sqlalchemy import (
    Column, DateTime, Integer, MetaData, Numeric, String, Text, create_engine
)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import Table as SQLTable

from src.common.config import Config
from src.common.models import Order, OrderBook, Trade
from src.common.utils import json_dumps, j

# Backward compatibility alias
DataRecorder = None

logger = logging.getLogger(__name__)


class Recorder:
    """Non-blocking data recorder with background writer task."""

    def __init__(self, config: Config):
        """Initialize recorder with configuration."""
        self.config = config
        self.backend = config.storage.backend
        
        # Buffers for parquet backend
        self.order_buffer: List[Dict[str, Any]] = []
        self.fill_buffer: List[Dict[str, Any]] = []
        self.quote_buffer: List[Dict[str, Any]] = []
        self.book_snapshot_buffer: List[Dict[str, Any]] = []
        self.custom_event_buffer: List[Dict[str, Any]] = []
        
        # SQLAlchemy components
        self.metadata = MetaData()
        self.tables: Dict[str, SQLTable] = {}
        self.async_engine = None
        self.sync_engine = None
        
        # Background writer task
        self._writer_task: Optional[asyncio.Task] = None
        self._queue: Optional[asyncio.Queue] = None
        self._stop_event = asyncio.Event()
        
        # Batching configuration
        self.buffer_size = getattr(config.storage, 'batch_size', 1000)
        self.flush_ms = getattr(config.storage, 'flush_ms', 200)
        self.compress = getattr(config.storage, 'compress', None)
        
        # Statistics
        self.records_written = 0
        self.stats = {
            'enqueued': 0,
            'flushes': 0,
            'flushed_events': 0,
            'last_flush_ms': 0
        }
        
        # Define table schemas
        self._define_tables()

    def _define_tables(self):
        """Define SQLAlchemy table schemas."""
        self.tables['orders'] = SQLTable(
            'orders',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('timestamp', DateTime, nullable=False, index=True),
            Column('side', String(10), nullable=False),
            Column('price', Numeric(20, 8), nullable=False),
            Column('qty', Numeric(20, 8), nullable=False),
            Column('status', String(20), nullable=False),
            Column('symbol', String(20), nullable=False, index=True),
            Column('order_id', String(100), nullable=False, unique=True),
            Column('client_order_id', String(100), nullable=True),
            Column('order_type', String(20), nullable=False),
            Column('time_in_force', String(10), nullable=False),
            Column('post_only', String(5), nullable=False),
            Column('reduce_only', String(5), nullable=False),
            Column('close_on_trigger', String(5), nullable=False),
            Column('filled_qty', Numeric(20, 8), nullable=True),
            Column('avg_price', Numeric(20, 8), nullable=True),
            Column('created_time', DateTime, nullable=False),
            Column('updated_time', DateTime, nullable=False)
        )
        
        self.tables['fills'] = SQLTable(
            'fills',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('timestamp', DateTime, nullable=False, index=True),
            Column('order_id', String(100), nullable=False, index=True),
            Column('trade_id', String(100), nullable=False, unique=True),
            Column('price', Numeric(20, 8), nullable=False),
            Column('qty', Numeric(20, 8), nullable=False),
            Column('fee', Numeric(20, 8), nullable=True),
            Column('fee_asset', String(10), nullable=True),
            Column('symbol', String(20), nullable=False, index=True),
            Column('side', String(10), nullable=False),
            Column('exec_time', DateTime, nullable=False)
        )
        
        self.tables['quotes'] = SQLTable(
            'quotes',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('timestamp', DateTime, nullable=False, index=True),
            Column('bid_px', Numeric(20, 8), nullable=True),
            Column('bid_qty', Numeric(20, 8), nullable=True),
            Column('ask_px', Numeric(20, 8), nullable=True),
            Column('ask_qty', Numeric(20, 8), nullable=True),
            Column('symbol', String(20), nullable=False, index=True),
            Column('mid_price', Numeric(20, 8), nullable=True),
            Column('spread_bps', Numeric(10, 4), nullable=True),
            Column('volatility', Numeric(10, 6), nullable=True),
            Column('imbalance', Numeric(10, 6), nullable=True)
        )
        
        self.tables['book_snapshots'] = SQLTable(
            'book_snapshots',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('timestamp', DateTime, nullable=False, index=True),
            Column('symbol', String(20), nullable=False, index=True),
            Column('sequence', Integer, nullable=False),
            Column('bids', Text, nullable=False),  # JSON string
            Column('asks', Text, nullable=False),  # JSON string
            Column('mid_price', Numeric(20, 8), nullable=True),
            Column('spread_bps', Numeric(10, 4), nullable=True)
        )

    async def _initialize_database(self):
        """Initialize database and create tables."""
        if self.backend in ["sqlite", "postgres"]:
            # Use new config structure
            if self.backend == "sqlite":
                db_url = f"sqlite:///{self.config.storage.sqlite_path}"
            else:  # postgres
                db_url = self.config.storage.pg_dsn
            
            # Create sync engine for table creation
            if self.backend == "sqlite":
                self.sync_engine = create_engine(db_url, connect_args={"check_same_thread": False})
            else:
                self.sync_engine = create_engine(db_url)
            
            # Create tables
            self.metadata.create_all(self.sync_engine)
            
            # Create async engine for operations
            if self.backend == "sqlite":
                # Use aiosqlite for async SQLite operations
                async_db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
                self.async_engine = create_async_engine(async_db_url)
            else:
                self.async_engine = create_async_engine(db_url)

    async def start(self):
        """Start the recorder and background writer task."""
        if self.backend in ["sqlite", "postgres"]:
            await self._initialize_database()
        
        # Initialize queue and start background writer
        self._queue = asyncio.Queue(maxsize=10000)
        self._stop_event.clear()
        self._writer_task = asyncio.create_task(self._background_writer())
        
        # Start periodic flush for parquet backend
        if self.backend == "parquet":
            asyncio.create_task(self._periodic_flush())
        
        logger.info(f"Recorder started with {self.backend} backend")

    async def stop(self):
        """Stop the recorder and wait for background writer to finish."""
        if self._writer_task:
            self._stop_event.set()
            
            # Wait for writer to drain queue with timeout
            try:
                await asyncio.wait_for(self._writer_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Background writer did not stop gracefully within timeout, cancelling")
                self._writer_task.cancel()
            
            self._writer_task = None
        
        # Dispose async engine
        if self.async_engine:
            await self.async_engine.dispose()
        
        # Final flush for parquet backend
        if self.backend == "parquet":
            await self._flush_all_buffers()
        
        logger.info("Recorder stopped")
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get current storage statistics."""
        return {
            'enqueued': self.stats['enqueued'],
            'flushes': self.stats['flushes'],
            'flushed_events': self.stats['flushed_events'],
            'last_flush_ms': self.stats['last_flush_ms'],
            'queue_size': len(self._queue) if self._queue else 0,
            'records_written': self.records_written
        }

    async def _background_writer(self):
        """Background task that drains the queue and persists events."""
        try:
            while not self._stop_event.is_set():
                try:
                    # Get item from queue with timeout
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    
                    # Debug log of the raw event
                    try:
                        logger.debug("recorder_event=%s", j(item))
                    except Exception:
                        pass
                    
                    # Process the item based on type
                    event_type = item.get('type')
                    data = item.get('data')
                    
                    if event_type == 'order':
                        await self._process_order(data)
                    elif event_type == 'fill':
                        await self._process_fill(data)
                    elif event_type == 'quote':
                        await self._process_quote(data)
                    elif event_type == 'book_snapshot':
                        await self._process_book_snapshot(data)
                    elif event_type == 'custom_event':
                        await self._process_custom_event(data)
                    else:
                        logger.warning("unknown_event_type=%s", event_type)
                    
                    self._queue.task_done()
                    
                except asyncio.TimeoutError:
                    # Timeout is expected, continue loop
                    continue
                except Exception as e:
                    logger.error("background_writer_process_error", exc_info=True)
                    if not self._queue.empty():
                        self._queue.task_done()
            
            # Drain remaining items in queue
            await self._drain_queue()
            
        except Exception:
            logger.error("background_writer_task_failed", exc_info=True)
            raise

    async def _drain_queue(self):
        """Drain remaining items in queue before stopping."""
        drained_count = 0
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                event_type = item.get('type')
                data = item.get('data')
                
                if event_type == 'order':
                    await self._process_order(data)
                elif event_type == 'fill':
                    await self._process_fill(data)
                elif event_type == 'quote':
                    await self._process_quote(data)
                elif event_type == 'book_snapshot':
                    await self._process_book_snapshot(data)
                elif event_type == 'custom_event':
                    await self._process_custom_event(data)
                
                drained_count += 1
                self._queue.task_done()
                
            except Exception as e:
                logger.error(f"Error draining queue item: {e}")
                if not self._queue.empty():
                    self._queue.task_done()
        
        if drained_count > 0:
            logger.info(f"Drained {drained_count} remaining events from queue")

    async def _process_order(self, order: Order):
        """Process order event."""
        if self.backend == "parquet":
            self.order_buffer.append({
                'timestamp': order.updated_time,
                'side': order.side.value,
                'price': float(order.price) if order.price else 0,
                'qty': float(order.qty),
                'status': order.status.value,
                'symbol': order.symbol,
                'order_id': order.order_id,
                'client_order_id': order.client_order_id,
                'order_type': order.order_type.value,
                'time_in_force': order.time_in_force.value,
                'post_only': str(order.post_only).lower(),
                'reduce_only': str(order.reduce_only).lower(),
                'close_on_trigger': str(order.close_on_trigger).lower(),
                'filled_qty': float(order.filled_qty) if order.filled_qty else None,
                'avg_price': float(order.avg_price) if order.avg_price else None,
                'created_time': order.created_time,
                'updated_time': order.updated_time
            })
            
            if len(self.order_buffer) >= self.buffer_size:
                await self._flush_order_buffer()
        else:
            await self._insert_order_db(order)

    async def _process_fill(self, fill: Trade):
        """Process fill event."""
        if self.backend == "parquet":
            self.fill_buffer.append({
                'timestamp': fill.exec_time,
                'order_id': fill.order_id,
                'trade_id': fill.trade_id,
                'price': float(fill.price),
                'qty': float(fill.qty),
                'fee': float(fill.fee) if fill.fee else None,
                'fee_asset': 'USDT',  # Default fee asset for USDT perpetuals
                'symbol': fill.symbol,
                'side': fill.side.value,
                'exec_time': fill.exec_time
            })
            
            if len(self.fill_buffer) >= self.buffer_size:
                await self._flush_fill_buffer()
        else:
            await self._insert_fill_db(fill)

    async def _process_quote(self, quote_data: Dict[str, Any]):
        """Process quote event."""
        if self.backend == "parquet":
            self.quote_buffer.append(quote_data)
            
            if len(self.quote_buffer) >= self.buffer_size:
                await self._flush_quote_buffer()
        else:
            await self._insert_quote_db(quote_data)

    async def _process_book_snapshot(self, snapshot: OrderBook):
        """Process book snapshot event."""
        if self.backend == "parquet":
            self.book_snapshot_buffer.append({
                'timestamp': snapshot.timestamp,
                'symbol': snapshot.symbol,
                'sequence': snapshot.sequence,
                'bids': json_dumps([{'price': float(p), 'qty': float(q)} for p, q in snapshot.bids]),
                'asks': json_dumps([{'price': float(p), 'qty': float(q)} for p, q in snapshot.asks]),
                'mid_price': float(snapshot.mid_price) if snapshot.mid_price else None,
                'spread_bps': float(snapshot.spread_bps) if snapshot.spread_bps else None
            })
            
            if len(self.book_snapshot_buffer) >= self.buffer_size:
                await self._flush_book_snapshot_buffer()
        else:
            await self._insert_book_snapshot_db(snapshot)

    async def _process_custom_event(self, event_data: Dict[str, Any]):
        """Process custom event."""
        if self.backend == "parquet":
            self.custom_event_buffer.append(event_data)
            
            if len(self.custom_event_buffer) >= self.buffer_size:
                await self._flush_custom_event_buffer()
        # Custom events are not stored in SQL tables by default

    # Public record methods - non-blocking, just queue the event
    async def record_order(self, order: Order) -> None:
        """Record an order (non-blocking)."""
        if self.backend == "parquet":
            # For parquet backend, add directly to buffer
            self.order_buffer.append(order)
            if len(self.order_buffer) >= self.buffer_size:
                await self._flush_order_buffer()
        elif self._queue and not self._queue.full():
            try:
                self._queue.put_nowait({'type': 'order', 'data': order})
            except asyncio.QueueFull:
                logger.warning("Recorder queue full, dropping order event")

    async def record_fill(self, fill: Trade) -> None:
        """Record a fill (non-blocking)."""
        if self.backend == "parquet":
            # For parquet backend, add directly to buffer
            self.fill_buffer.append(fill)
            if len(self.fill_buffer) >= self.buffer_size:
                await self._flush_fill_buffer()
        elif self._queue and not self._queue.full():
            try:
                self._queue.put_nowait({'type': 'fill', 'data': fill})
            except asyncio.QueueFull:
                logger.warning("Recorder queue full, dropping fill event")

    async def record_quote(self, quote_data: Dict[str, Any]) -> None:
        """Record a quote (non-blocking)."""
        if self._queue and not self._queue.full():
            try:
                self._queue.put_nowait({'type': 'quote', 'data': quote_data})
            except asyncio.QueueFull:
                logger.warning("Recorder queue full, dropping quote event")

    async def record_book_snapshot(self, snapshot: OrderBook) -> None:
        """Record a book snapshot (non-blocking)."""
        if self.backend == "parquet":
            # For parquet backend, add directly to buffer
            self.book_snapshot_buffer.append(snapshot)
            if len(self.book_snapshot_buffer) >= self.buffer_size:
                await self._flush_book_snapshot_buffer()
        elif self._queue and not self._queue.full():
            try:
                self._queue.put_nowait({'type': 'book_snapshot', 'data': snapshot})
            except asyncio.QueueFull:
                logger.warning("Recorder queue full, dropping book snapshot event")

    async def record_custom_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Record a custom event (non-blocking)."""
        if self._queue and not self._queue.full():
            try:
                event_data = {
                    'event_type': event_type,
                    'timestamp': datetime.now(timezone.utc),
                    **data
                }
                self._queue.put_nowait({'type': 'custom_event', 'data': event_data})
            except asyncio.QueueFull:
                logger.warning("Recorder queue full, dropping custom event")

    # Legacy methods for backward compatibility
    async def record_orderbook(self, orderbook: OrderBook) -> None:
        """Legacy method - record orderbook snapshot."""
        await self.record_book_snapshot(orderbook)

    async def record_trade(self, trade: Trade) -> None:
        """Legacy method - record trade/fill."""
        await self.record_fill(trade)

    async def record_risk_metrics(self, metrics: Dict[str, Any]) -> None:
        """Legacy method - record risk metrics as custom event."""
        await self.record_custom_event("risk_metrics", metrics)

    # Database insertion methods
    async def _insert_order_db(self, order: Order):
        """Insert order into database."""
        if not self.async_engine:
            return
        try:
            async with self.async_engine.begin() as conn:
                await conn.execute(
                    self.tables['orders'].insert().values(
                        timestamp=order.updated_time,
                        side=order.side.value,
                        price=float(order.price) if order.price else 0,
                        qty=float(order.qty),
                        status=order.status.value,
                        symbol=order.symbol,
                        order_id=order.order_id,
                        client_order_id=order.client_order_id,
                        order_type=order.order_type.value,
                        time_in_force=order.time_in_force.value,
                        post_only=str(order.post_only).lower(),
                        reduce_only=str(order.reduce_only).lower(),
                        close_on_trigger=str(order.close_on_trigger).lower(),
                        filled_qty=float(order.filled_qty) if order.filled_qty else None,
                        avg_price=float(order.avg_price) if order.avg_price else None,
                        created_time=order.created_time,
                        updated_time=order.updated_time
                    )
                )
                self.records_written += 1
        except Exception as e:
            logger.error(f"Error inserting order into database: {e}")

    async def _insert_fill_db(self, fill: Trade):
        """Insert fill into database."""
        if not self.async_engine:
            return
        try:
            async with self.async_engine.begin() as conn:
                await conn.execute(
                    self.tables['fills'].insert().values(
                        timestamp=fill.exec_time,
                        order_id=fill.order_id,
                        trade_id=fill.trade_id,
                        price=float(fill.price),
                        qty=float(fill.qty),
                        fee=float(fill.fee) if fill.fee else None,
                        fee_asset=fill.fee_asset,
                        symbol=fill.symbol,
                        side=fill.side.value,
                        exec_time=fill.exec_time
                    )
                )
                self.records_written += 1
        except Exception as e:
            logger.error(f"Error inserting fill into database: {e}")

    async def _insert_quote_db(self, quote_data: Dict[str, Any]):
        """Insert quote into database."""
        if not self.async_engine:
            return
        try:
            async with self.async_engine.begin() as conn:
                await conn.execute(
                    self.tables['quotes'].insert().values(
                        timestamp=quote_data.get('timestamp', datetime.now(timezone.utc)),
                        bid_px=quote_data.get('bid_px'),
                        bid_qty=quote_data.get('bid_qty'),
                        ask_px=quote_data.get('ask_px'),
                        ask_qty=quote_data.get('ask_qty'),
                        symbol=quote_data.get('symbol'),
                        mid_price=quote_data.get('mid_price'),
                        spread_bps=quote_data.get('spread_bps'),
                        volatility=quote_data.get('volatility'),
                        imbalance=quote_data.get('imbalance')
                    )
                )
                self.records_written += 1
        except Exception as e:
            logger.error(f"Error inserting quote into database: {e}")

    async def _insert_book_snapshot_db(self, snapshot: OrderBook):
        """Insert book snapshot into database."""
        if not self.async_engine:
            return
        try:
            async with self.async_engine.begin() as conn:
                await conn.execute(
                    self.tables['book_snapshots'].insert().values(
                        timestamp=snapshot.timestamp,
                        symbol=snapshot.symbol,
                        sequence=snapshot.sequence,
                        bids=json_dumps([{'price': float(p), 'qty': float(q)} for p, q in snapshot.bids]),
                        asks=json_dumps([{'price': float(p), 'qty': float(q)} for p, q in snapshot.asks]),
                        mid_price=float(snapshot.mid_price) if snapshot.mid_price else None,
                        spread_bps=float(snapshot.spread_bps) if snapshot.spread_bps else None
                    )
                )
                self.records_written += 1
        except Exception as e:
            logger.error(f"Error inserting book snapshot into database: {e}")

    # Parquet flushing methods (only for parquet backend)
    async def _periodic_flush(self):
        """Periodically flush all buffers."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.flush_ms / 1000)  # Flush every flush_ms milliseconds
                await self._flush_all_buffers()
            except Exception as e:
                logger.error("error_in_periodic_flush", exc_info=True)

    async def _flush_all_buffers(self):
        """Flush all buffers if they contain data."""
        if self.backend != "parquet":
            return
            
        if self.order_buffer:
            await self._flush_order_buffer()
        if self.fill_buffer:
            await self._flush_fill_buffer()
        if self.quote_buffer:
            await self._flush_quote_buffer()
        if self.book_snapshot_buffer:
            await self._flush_book_snapshot_buffer()
        if self.custom_event_buffer:
            await self._flush_custom_event_buffer()

    async def _flush_order_buffer(self):
        """Flush order buffer to parquet."""
        if not self.order_buffer:
            return
            
        try:
            df = pl.DataFrame(self.order_buffer)
            await self._write_parquet(df, "orders")
            self.stats['flushes'] += 1
            self.order_buffer.clear()
        except Exception:
            logger.error("error_flushing_order_buffer", exc_info=True)

    async def _flush_fill_buffer(self):
        """Flush fill buffer to parquet."""
        if not self.fill_buffer:
            return
            
        try:
            df = pl.DataFrame(self.fill_buffer)
            await self._write_parquet(df, "fills")
            self.stats['flushes'] += 1
            self.fill_buffer.clear()
        except Exception:
            logger.error("error_flushing_fill_buffer", exc_info=True)

    # Aliases for tests compatibility
    async def _flush_trade_buffer(self):
        return await self._flush_fill_buffer()

    async def _flush_quote_buffer(self):
        """Flush quote buffer to parquet."""
        if not self.quote_buffer:
            return
            
        try:
            df = pl.DataFrame(self.quote_buffer)
            await self._write_parquet(df, "quotes")
            self.stats['flushes'] += 1
            self.quote_buffer.clear()
        except Exception:
            logger.error("error_flushing_quote_buffer", exc_info=True)

    async def _flush_book_snapshot_buffer(self):
        """Flush book snapshot buffer to parquet."""
        if not self.book_snapshot_buffer:
            return
            
        try:
            df = pl.DataFrame(self.book_snapshot_buffer)
            await self._write_parquet(df, "book_snapshots")
            self.stats['flushes'] += 1
            self.book_snapshot_buffer.clear()
        except Exception:
            logger.error("error_flushing_book_snapshot_buffer", exc_info=True)

    async def _flush_orderbook_buffer(self):
        return await self._flush_book_snapshot_buffer()

    async def _flush_custom_event_buffer(self):
        """Flush custom event buffer to parquet."""
        if not self.custom_event_buffer:
            return
            
        try:
            # Normalize datetimes to UTC epoch ms and prefer key 'ts'
            normalized_events: List[Dict[str, Any]] = []
            for ev in self.custom_event_buffer:
                try:
                    if not isinstance(ev, dict):
                        continue
                    norm: Dict[str, Any] = {}
                    first_ms: Optional[int] = None
                    for k, v in ev.items():
                        if isinstance(v, datetime):
                            dt = v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
                            ms = int(dt.timestamp() * 1000)
                            norm[k] = ms
                            if first_ms is None:
                                first_ms = ms
                        else:
                            norm[k] = v
                    if "ts" not in norm and first_ms is not None:
                        norm["ts"] = first_ms
                    normalized_events.append(norm)
                except Exception:
                    logger.error("error_normalizing_custom_event", exc_info=True)
                    continue

            if not normalized_events:
                self.custom_event_buffer.clear()
                return

            df = pl.DataFrame(normalized_events, strict=False)
            await self._write_parquet(df, "custom_events")
            self.stats['flushes'] += 1
            self.custom_event_buffer.clear()
        except Exception:
            logger.error("error_flushing_custom_event_buffer", exc_info=True)

    async def _write_parquet(self, df: pl.DataFrame, table_name: str):
        """Write DataFrame to parquet file in <parquet_path>/<table>/<date>_*.parquet."""
        try:
            base_path = Path(self.config.storage.parquet_path)
            table_dir = base_path / table_name
            table_dir.mkdir(parents=True, exist_ok=True)
            
            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            filename = f"{date_str}_{table_name}.parquet"
            filepath = table_dir / filename
            
            # Append or write new
            if filepath.exists():
                # Read existing, concat, and overwrite for simplicity
                try:
                    existing = pl.read_parquet(filepath)
                    df = pl.concat([existing, df], how="vertical_relaxed")
                except Exception:
                    pass
            df.write_parquet(filepath)
            self.records_written += df.height
            logger.debug("parquet_written table=%s rows=%s path=%s", table_name, df.height, str(filepath))
        except Exception:
            logger.error("error_writing_parquet_file", exc_info=True)
    
    async def _write_ndjson(self, data: List[Dict], table_name: str):
        """Write data to NDJSON file with optional compression."""
        try:
            base_path = Path(self.config.storage.parquet_path)
            table_dir = base_path / table_name
            table_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            
            if self.compress == "zstd":
                try:
                    import zstandard as zstd
                    compressor = zstd.ZstdCompressor(level=3)
                    ndjson_data = b'\n'.join(orjson.dumps(record) for record in data)
                    compressed = compressor.compress(ndjson_data)
                    
                    filename = f"{timestamp}_{table_name}.ndjson.zst"
                    filepath = table_dir / filename
                    
                    with open(filepath, 'wb') as f:
                        f.write(compressed)
                    
                    logger.debug("ndjson_compressed_written table=%s rows=%s path=%s", table_name, len(data), str(filepath))
                except ImportError:
                    logger.warning("zstandard not available, falling back to plain NDJSON")
                    self.compress = None
            
            if self.compress != "zstd":
                # Plain NDJSON
                filename = f"{timestamp}_{table_name}.ndjson"
                filepath = table_dir / filename
                
                with open(filepath, 'wb') as f:
                    for record in data:
                        f.write(orjson.dumps(record))
                        f.write(b'\n')
                
                logger.debug("ndjson_written table=%s rows=%s path=%s", table_name, len(data), str(filepath))
            
            self.stats['flushed_events'] += len(data)
            self.stats['last_flush_ms'] = int(datetime.now(timezone.utc).timestamp() * 1000)
            
        except Exception:
            logger.error("error_writing_ndjson_file", exc_info=True)

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        return {
            'enqueued': self.stats['enqueued'],
            'flushes': self.stats['flushes'],
            'flushed_events': self.stats['flushed_events'],
            'last_flush_ms': self.stats['last_flush_ms'],
            'queue_size': len(self._queue) if self._queue else 0,
            'records_written': self.records_written,
            'backend': self.backend,
            'buffer_sizes': {
                'orders': len(self.order_buffer),
                'fills': len(self.fill_buffer),
                'quotes': len(self.quote_buffer),
                'book_snapshots': len(self.book_snapshot_buffer),
                'custom_events': len(self.custom_event_buffer)
            }
        }

    def get_data_summary(self) -> Dict[str, Any]:
        """Get data summary."""
        return {
            'backend': self.backend,
            'total_records': self.records_written,
            'active_buffers': sum([
                len(self.order_buffer),
                len(self.fill_buffer),
                len(self.quote_buffer),
                len(self.book_snapshot_buffer),
                len(self.custom_event_buffer)
            ])
        }

    def reset(self):
        """Reset recorder state."""
        self.records_written = 0
        self.order_buffer.clear()
        self.fill_buffer.clear()
        self.quote_buffer.clear()
        self.book_snapshot_buffer.clear()
        self.custom_event_buffer.clear()
        logger.info("recorder_reset")
