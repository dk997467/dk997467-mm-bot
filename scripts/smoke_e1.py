#!/usr/bin/env python3
"""
E1 Smoke Test Script for Live Summaries validation.

Generates synthetic order/quote events around hour boundary and validates
that hourly summary files are created with correct schema.
"""

import argparse
import asyncio
import json
import random
import sys
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List
from decimal import Decimal
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.research_recorder import ResearchRecorder
from src.common.config import AppConfig
from src.common.models import OrderBook, PriceLevel, Order, Side, OrderType


def setup_determinism(seed: int):
    """Setup deterministic random number generation."""
    random.seed(seed)
    np.random.seed(seed)


def create_mock_config() -> AppConfig:
    """Create a mock AppConfig for the recorder."""
    config = MagicMock(spec=AppConfig)
    config.storage = MagicMock()
    config.storage.compress = 'none'  # No compression for smoke test
    config.storage.batch_size = 100
    config.storage.flush_ms = 50
    return config


def create_synthetic_orderbook(symbol: str, mid_price: float, timestamp: datetime, sequence: int = 0) -> OrderBook:
    """Create synthetic orderbook around mid price."""
    spread = 0.002  # 0.2% spread
    bid_price = mid_price * (1 - spread / 2)
    ask_price = mid_price * (1 + spread / 2)
    
    return OrderBook(
        symbol=symbol,
        timestamp=timestamp,
        sequence=sequence,
        bids=[PriceLevel(price=Decimal(str(bid_price)), size=Decimal('10.0'))],
        asks=[PriceLevel(price=Decimal(str(ask_price)), size=Decimal('10.0'))]
    )


def create_synthetic_quotes(mid_price: float, price_bins: List[int]) -> Dict[str, List[Dict]]:
    """Create synthetic quotes at specified price bins."""
    quotes = {"bids": [], "asks": []}
    
    for bin_bps in price_bins:
        # Convert bps to price offset
        offset = (bin_bps / 10000) * mid_price
        
        # Add bid and ask at this bin
        quotes["bids"].append({
            "price": mid_price - offset,
            "size": random.uniform(0.1, 2.0)
        })
        quotes["asks"].append({
            "price": mid_price + offset,
            "size": random.uniform(0.1, 2.0)
        })
    
    return quotes


async def run_smoke_test(symbol: str, seed: int, out_dir: str) -> bool:
    """
    Run the E1 smoke test.
    
    Returns True if all validations pass, False otherwise.
    """
    print(f"E1 SMOKE: Starting test for {symbol} with seed {seed}")
    
    setup_determinism(seed)
    
    # Create output directory
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    # Initialize recorder - use out_path as the base directory for research data
    config = create_mock_config()
    recorder = ResearchRecorder(
        config, 
        str(out_path), 
        summaries_dir=str(out_path / "summaries"),
        retention_days=None  # Disable retention for smoke test
    )
    
    try:
        await recorder.start()
        
        # Define time window around hour boundary
        now = datetime.now(timezone.utc)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        
        # Events from HH:59:30 to (HH+1):00:30
        start_time = current_hour - timedelta(seconds=30)
        end_time = current_hour + timedelta(minutes=1, seconds=30)
        
        print(f"E1 SMOKE: Generating events from {start_time} to {end_time}")
        
        # Parameters for synthetic data
        mid_price = 100.0
        price_bins = [0, 5, 15, 40]  # bps from mid
        event_count = 0
        sequence = 1000  # Starting sequence number
        
        # Generate events across the time window
        current_time = start_time
        while current_time <= end_time and event_count < 120:
            # Advance time by random interval (0.5 to 2 seconds)
            current_time += timedelta(seconds=random.uniform(0.5, 2.0))
            
            # Create market snapshot event
            orderbook = create_synthetic_orderbook(symbol, mid_price, current_time, sequence)
            selected_bins = random.sample(price_bins, random.randint(1, 3))
            our_quotes = create_synthetic_quotes(mid_price, selected_bins)
            
            sequence += 1  # Increment sequence for next event
            
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.15)
            event_count += 1
            
            # Sometimes generate order events
            if random.random() < 0.3:  # 30% chance
                # Create order
                price_bin = random.choice(price_bins)
                order_price = mid_price + (price_bin / 10000) * mid_price * random.choice([-1, 1])
                
                order = Order(
                    order_id=f"smoke_{event_count}",
                    symbol=symbol,
                    side=random.choice([Side.BUY, Side.SELL]),
                    order_type=OrderType.LIMIT,
                    price=Decimal(str(order_price)),
                    qty=Decimal(str(round(random.uniform(0.1, 1.0), 4))),
                    created_time=current_time
                )
                
                # Record order creation
                recorder.record_order_event(
                    event_type="create",
                    order=order,
                    mid_price=mid_price
                )
                event_count += 1
                
                # Sometimes record fill
                if random.random() < 0.4:  # 40% of orders get filled
                    queue_wait_ms = max(0, np.random.normal(200, 50))
                    
                    fill_ratio = random.uniform(0.3, 1.0)
                    fill_qty = float(order.qty) * fill_ratio
                    
                    recorder.record_order_event(
                        event_type="fill",
                        order=order,
                        fill_price=order_price,
                        fill_qty=fill_qty,
                        queue_wait_ms=queue_wait_ms,
                        mid_price=mid_price
                    )
                    event_count += 1
        
        print(f"E1 SMOKE: Generated {event_count} events")
        
        # Mock the git_sha and cfg_hash functions before generating summaries
        from unittest.mock import patch
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='smoke_test_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='smoke_test_hash'):
            
            # Force flush of current hour
            await recorder._generate_hourly_summaries(current_hour)
            await recorder._generate_hourly_summaries(current_hour + timedelta(hours=1))
        
        # Stop recorder
        await recorder.stop()
        
        # Validate generated files - look for summaries in the proper location
        # Since we create summaries under data_dir/summaries/symbol
        summaries_dir = out_path / "summaries" / symbol
        if not summaries_dir.exists():
            print(f"E1 SMOKE: FAIL - Summaries directory not found: {summaries_dir}")
            return False
        
        # Find JSON files
        json_files = list(summaries_dir.glob(f"{symbol}_*.json"))
        if len(json_files) == 0:
            print(f"E1 SMOKE: FAIL - No summary files found in {summaries_dir}")
            return False
        
        print(f"E1 SMOKE: Found {len(json_files)} summary files")
        
        # Validate each file
        for json_file in json_files:
            if not validate_summary_file(json_file):
                return False
        
        print("E1 SMOKE: OK")
        return True
        
    except Exception as e:
        print(f"E1 SMOKE: FAIL - Exception: {e}")
        return False


def validate_summary_file(file_path: Path) -> bool:
    """Validate the schema and content of a summary file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Check required top-level keys
        required_keys = ["symbol", "hour_utc", "counts", "hit_rate_by_bin", 
                        "queue_wait_cdf_ms", "metadata"]
        for key in required_keys:
            if key not in data:
                print(f"E1 SMOKE: FAIL - Missing key '{key}' in {file_path}")
                return False
        
        # Validate counts structure
        counts = data["counts"]
        for count_key in ["orders", "quotes", "fills"]:
            if count_key not in counts or not isinstance(counts[count_key], int):
                print(f"E1 SMOKE: FAIL - Invalid counts.{count_key} in {file_path}")
                return False
        
        # Validate hit_rate_by_bin
        hit_rates = data["hit_rate_by_bin"]
        total_quotes = 0
        total_fills = 0
        
        for bin_key, bin_data in hit_rates.items():
            if not isinstance(bin_data, dict):
                print(f"E1 SMOKE: FAIL - Invalid hit_rate_by_bin[{bin_key}] in {file_path}")
                return False
            
            if "count" not in bin_data or "fills" not in bin_data:
                print(f"E1 SMOKE: FAIL - Missing count/fills in hit_rate_by_bin[{bin_key}] in {file_path}")
                return False
            
            count = bin_data["count"]
            fills = bin_data["fills"]
            
            if fills > count:
                print(f"E1 SMOKE: FAIL - fills > count in bin {bin_key} in {file_path}")
                return False
            
            total_quotes += count
            total_fills += fills
        
        # Check that totals make sense
        if total_fills > total_quotes:
            print(f"E1 SMOKE: FAIL - Total fills > total quotes in {file_path}")
            return False
        
        # Validate queue wait CDF
        cdf = data["queue_wait_cdf_ms"]
        if not isinstance(cdf, list):
            print(f"E1 SMOKE: FAIL - queue_wait_cdf_ms is not a list in {file_path}")
            return False
        
        # Check CDF monotonicity
        prev_p = -1
        prev_v = -1
        for point in cdf:
            if not isinstance(point, dict) or "p" not in point or "v" not in point:
                print(f"E1 SMOKE: FAIL - Invalid CDF point in {file_path}")
                return False
            
            p = point["p"]
            v = point["v"]
            
            if p <= prev_p:
                print(f"E1 SMOKE: FAIL - CDF p values not increasing in {file_path}")
                return False
            
            if v < prev_v:
                print(f"E1 SMOKE: FAIL - CDF v values decreasing in {file_path}")
                return False
            
            prev_p = p
            prev_v = v
        
        # Validate metadata
        metadata = data["metadata"]
        if "git_sha" not in metadata or "cfg_hash" not in metadata:
            print(f"E1 SMOKE: FAIL - Missing metadata fields in {file_path}")
            return False
        
        print(f"E1 SMOKE: Validated {file_path.name}")
        return True
        
    except Exception as e:
        print(f"E1 SMOKE: FAIL - Error validating {file_path}: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='E1 Smoke Test for Live Summaries')
    parser.add_argument('--symbol', default='TEST', help='Symbol to test (default: TEST)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')
    parser.add_argument('--out', default='data/research/summaries', 
                       help='Output directory (default: data/research/summaries)')
    
    args = parser.parse_args()
    
    # Run the smoke test
    success = asyncio.run(run_smoke_test(args.symbol, args.seed, args.out))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
