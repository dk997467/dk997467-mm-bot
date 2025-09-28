"""
Tests for research data recorder functionality.

Tests:
- File writing and rotation
- Data recording and buffering
- Compression and file management
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.storage.research_recorder import ResearchRecorder, ResearchRecord
from src.common.config import AppConfig
from src.common.models import OrderBook, PriceLevel, Order, Side, OrderType, TimeInForce, OrderStatus


class TestResearchRecorder:
    """Test research data recorder."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / "research"
        
        # Create mock config
        self.mock_config = AppConfig(
            storage=type('StorageConfig', (), {
                'compress': 'zstd',
                'batch_size': 100,
                'flush_ms': 100
            })(),
            trading=type('TradingConfig', (), {
                'maker_fee_bps': 1.0,
                'taker_fee_bps': 5.0
            })()
        )
        
        # Create recorder
        self.recorder = ResearchRecorder(self.mock_config, str(self.data_dir))
    
    def teardown_method(self):
        """Clean up test fixtures."""
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_recorder_initialization(self):
        """Test recorder initialization."""
        assert self.recorder.data_dir == self.data_dir
        assert self.recorder.compress == 'zstd'
        assert self.recorder.buffer_size == 100
        assert self.recorder.flush_ms == 100
        assert len(self.recorder.market_buffer) == 0
        assert len(self.recorder.event_buffer) == 0
    
    @pytest.mark.asyncio
    async def test_start_stop_recorder(self):
        """Test starting and stopping recorder."""
        # Start recorder
        await self.recorder.start()
        assert self.recorder._writer_task is not None
        assert not self.recorder._stop_event.is_set()
        
        # Stop recorder
        await self.recorder.stop()
        # Note: _writer_task may not be None immediately after stop
        # as it takes time for the task to complete
        assert self.recorder._stop_event.is_set()
    
    def test_record_market_snapshot(self):
        """Test recording market snapshot."""
        # Create mock orderbook
        orderbook = OrderBook(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[
                PriceLevel(price=Decimal("50000"), size=Decimal("1.0"), sequence=1),
                PriceLevel(price=Decimal("49999"), size=Decimal("0.5"), sequence=2)
            ],
            asks=[
                PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
                PriceLevel(price=Decimal("50002"), size=Decimal("0.5"), sequence=2)
            ]
        )
        
        # Mock our quotes
        our_quotes = {
            'bids': [
                {'price': 49998, 'size': 0.1},
                {'price': 49997, 'size': 0.2}
            ],
            'asks': [
                {'price': 50003, 'size': 0.1},
                {'price': 50004, 'size': 0.2}
            ]
        }
        
        vola_1m = 0.02
        
        # Record snapshot
        self.recorder.record_market_snapshot("BTCUSDT", orderbook, our_quotes, vola_1m)
        
        # Check buffer
        assert len(self.recorder.market_buffer) == 1
        record = self.recorder.market_buffer[0]
        
        assert record.symbol == "BTCUSDT"
        assert record.mid == 50000.5  # (50000 + 50001) / 2
        assert record.best_bid == 50000.0
        assert record.best_ask == 50001.0
        # Spread calculation: (50001 - 50000) / 50000.5 * 10000 = 0.2 bps
        assert abs(record.spread - 0.2) < 0.01
        assert record.vola_1m == 0.02
        assert record.ob_imbalance == 0.0  # (1.5 - 1.5) / 3.0
        
        # Check our quotes
        assert record.our_bid_1 == 49998.0
        assert record.our_bid_1_size == 0.1
        assert record.our_bid_2 == 49997.0
        assert record.our_bid_2_size == 0.2
        assert record.our_ask_1 == 50003.0
        assert record.our_ask_1_size == 0.1
        assert record.our_ask_2 == 50004.0
        assert record.our_ask_2_size == 0.2
    
    def test_record_order_event(self):
        """Test recording order event."""
        # Create mock order
        order = Order(
            order_id="test_order_123",
            client_order_id="client_123",
            symbol="BTCUSDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=Decimal("0.001"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.GTC,
            post_only=True,
            status=OrderStatus.NEW
        )
        
        # Record order event
        self.recorder.record_order_event(
            event_type="create",
            order=order,
            fill_price=50000.0,
            fill_qty=0.001,
            fees=0.05,
            inventory=0.001,
            realized_pnl=0.0,
            queue_position=2.0,
            ahead_volume=1.5,
            time_in_book_ms=1000
        )
        
        # Check buffer
        assert len(self.recorder.event_buffer) == 1
        record = self.recorder.event_buffer[0]
        
        assert record.symbol == "BTCUSDT"
        assert record.event_type == "create"
        assert record.order_id == "test_order_123"
        assert record.side == "Buy"
        assert record.price == 50000.0
        assert record.qty == 0.001
        assert record.fill_price == 50000.0
        assert record.fill_qty == 0.001
        assert record.fees == 0.05
        assert record.inventory == 0.001
        assert record.realized_pnl == 0.0
        assert record.queue_position == 2.0
        assert record.ahead_volume == 1.5
        assert record.time_in_book_ms == 1000
    
    @pytest.mark.asyncio
    async def test_file_rotation(self):
        """Test file rotation functionality."""
        # Start recorder
        await self.recorder.start()
        
        # Manually trigger file rotation
        old_hour = self.recorder.current_hour
        new_hour = old_hour + timedelta(hours=1)
        
        await self.recorder._rotate_file(new_hour)
        
        # Check that new file was created
        assert self.recorder.current_file is not None
        assert self.recorder.current_hour == new_hour
        assert self.recorder.files_created == 1
        
        # Check file naming
        expected_filename = f"research_{new_hour.strftime('%Y%m%d_%H')}.parquet"
        assert self.recorder.current_file.name == expected_filename
        
        # Stop recorder
        await self.recorder.stop()
    
    @pytest.mark.asyncio
    async def test_buffer_flushing(self):
        """Test buffer flushing functionality."""
        # Start recorder
        await self.recorder.start()
        
        # Set up a current file for flushing
        from datetime import datetime, timezone
        current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        await self.recorder._rotate_file(current_hour)
        
        # Add some data to buffers
        self.recorder.market_buffer.append(ResearchRecord(
            ts=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            mid=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            spread=4.0,
            vola_1m=0.02,
            ob_imbalance=0.0
        ))
        
        self.recorder.event_buffer.append(ResearchRecord(
            ts=datetime.now(timezone.utc),
            symbol="BTCUSDT",
            mid=50000.0,
            best_bid=49999.0,
            best_ask=50001.0,
            spread=4.0,
            vola_1m=0.02,
            ob_imbalance=0.0,
            event_type="create",
            order_id="test_order",
            side="Buy",
            price=50000.0,
            qty=0.001
        ))
        
        # Manually trigger flush
        await self.recorder._flush_buffers()
        
        # Check that buffers were cleared
        assert len(self.recorder.market_buffer) == 0
        assert len(self.recorder.event_buffer) == 0
        
        # Stop recorder
        await self.recorder.stop()
    
    def test_get_stats(self):
        """Test getting recorder statistics."""
        stats = self.recorder.get_stats()
        
        assert 'records_written' in stats
        assert 'files_created' in stats
        assert 'current_file' in stats
        assert 'market_buffer_size' in stats
        assert 'event_buffer_size' in stats
        assert 'compression' in stats
        
        assert stats['records_written'] == 0
        assert stats['files_created'] == 0
        assert stats['compression'] == 'zstd'
    
    @pytest.mark.asyncio
    async def test_compression(self):
        """Test file compression functionality."""
        # Create a test file
        test_file = self.data_dir / "test.parquet"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("test content")
        
        # Test gzip compression
        self.recorder.compress = 'gzip'
        await self.recorder._compress_file(test_file)
        
        compressed_file = test_file.with_suffix('.parquet.gz')
        assert compressed_file.exists()
        assert not test_file.exists()
        
        # Test zstd compression
        test_file2 = self.data_dir / "test2.parquet"
        test_file2.write_text("test content 2")
        
        self.recorder.compress = 'zstd'
        await self.recorder._compress_file(test_file2)
        
        compressed_file2 = test_file2.with_suffix('.parquet.zst')
        assert compressed_file2.exists()
        assert not test_file2.exists()
    
    def test_empty_orderbook_handling(self):
        """Test handling of empty orderbook."""
        # Create empty orderbook
        empty_orderbook = OrderBook(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[],
            asks=[]
        )
        
        our_quotes = {'bids': [], 'asks': []}
        vola_1m = 0.02
        
        # Record snapshot (should not add to buffer)
        self.recorder.record_market_snapshot("BTCUSDT", empty_orderbook, our_quotes, vola_1m)
        
        # Check that nothing was added to buffer
        assert len(self.recorder.market_buffer) == 0
    
    def test_market_data_calculation(self):
        """Test market data calculations."""
        # Create orderbook with specific values
        orderbook = OrderBook(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[
                PriceLevel(price=Decimal("40000"), size=Decimal("2.0"), sequence=1),
                PriceLevel(price=Decimal("39999"), size=Decimal("1.0"), sequence=2)
            ],
            asks=[
                PriceLevel(price=Decimal("40001"), size=Decimal("1.0"), sequence=1),
                PriceLevel(price=Decimal("40002"), size=Decimal("2.0"), sequence=2)
            ]
        )
        
        our_quotes = {'bids': [], 'asks': []}
        vola_1m = 0.015
        
        # Record snapshot
        self.recorder.record_market_snapshot("BTCUSDT", orderbook, our_quotes, vola_1m)
        
        # Check calculations
        record = self.recorder.market_buffer[0]
        
        # Mid price: (40000 + 40001) / 2 = 40000.5
        assert record.mid == 40000.5
        
        # Spread: (40001 - 40000) / 40000.5 * 10000 = 0.25 bps
        assert abs(record.spread - 0.25) < 0.1
        
        # Imbalance: (3.0 - 3.0) / 6.0 = 0.0
        assert record.ob_imbalance == 0.0
        
        # Volatility
        assert record.vola_1m == 0.015
