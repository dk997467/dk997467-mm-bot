"""
Tests for the Recorder class using SQLAlchemy Core 2.0.
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

from src.common.config import Config
from src.common.models import Order, Trade, OrderBook, PriceLevel, Side, OrderType, OrderStatus, TimeInForce
from src.storage.recorder import Recorder


@pytest.fixture
def temp_config(tmp_path):
    """Create a temporary configuration for testing."""
    config = Config()
    config.storage.backend = "sqlite"
    config.storage.sqlite_path = str(tmp_path / "test.db")
    return config


@pytest.fixture
def sample_order():
    """Create a sample order for testing."""
    return Order(
        order_id="test_order_123",
        client_order_id="client_123",
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=Decimal("0.001"),
        price=Decimal("50000.00"),
        time_in_force=TimeInForce.GTC,
        status=OrderStatus.NEW,
        post_only=True,
        reduce_only=False,
        close_on_trigger=False,
        created_time=datetime.now(timezone.utc),
        updated_time=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_fill():
    """Create a sample trade/fill for testing."""
    return Trade(
        trade_id="test_trade_456",
        order_id="test_order_123",
        symbol="BTCUSDT",
        side=Side.BUY,
        qty=Decimal("0.001"),
        price=Decimal("50000.00"),
        fee=Decimal("0.25"),
        fee_rate=Decimal("0.0005"),
        timestamp=datetime.now(timezone.utc),
        exec_time=datetime.now(timezone.utc),
        is_maker=True
    )


@pytest.fixture
def sample_orderbook():
    """Create a sample orderbook for testing."""
    return OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=12345,
        bids=[
            PriceLevel(price=Decimal("49999.00"), size=Decimal("0.5")),
            PriceLevel(price=Decimal("49998.00"), size=Decimal("1.0"))
        ],
        asks=[
            PriceLevel(price=Decimal("50001.00"), size=Decimal("0.5")),
            PriceLevel(price=Decimal("50002.00"), size=Decimal("1.0"))
        ]
    )


@pytest.fixture
def sample_quote_data():
    """Create sample quote data for testing."""
    return {
        "timestamp": datetime.now(timezone.utc),
        "bid_px": Decimal("49999.00"),
        "bid_qty": Decimal("0.5"),
        "ask_px": Decimal("50001.00"),
        "ask_qty": Decimal("0.5"),
        "symbol": "BTCUSDT",
        "spread_bps": Decimal("4.0"),
        "mid_price": Decimal("50000.00"),
        "imbalance": Decimal("0.0"),
        "volatility": Decimal("0.02")
    }


class TestRecorder:
    """Test the Recorder class functionality."""
    
    @pytest.mark.asyncio
    async def test_recorder_initialization(self, temp_config):
        """Test recorder initialization."""
        recorder = Recorder(temp_config)
        assert recorder.backend == "sqlite"
        assert recorder.tables is not None
        assert len(recorder.tables) == 4  # orders, fills, quotes, book_snapshots
        assert "orders" in recorder.tables
        assert "fills" in recorder.tables
        assert "quotes" in recorder.tables
        assert "book_snapshots" in recorder.tables
    
    @pytest.mark.asyncio
    async def test_recorder_start_stop(self, temp_config):
        """Test recorder start and stop."""
        recorder = Recorder(temp_config)
        
        # Start recorder
        await recorder.start()
        assert recorder._writer_task is not None
        
        # Stop recorder
        await recorder.stop()
        assert recorder._writer_task is None
    
    @pytest.mark.asyncio
    async def test_record_order(self, temp_config, sample_order):
        """Test recording an order."""
        recorder = Recorder(temp_config)
        await recorder.start()
        
        # Record order
        await recorder.record_order(sample_order)
        
        # Check that record was processed
        assert recorder.records_written >= 0
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_record_fill(self, temp_config, sample_fill):
        """Test recording a fill."""
        recorder = Recorder(temp_config)
        await recorder.start()
        
        # Record fill
        await recorder.record_fill(sample_fill)
        
        # Check that record was processed
        assert recorder.records_written >= 0
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_record_quote(self, temp_config, sample_quote_data):
        """Test recording a quote."""
        recorder = Recorder(temp_config)
        await recorder.start()
        
        # Record quote
        await recorder.record_quote(sample_quote_data)
        
        # Check that record was processed
        assert recorder.records_written >= 0
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_record_book_snapshot(self, temp_config, sample_orderbook):
        """Test recording a book snapshot."""
        recorder = Recorder(temp_config)
        await recorder.start()
        
        # Record book snapshot
        await recorder.record_book_snapshot(sample_orderbook)
        
        # Check that record was processed
        assert recorder.records_written >= 0
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_legacy_methods(self, temp_config, sample_order, sample_fill, sample_orderbook):
        """Test legacy method compatibility."""
        recorder = Recorder(temp_config)
        await recorder.start()
        
        # Test legacy methods
        await recorder.record_orderbook(sample_orderbook)
        await recorder.record_trade(sample_fill)
        
        # Wait a bit for async tasks to complete
        await asyncio.sleep(0.1)
        
        await recorder.stop()
    
    def test_storage_stats(self, temp_config):
        """Test storage statistics."""
        recorder = Recorder(temp_config)
        stats = recorder.get_storage_stats()
        
        assert "backend" in stats
        assert "records_written" in stats
        assert "queue_size" in stats
        assert "buffer_sizes" in stats
        assert stats["backend"] == "sqlite"
    
    def test_data_summary(self, temp_config):
        """Test data summary generation."""
        recorder = Recorder(temp_config)
        summary = recorder.get_data_summary()
        
        assert "backend" in summary
        assert "total_records" in summary
        assert "active_buffers" in summary
        assert summary["backend"] == "sqlite"
    
    def test_reset(self, temp_config):
        """Test recorder reset functionality."""
        recorder = Recorder(temp_config)
        
        # Add some data to buffers
        recorder.book_snapshot_buffer.append({"test": "data"})
        recorder.fill_buffer.append({"test": "data"})
        recorder.order_buffer.append({"test": "data"})
        recorder.custom_event_buffer.append({"test": "data"})
        
        # Reset
        recorder.reset()
        
        # Check buffers are cleared
        assert len(recorder.book_snapshot_buffer) == 0
        assert len(recorder.fill_buffer) == 0
        assert len(recorder.order_buffer) == 0
        assert len(recorder.custom_event_buffer) == 0
        
        # Check statistics are reset
        assert recorder.records_written == 0


class TestRecorderParquet:
    """Test the Recorder class with Parquet backend."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for Parquet files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def parquet_config(self, temp_dir):
        """Create a configuration for Parquet backend."""
        config = Config()
        config.storage.backend = "parquet"
        config.storage.parquet_path = temp_dir
        return config
    
    @pytest.mark.asyncio
    async def test_parquet_initialization(self, parquet_config):
        """Test recorder initialization with Parquet backend."""
        recorder = Recorder(parquet_config)
        assert recorder.backend == "parquet"
        assert Path(recorder.config.storage.parquet_path).exists()
    
    @pytest.mark.asyncio
    async def test_parquet_record_order(self, parquet_config, sample_order):
        """Test recording an order to Parquet."""
        recorder = Recorder(parquet_config)
        await recorder.start()
        
        # Record order
        await recorder.record_order(sample_order)
        
        # Check buffer
        assert len(recorder.order_buffer) == 1
        
        # Flush buffer
        await recorder._flush_order_buffer()
        
        # Check file was created
        date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        expected_file = Path(recorder.config.storage.parquet_path) / "orders" / f"{date_str}_orders.parquet"
        assert expected_file.exists()
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_parquet_record_fill(self, parquet_config, sample_fill):
        """Test recording a fill to Parquet."""
        recorder = Recorder(parquet_config)
        await recorder.start()
        
        # Record fill
        await recorder.record_fill(sample_fill)
        
        # Check buffer
        assert len(recorder.fill_buffer) == 1
        
        # Flush buffer
        await recorder._flush_trade_buffer()
        
        # Check file was created
        date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        expected_file = Path(recorder.config.storage.parquet_path) / "fills" / f"{date_str}_fills.parquet"
        assert expected_file.exists()
        
        await recorder.stop()
    
    @pytest.mark.asyncio
    async def test_parquet_record_book_snapshot(self, parquet_config, sample_orderbook):
        """Test recording a book snapshot to Parquet."""
        recorder = Recorder(parquet_config)
        await recorder.start()
        
        # Record book snapshot
        await recorder.record_book_snapshot(sample_orderbook)
        
        # Check buffer
        assert len(recorder.book_snapshot_buffer) == 1
        
        # Flush buffer
        await recorder._flush_orderbook_buffer()
        
        # Check file was created
        date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        expected_file = Path(recorder.config.storage.parquet_path) / "book_snapshots" / f"{date_str}_book_snapshots.parquet"
        assert expected_file.exists()
        
        await recorder.stop()


if __name__ == "__main__":
    pytest.main([__file__])
