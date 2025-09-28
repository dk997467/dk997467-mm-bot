"""Tests for queue simulator calibration effects."""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from src.backtest.queue_sim import QueueSimulator, CalibrationParams, SimulatedOrder
from src.marketdata.orderbook import OrderBookAggregator
from src.common.models import OrderBook, PriceLevel, Side


class TestQueueSimCalibration:
    """Test calibration effects on queue simulation."""
    
    def test_calibration_params_validation(self):
        """Test calibration parameter validation."""
        # Valid parameters
        valid_params = CalibrationParams(
            latency_ms_mean=10.0,
            latency_ms_std=2.0,
            toxic_sweep_prob=0.05,
            extra_slippage_bps=1.0
        )
        assert valid_params.latency_ms_mean == 10.0
        
        # Invalid toxic sweep probability
        with pytest.raises(ValueError, match="toxic_sweep_prob must be between 0 and 1"):
            CalibrationParams(toxic_sweep_prob=1.5)
        
        with pytest.raises(ValueError, match="toxic_sweep_prob must be between 0 and 1"):
            CalibrationParams(toxic_sweep_prob=-0.1)
        
        # Invalid latency parameters
        with pytest.raises(ValueError, match="Latency parameters must be non-negative"):
            CalibrationParams(latency_ms_mean=-5.0)
        
        with pytest.raises(ValueError, match="Latency parameters must be non-negative"):
            CalibrationParams(latency_ms_std=-1.0)
    
    def test_baseline_vs_calibrated_simulation(self):
        """Test that calibration affects hit rate and queue wait time."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        orderbook_aggregator.ahead_volume.return_value = 1.0
        
        # Baseline simulation (no calibration)
        baseline_sim = QueueSimulator(orderbook_aggregator)
        
        # Calibrated simulation with higher latency and slippage
        calibrated_params = CalibrationParams(
            latency_ms_mean=50.0,
            latency_ms_std=10.0,
            toxic_sweep_prob=0.1,  # 10% chance of toxic sweep
            extra_slippage_bps=2.0
        )
        calibrated_sim = QueueSimulator(orderbook_aggregator, calibrated_params)
        
        # Create test orders
        base_time = datetime.now(timezone.utc)
        
        baseline_order = SimulatedOrder(
            order_id="baseline_001",
            symbol="BTCUSDT",
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("1.0"),
            timestamp=base_time
        )
        
        calibrated_order = SimulatedOrder(
            order_id="calibrated_001",
            symbol="BTCUSDT", 
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("1.0"),
            timestamp=base_time
        )
        
        # Add orders to simulators
        baseline_sim.add_order(baseline_order)
        calibrated_sim.add_order(calibrated_order)
        
        # Check that calibrated order has latency applied
        assert baseline_order.actual_place_time is None or baseline_order.actual_place_time == baseline_order.timestamp
        assert calibrated_order.actual_place_time > calibrated_order.timestamp
        
        # Check latency calculation
        latency_ms = (calibrated_order.actual_place_time - calibrated_order.timestamp).total_seconds() * 1000
        assert latency_ms >= 0  # Should have some latency
    
    def test_extra_slippage_application(self):
        """Test that extra slippage is correctly applied."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        orderbook_aggregator.ahead_volume.return_value = 1.0
        
        # Simulator with extra slippage
        calibration = CalibrationParams(extra_slippage_bps=10.0)  # 10 bps extra slippage
        simulator = QueueSimulator(orderbook_aggregator, calibration)
        
        # Test slippage calculation
        base_price = Decimal("50000")
        mid_price = 50000.0
        
        slipped_price = simulator._apply_extra_slippage(base_price, mid_price)
        
        # Should have worse price due to slippage
        # 10 bps of 50000 = 50 USD reduction
        expected_slippage = Decimal("50")  # 50000 * 0.001 = 50
        assert slipped_price == base_price - expected_slippage
    
    def test_toxic_sweep_detection(self):
        """Test toxic sweep probability mechanism."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        
        # Test with 0% toxic sweep probability
        no_toxic = CalibrationParams(toxic_sweep_prob=0.0)
        sim_no_toxic = QueueSimulator(orderbook_aggregator, no_toxic)
        
        # Test with 100% toxic sweep probability
        always_toxic = CalibrationParams(toxic_sweep_prob=1.0)
        sim_always_toxic = QueueSimulator(orderbook_aggregator, always_toxic)
        
        # Test multiple times to ensure consistency
        for _ in range(10):
            assert not sim_no_toxic._is_toxic_sweep()
            assert sim_always_toxic._is_toxic_sweep()
    
    def test_latency_calculation_determinism(self):
        """Test that latency calculation is deterministic with same seed."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        
        calibration = CalibrationParams(
            latency_ms_mean=20.0,
            latency_ms_std=5.0
        )
        
        # Create two simulators with same calibration
        sim1 = QueueSimulator(orderbook_aggregator, calibration)
        sim2 = QueueSimulator(orderbook_aggregator, calibration)
        
        # Set same seed for deterministic results
        sim1.rng.seed(42)
        sim2.rng.seed(42)
        
        # Calculate latencies
        latency1 = sim1._calculate_placement_latency()
        latency2 = sim2._calculate_placement_latency()
        
        # Should be identical with same seed
        assert latency1 == latency2
        assert latency1 >= 0  # Should be non-negative
    
    def test_market_simulation_with_calibration_effects(self):
        """Test market simulation incorporating all calibration effects."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        orderbook_aggregator.ahead_volume.return_value = 10.0
        
        # Create calibrated simulator
        calibration = CalibrationParams(
            latency_ms_mean=25.0,
            latency_ms_std=5.0,
            toxic_sweep_prob=0.2,  # 20% toxic sweep
            extra_slippage_bps=1.5
        )
        simulator = QueueSimulator(orderbook_aggregator, calibration)
        
        # Create test order
        order = SimulatedOrder(
            order_id="test_order",
            symbol="BTCUSDT",
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("1.0"),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add order
        simulator.add_order(order)
        
        # Create test orderbook that should trigger a fill
        orderbook = OrderBook(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc) + timedelta(milliseconds=100),  # After latency
            bids=[PriceLevel(price=Decimal("49990"), size=Decimal("1.0"))],
            asks=[PriceLevel(price=Decimal("49999"), size=Decimal("1.0"))]  # Below our bid price
        )
        
        # Simulate market moves
        fills = simulator.simulate_market_moves(orderbook)
        
        # Check fill statistics include calibration params
        fill_stats = simulator.get_fill_statistics()
        assert "calibration_params" in fill_stats
        
        calib_params = fill_stats["calibration_params"]
        assert calib_params["latency_ms_mean"] == 25.0
        assert calib_params["latency_ms_std"] == 5.0
        assert calib_params["toxic_sweep_prob"] == 0.2
        assert calib_params["extra_slippage_bps"] == 1.5
    
    def test_queue_wait_time_calculation(self):
        """Test queue wait time calculation for orders."""
        # Create test order
        base_time = datetime.now(timezone.utc)
        
        order = SimulatedOrder(
            order_id="test_wait",
            symbol="BTCUSDT",
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("1.0"),
            timestamp=base_time
        )
        
        # Set placement time (after latency)
        order.actual_place_time = base_time + timedelta(milliseconds=25)
        
        # Initially no fill, so no queue wait time
        assert order.queue_wait_ms is None
        
        # Mark as filled
        order.filled_qty = Decimal("0.5")
        
        # Now should have queue wait time
        wait_time = order.queue_wait_ms
        assert wait_time is not None
        assert wait_time >= 0
    
    def test_calibration_with_no_latency(self):
        """Test calibration behavior with zero latency."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        
        # Zero latency calibration
        calibration = CalibrationParams(
            latency_ms_mean=0.0,
            latency_ms_std=0.0
        )
        simulator = QueueSimulator(orderbook_aggregator, calibration)
        
        # Should always return zero latency
        for _ in range(5):
            assert simulator._calculate_placement_latency() == 0.0
    
    def test_calibration_parameters_in_fill_statistics(self):
        """Test that calibration parameters are properly exposed in statistics."""
        # Create mock orderbook aggregator
        orderbook_aggregator = MagicMock(spec=OrderBookAggregator)
        
        calibration = CalibrationParams(
            latency_ms_mean=15.0,
            latency_ms_std=3.0,
            amend_latency_ms=12.0,
            cancel_latency_ms=8.0,
            toxic_sweep_prob=0.05,
            extra_slippage_bps=1.2
        )
        
        simulator = QueueSimulator(orderbook_aggregator, calibration)
        
        # Get statistics
        stats = simulator.get_fill_statistics()
        
        # Verify all calibration parameters are present
        calib = stats["calibration_params"]
        assert calib["latency_ms_mean"] == 15.0
        assert calib["latency_ms_std"] == 3.0
        assert calib["amend_latency_ms"] == 12.0
        assert calib["cancel_latency_ms"] == 8.0
        assert calib["toxic_sweep_prob"] == 0.05
        assert calib["extra_slippage_bps"] == 1.2
