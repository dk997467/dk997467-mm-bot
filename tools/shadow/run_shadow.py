#!/usr/bin/env python3
"""
Shadow Mode Runner

Connects to real exchange feeds (Bybit/KuCoin), simulates order placements
locally without API writes, and generates KPI metrics comparable to soak tests.

Supports per-symbol profiles and rich artifact metadata.

Usage:
    python -m tools.shadow.run_shadow --iterations 6 --duration 60
    python -m tools.shadow.run_shadow --profile aggressive --source mock
"""

import argparse
import asyncio
import json
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Mock mode: Generate synthetic market data for testing
MOCK_MODE = True  # Toggle to False for real WS feeds


def _git_sha_short() -> str:
    """Get short git commit SHA (fallback: 'unknown')."""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL
        )
        return result.strip()
    except Exception:
        return "unknown"


def load_symbol_profile(symbol: str) -> Dict:
    """
    Load per-symbol profile overrides from profiles/shadow_profiles.json.
    
    Args:
        symbol: Symbol name (e.g., "BTCUSDT")
    
    Returns:
        Dict with profile parameters (empty if not found)
    """
    profile_path = Path("profiles/shadow_profiles.json")
    if not profile_path.exists():
        return {}
    
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profiles = json.load(f)
        return profiles.get(symbol, {})
    except Exception:
        return {}


class MiniLOB:
    """Minimal LOB state for fill simulation."""
    
    def __init__(self):
        self.best_bid = None  # (price, size)
        self.best_ask = None  # (price, size)
        self.last_trade_qty = 0.0
    
    def on_tick(self, tick: dict):
        """Update LOB state from market tick."""
        if "bid" in tick:
            self.best_bid = (tick["bid"], tick.get("bid_size", 0.0))
        if "ask" in tick:
            self.best_ask = (tick["ask"], tick.get("ask_size", 0.0))
        if "last_qty" in tick:
            self.last_trade_qty = tick["last_qty"]


class ShadowSimulator:
    """
    Shadow mode simulator that consumes market data and simulates trades locally.
    
    Supports multiple data sources: mock, ws (WebSocket), redis (Redis Streams).
    """
    
    def __init__(
        self,
        exchange: str = "bybit",
        symbols: List[str] = None,
        profile: str = "moderate",
        source: str = "mock",
        min_lot: float = 0.0,
        touch_dwell_ms: float = 25.0,
        require_volume: bool = False,
        # Redis-specific parameters
        redis_url: str = "redis://localhost:6379",
        redis_stream: str = "lob:ticks",
        redis_group: str = "shadow",
        redis_consumer_id: Optional[str] = None,
    ):
        self.exchange = exchange
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self.profile = profile
        self.source = source  # "mock", "ws", or "redis"
        self.min_lot = min_lot
        self.touch_dwell_ms = touch_dwell_ms
        self.require_volume = require_volume
        
        # Redis parameters
        self.redis_url = redis_url
        self.redis_stream = redis_stream
        self.redis_group = redis_group
        self.redis_consumer_id = redis_consumer_id
        
        # KPI tracking
        self.maker_count = 0
        self.taker_count = 0
        self.latencies = []
        self.net_bps_values = []
        self.risk_ratios = []
        self.clock_drift_ewma = 0.0  # EWMA of clock drift
        
        # Ingest statistics (for Redis source)
        self.seq_gaps = 0
        self.reordered = 0
        self.bp_drops = 0
        
    async def connect_feed(self):
        """Connect to data source (mock/ws/redis)."""
        if self.source == "mock":
            print(f"[MOCK] Simulating {self.exchange} feed for {self.symbols}")
        elif self.source == "redis":
            print(f"[REDIS] Connecting to Redis Streams: {self.redis_stream}")
            print(f"        URL: {self.redis_url}")
            print(f"        Group: {self.redis_group}")
        else:  # ws
            print(f"[WS] Connecting to {self.exchange} WebSocket feed...")
            # TODO: Implement real WS connection
            # await websockets.connect(f"wss://{self.exchange}.com/ws")
    
    def _compute_p95(self, values: List[float]) -> float:
        """Compute 95th percentile."""
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * 0.95)
        return sorted_vals[idx]
    
    def _simulate_lob_fills(
        self,
        ticks: List[Dict],
        spread_bps: float,
    ) -> tuple:
        """
        Simulate fills via LOB intersections.
        
        Virtual limits placed at best_bid - δ and best_ask + δ,
        where δ = spread_bps * 1e-4 * mid.
        
        Fill conditions:
        - BUY fill: best_ask <= buy_px, dwell >= touch_dwell_ms, volume OK
        - SELL fill: best_bid >= sell_px, dwell >= touch_dwell_ms, volume OK
        
        Returns:
            (maker_count, taker_count, maker_taker_ratio, p95_latency,
             risk_ratio, net_bps, clock_drift_ms)
        """
        lob = MiniLOB()
        maker = 0
        taker = 0
        lat_corr_ms = []
        drift_ms = self.clock_drift_ewma
        alpha = 0.05  # EWMA smoothing
        
        last_touch_buy = None
        last_touch_sell = None
        
        for t in ticks:
            # Clock-sync: server_ts → ingest_ts
            server_ts = t.get("ts_server", t.get("ts", time.time()))
            ingest_ts = time.time()
            
            drift_cur = (ingest_ts - server_ts) * 1000.0
            drift_ms = (1 - alpha) * drift_ms + alpha * drift_cur
            
            latency_ms = max(0.0, (ingest_ts - server_ts) * 1000.0)
            lat_corr_ms.append(latency_ms)
            
            lob.on_tick(t)
            
            if not (lob.best_bid and lob.best_ask):
                continue
            
            mid = 0.5 * (lob.best_bid[0] + lob.best_ask[0])
            delta = spread_bps * 1e-4 * mid
            
            buy_px = lob.best_bid[0] - delta
            sell_px = lob.best_ask[0] + delta
            
            # BUY: fill if best_ask <= buy_px
            if lob.best_ask[0] <= buy_px:
                last_touch_buy = last_touch_buy or ingest_ts
                dwell = (ingest_ts - last_touch_buy) * 1000.0
                vol_ok = (lob.last_trade_qty >= self.min_lot) if self.require_volume else True
                
                if dwell >= self.touch_dwell_ms and vol_ok:
                    maker += 1
                    last_touch_buy = None
            else:
                last_touch_buy = None
            
            # SELL: fill if best_bid >= sell_px
            if lob.best_bid[0] >= sell_px:
                last_touch_sell = last_touch_sell or ingest_ts
                dwell = (ingest_ts - last_touch_sell) * 1000.0
                vol_ok = (lob.last_trade_qty >= self.min_lot) if self.require_volume else True
                
                if dwell >= self.touch_dwell_ms and vol_ok:
                    maker += 1
                    last_touch_sell = None
            else:
                last_touch_sell = None
        
        # Update EWMA
        self.clock_drift_ewma = drift_ms
        
        # Compute metrics
        total = max(1, maker + taker)
        maker_taker = maker / total
        p95 = self._compute_p95(lat_corr_ms)
        risk_ratio = min(0.80, 1.0 - maker_taker)
        net_bps = max(0.0, (maker_taker - 0.20) * 10.0)
        
        return maker, taker, maker_taker, p95, risk_ratio, net_bps, drift_ms
    
    async def simulate_iteration(self, iter_num: int, duration: int) -> Dict:
        """
        Simulate one iteration (monitoring window).
        
        Args:
            iter_num: Iteration number
            duration: Duration in seconds
        
        Returns:
            Dict with iteration summary (same schema as ITER_SUMMARY)
        """
        print(f"[ITER {iter_num}] Starting {duration}s shadow window...")
        
        # Collect market ticks
        start_time = time.time()
        ticks = []
        
        if self.source == "redis":
            # Read from Redis Streams with reordering buffer
            from tools.shadow.ingest_redis import read_ticks_redis
            from tools.shadow.reorder_buffer import ReorderBuffer
            
            buffer = ReorderBuffer(window_ms=40.0, max_size=4000)
            
            # Read ticks for duration
            async def collect_redis_ticks():
                deadline = start_time + duration
                tick_count = 0
                
                async for tick in read_ticks_redis(
                    self.redis_url,
                    self.redis_stream,
                    self.redis_group,
                    self.redis_consumer_id,
                ):
                    # Filter by symbol (only process relevant symbols)
                    symbol = tick.get("symbol", "")
                    if symbol not in self.symbols:
                        continue
                    
                    # Track seq gaps
                    if "_seq_gap_warning" in tick:
                        self.seq_gaps += 1
                    
                    # Add to reorder buffer
                    buffer.add(tick)
                    tick_count += 1
                    
                    # Check deadline
                    if time.time() >= deadline:
                        break
                
                # Final flush
                return buffer.flush(force=True)
            
            ticks = await collect_redis_ticks()
            
            # Update ingest stats
            stats = buffer.get_stats()
            self.reordered = sum(stats["reordered"].values())
            self.bp_drops = sum(stats["backpressure_drops"].values())
            
        else:
            # Mock or WS mode
            samples = duration  # 1 sample per second
            
            for tick_idx in range(samples):
                await asyncio.sleep(0.1 if self.source == "mock" else 1.0)
                
                # Generate synthetic tick (mock mode)
                if self.source == "mock":
                    base_price = 50000.0 + random.uniform(-100, 100)
                    spread = random.uniform(0.5, 2.0)
                    
                    tick = {
                        "ts": time.time() - random.uniform(0.05, 0.15),
                        "ts_server": time.time() - random.uniform(0.05, 0.15),
                        "bid": base_price,
                        "ask": base_price + spread,
                        "bid_size": random.uniform(0.1, 5.0),
                        "ask_size": random.uniform(0.1, 5.0),
                        "last_qty": random.uniform(0.001, 0.5),
                    }
                    ticks.append(tick)
        
        # Determine spread_bps based on profile
        spread_bps = 30.0 if self.profile == "moderate" else 15.0
        
        # Run LOB-based simulation
        maker, taker, maker_taker, p95, risk, net_bps, drift_ms = self._simulate_lob_fills(
            ticks, spread_bps
        )
        
        elapsed = time.time() - start_time
        
        # Slippage & adverse (mock approximations)
        slippage_p95 = random.uniform(0.8, 1.5)
        adverse_p95 = random.uniform(1.5, 2.5)
        
        # Rich notes with metadata
        commit_sha = _git_sha_short()
        notes = (
            f"commit={commit_sha} "
            f"source={self.source} "
            f"profile={self.profile} "
            f"dwell_ms={self.touch_dwell_ms} "
            f"min_lot={self.min_lot}"
        )
        
        # Add ingest stats for Redis source
        if self.source == "redis":
            notes += (
                f" seq_gaps={self.seq_gaps} "
                f"reordered={self.reordered} "
                f"bp_drops={self.bp_drops}"
            )
        
        summary = {
            "iteration": iter_num,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "duration_seconds": int(elapsed),
            "exchange": self.exchange,
            "symbols": self.symbols,
            "profile": self.profile,
            "summary": {
                "maker_count": maker,
                "taker_count": taker,
                "maker_taker_ratio": round(maker_taker, 3),
                "net_bps": round(net_bps, 2),
                "p95_latency_ms": round(p95, 1),
                "risk_ratio": round(risk, 3),
                "slippage_bps_p95": round(slippage_p95, 2),
                "adverse_bps_p95": round(adverse_p95, 2),
                "clock_drift_ms": round(drift_ms, 2),
            },
            "notes": notes,
            "mode": "shadow",
        }
        
        print(f"[ITER {iter_num}] Completed: "
              f"maker/taker={maker_taker:.3f}, "
              f"edge={net_bps:.2f}, "
              f"latency={p95:.0f}ms, "
              f"risk={risk:.3f}, "
              f"drift={drift_ms:.1f}ms")
        
        return summary
    
    async def run(
        self,
        iterations: int,
        duration: int,
        output_dir: str,
        redis_export_enabled: bool = False,
        redis_export_url: str = "redis://localhost:6379"
    ):
        """
        Run shadow mode for N iterations.
        
        Args:
            iterations: Number of monitoring windows
            duration: Duration per iteration (seconds)
            output_dir: Output directory for artifacts
            redis_export_enabled: Enable Redis KPI export after each iteration (default: False)
            redis_export_url: Redis connection URL for export (default: redis://localhost:6379)
        """
        await self.connect_feed()
        
        # Prepare output directory
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Redis exporter if enabled
        redis_exporter = None
        if redis_export_enabled:
            try:
                from tools.shadow.export_to_redis import RedisKPIExporter
                redis_exporter = RedisKPIExporter(redis_url=redis_export_url, mode="hash")
                print(f"[REDIS-EXPORT] Enabled (URL: {redis_export_url})")
            except ImportError as e:
                print(f"[REDIS-EXPORT] WARNING: Failed to import RedisKPIExporter: {e}")
                print(f"[REDIS-EXPORT] Continuing without Redis export")
                redis_exporter = None
            except Exception as e:
                print(f"[REDIS-EXPORT] WARNING: Failed to initialize Redis exporter: {e}")
                print(f"[REDIS-EXPORT] Continuing without Redis export")
                redis_exporter = None
        
        print(f"[SHADOW] Running {iterations} iterations, {duration}s each")
        print(f"[SHADOW] Output: {output_dir}")
        print("=" * 80)
        
        summaries = []
        
        for i in range(1, iterations + 1):
            summary = await self.simulate_iteration(i, duration)
            summaries.append(summary)
            
            # Write ITER_SUMMARY_N.json
            iter_file = out_path / f"ITER_SUMMARY_{i}.json"
            with open(iter_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
            
            print(f"[ITER {i}] Saved: {iter_file.name}")
            
            # Export to Redis if enabled
            if redis_exporter:
                try:
                    symbol = summary.get("symbol", "UNKNOWN")
                    success = redis_exporter.export_snapshot(summary, symbol=symbol)
                    if success:
                        print(f"[REDIS-EXPORT] Exported iteration {i} KPIs for {symbol}")
                except Exception as e:
                    print(f"[REDIS-EXPORT] WARNING: Export failed for iteration {i}: {e}")
            
            print()
        
        # Write SHADOW_RUN_SUMMARY.json
        run_summary = {
            "total_iterations": iterations,
            "duration_per_iteration": duration,
            "exchange": self.exchange,
            "symbols": self.symbols,
            "profile": self.profile,
            "mode": "shadow",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "iterations": summaries,
        }
        
        summary_file = out_path / "SHADOW_RUN_SUMMARY.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(run_summary, f, indent=2)
        
        print("=" * 80)
        print(f"[SHADOW] Run complete!")
        print(f"[SHADOW] Artifacts: {output_dir}")
        print(f"[SHADOW] Summary: {summary_file.name}")
        print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Shadow Mode: Live feed monitoring with local simulation"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=6,
        help="Number of monitoring windows (default: 6)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration per iteration in seconds (default: 60)"
    )
    parser.add_argument(
        "--exchange",
        default="bybit",
        choices=["bybit", "kucoin"],
        help="Exchange to monitor (default: bybit)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Symbols to monitor (default: BTCUSDT ETHUSDT)"
    )
    parser.add_argument(
        "--profile",
        default="moderate",
        choices=["moderate", "aggressive"],
        help="Trading profile (default: moderate)"
    )
    parser.add_argument(
        "--source",
        default="mock",
        choices=["mock", "ws", "redis"],
        help="Data source: mock (synthetic), ws (WebSocket), redis (Redis Streams) (default: mock)"
    )
    parser.add_argument(
        "--output",
        default="artifacts/shadow/latest",
        help="Output directory (default: artifacts/shadow/latest)"
    )
    
    # Redis-specific arguments
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379",
        help="Redis connection URL (default: redis://localhost:6379)"
    )
    parser.add_argument(
        "--redis-stream",
        default="lob:ticks",
        help="Redis stream name (default: lob:ticks)"
    )
    parser.add_argument(
        "--redis-group",
        default="shadow",
        help="Redis consumer group name (default: shadow)"
    )
    parser.add_argument(
        "--redis-consumer-id",
        default=None,
        help="Redis consumer ID (default: auto-generated)"
    )
    parser.add_argument(
        "--min_lot",
        type=float,
        default=0.0,
        help="Minimum lot size for volume check (default: 0.0, disabled)"
    )
    parser.add_argument(
        "--touch_dwell_ms",
        type=float,
        default=25.0,
        help="Minimum dwell time at touch price in ms (default: 25.0)"
    )
    parser.add_argument(
        "--require_volume",
        action="store_true",
        help="Require last_qty >= min_lot for fills (default: False)"
    )
    
    # Redis export arguments
    parser.add_argument(
        "--redis-export",
        action="store_true",
        help="Enable Redis KPI export after each iteration (default: False)"
    )
    parser.add_argument(
        "--redis-export-url",
        default="redis://localhost:6379",
        help="Redis connection URL for export (default: redis://localhost:6379)"
    )
    
    # Back-compat: deprecated flag (no-op)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="(deprecated) no-op; use --source mock instead"
    )
    
    args = parser.parse_args()
    
    # Load per-symbol profile (for first symbol, CLI overrides profile)
    symbol_profile = load_symbol_profile(args.symbols[0]) if args.symbols else {}
    
    # Apply profile defaults (CLI args have priority)
    # If CLI arg is still at default value, use profile value
    min_lot = args.min_lot
    touch_dwell_ms = args.touch_dwell_ms
    
    # Apply profile if CLI args are at default
    if args.min_lot == 0.0 and "min_lot" in symbol_profile:
        min_lot = symbol_profile["min_lot"]
        print(f"[PROFILE] Using min_lot={min_lot} from profile for {args.symbols[0]}")
    
    if args.touch_dwell_ms == 25.0 and "touch_dwell_ms" in symbol_profile:
        touch_dwell_ms = symbol_profile["touch_dwell_ms"]
        print(f"[PROFILE] Using touch_dwell_ms={touch_dwell_ms} from profile for {args.symbols[0]}")
    
    # Create simulator with resolved parameters
    simulator = ShadowSimulator(
        exchange=args.exchange,
        symbols=args.symbols,
        profile=args.profile,
        source=args.source,
        min_lot=min_lot,
        touch_dwell_ms=touch_dwell_ms,
        require_volume=args.require_volume,
        # Redis parameters
        redis_url=args.redis_url,
        redis_stream=args.redis_stream,
        redis_group=args.redis_group,
        redis_consumer_id=args.redis_consumer_id,
    )
    
    # Run shadow mode
    asyncio.run(simulator.run(
        args.iterations,
        args.duration,
        args.output,
        redis_export_enabled=args.redis_export,
        redis_export_url=args.redis_export_url
    ))


if __name__ == "__main__":
    main()

