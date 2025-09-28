#!/usr/bin/env python3
"""
Demo script for Rust-backed L2 order book.
Shows performance comparison between Rust and Python implementations.
"""

import time
import random
from decimal import Decimal
from typing import List, Tuple

# Try to import Rust extension
try:
    from mm_orderbook import L2Book
    RUST_AVAILABLE = True
    print("✓ Rust extension loaded successfully")
except ImportError:
    RUST_AVAILABLE = False
    print("⚠ Rust extension not available, using Python fallback")


def generate_market_data(num_levels: int = 100) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]:
    """Generate realistic market data for testing."""
    base_price = 50000.0
    
    # Generate bids (descending prices)
    bids = []
    for i in range(num_levels):
        price = base_price - (i * 0.5)  # 0.5 tick size
        size = random.uniform(0.1, 10.0)
        bids.append((price, size))
    
    # Generate asks (ascending prices)
    asks = []
    for i in range(num_levels):
        price = base_price + (i * 0.5)  # 0.5 tick size
        size = random.uniform(0.1, 10.0)
        asks.append((price, size))
    
    return bids, asks


def benchmark_orderbook_operations(use_rust: bool = True):
    """Benchmark order book operations."""
    print(f"\n{'='*60}")
    print(f"Benchmarking {'Rust' if use_rust else 'Python'} Order Book")
    print(f"{'='*60}")
    
    if use_rust and not RUST_AVAILABLE:
        print("Rust extension not available, skipping benchmark")
        return
    
    # Generate test data
    print("Generating test data...")
    bids, asks = generate_market_data(1000)
    
    # Initialize order book
    if use_rust:
        book = L2Book()
    else:
        # Python fallback would go here
        print("Python fallback not implemented in this demo")
        return
    
    # Benchmark snapshot application
    print("Benchmarking snapshot application...")
    start_time = time.perf_counter()
    
    for _ in range(100):
        book.apply_snapshot(bids, asks)
    
    snapshot_time = time.perf_counter() - start_time
    print(f"Snapshot (100x): {snapshot_time:.6f}s ({snapshot_time/100*1000:.3f}ms per operation)")
    
    # Benchmark delta updates
    print("Benchmarking delta updates...")
    start_time = time.perf_counter()
    
    for i in range(1000):
        # Generate random delta
        delta_bids = [(bids[i % len(bids)][0], random.uniform(0, 15)) for _ in range(5)]
        delta_asks = [(asks[i % len(asks)][0], random.uniform(0, 15)) for _ in range(5)]
        book.apply_delta(delta_bids, delta_asks)
    
    delta_time = time.perf_counter() - start_time
    print(f"Delta updates (1000x): {delta_time:.6f}s ({delta_time/1000*1000:.3f}ms per operation)")
    
    # Benchmark market data calculations
    print("Benchmarking market data calculations...")
    start_time = time.perf_counter()
    
    for _ in range(10000):
        _ = book.best_bid()
        _ = book.best_ask()
        _ = book.mid()
        _ = book.microprice()
        _ = book.imbalance(5)
    
    calc_time = time.perf_counter() - start_time
    print(f"Calculations (10000x): {calc_time:.6f}s ({calc_time/10000*1000:.3f}ms per operation)")
    
    # Show final state
    print(f"\nFinal order book state:")
    print(f"Best bid: {book.best_bid()}")
    print(f"Best ask: {book.best_ask()}")
    print(f"Mid price: {book.mid():.2f}")
    print(f"Microprice: {book.microprice():.2f}")
    print(f"Imbalance (5 levels): {book.imbalance(5):.4f}")


def demonstrate_orderbook_features():
    """Demonstrate order book features."""
    if not RUST_AVAILABLE:
        print("Rust extension not available for demonstration")
        return
    
    print(f"\n{'='*60}")
    print("Order Book Feature Demonstration")
    print(f"{'='*60}")
    
    # Create order book
    book = L2Book()
    
    # 1. Apply initial snapshot
    print("1. Applying initial snapshot...")
    initial_bids = [(50000.0, 2.0), (49999.5, 1.5), (49999.0, 3.0)]
    initial_asks = [(50001.0, 1.0), (50001.5, 2.5), (50002.0, 1.8)]
    
    book.apply_snapshot(initial_bids, initial_asks)
    
    print(f"   Best bid: {book.best_bid()}")
    print(f"   Best ask: {book.best_ask()}")
    print(f"   Mid price: {book.mid():.2f}")
    print(f"   Microprice: {book.microprice():.2f}")
    print(f"   Imbalance: {book.imbalance(5):.4f}")
    
    # 2. Apply delta updates
    print("\n2. Applying delta updates...")
    
    # Add new bid level
    book.apply_delta([(49998.5, 2.2)], [])
    print(f"   Added bid at 49998.5: {book.best_bid()}")
    
    # Update existing ask level
    book.apply_delta([], [(50001.0, 0.5)])  # Reduce size
    print(f"   Updated ask at 50001.0: {book.best_ask()}")
    
    # Remove bid level
    book.apply_delta([(49999.0, 0.0)], [])  # size <= 0 removes level
    print(f"   Removed bid at 49999.0")
    
    # 3. Show final state
    print(f"\n3. Final state after updates:")
    print(f"   Best bid: {book.best_bid()}")
    print(f"   Best ask: {book.best_ask()}")
    print(f"   Mid price: {book.mid():.2f}")
    print(f"   Microprice: {book.microprice():.2f}")
    print(f"   Imbalance: {book.imbalance(5):.4f}")
    
    # 4. Clear and reset
    print(f"\n4. Clearing order book...")
    book.clear()
    
    print(f"   Best bid: {book.best_bid()}")
    print(f"   Best ask: {book.best_ask()}")
    print(f"   Mid price: {book.mid()}")


def performance_comparison():
    """Compare performance between implementations."""
    print(f"\n{'='*60}")
    print("Performance Comparison")
    print(f"{'='*60}")
    
    if RUST_AVAILABLE:
        print("Rust extension available - running performance benchmarks...")
        benchmark_orderbook_operations(use_rust=True)
    else:
        print("Rust extension not available - cannot run performance comparison")
        print("Install with: make rust-install")


def main():
    """Main demonstration function."""
    print("Rust-Backed L2 Order Book Demonstration")
    print("=" * 60)
    
    # Check availability
    if RUST_AVAILABLE:
        print("✓ Rust extension is available")
        print(f"   Type: {type(L2Book())}")
    else:
        print("⚠ Rust extension not available")
        print("   Install with: make rust-install")
        print("   Or build manually: cd rust && maturin develop --release")
    
    # Demonstrate features
    demonstrate_orderbook_features()
    
    # Performance comparison
    performance_comparison()
    
    print(f"\n{'='*60}")
    print("Demonstration completed!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
