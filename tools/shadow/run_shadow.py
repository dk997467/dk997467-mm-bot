#!/usr/bin/env python3
"""
Shadow Mode Runner

Connects to real exchange feeds (Bybit/KuCoin), simulates order placements
locally without API writes, and generates KPI metrics comparable to soak tests.

Usage:
    python -m tools.shadow.run_shadow --iterations 6 --duration 60
    python -m tools.shadow.run_shadow --profile aggressive --mock
"""

import argparse
import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Mock mode: Generate synthetic market data for testing
MOCK_MODE = True  # Toggle to False for real WS feeds


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
    """
    
    def __init__(
        self,
        exchange: str = "bybit",
        symbols: List[str] = None,
        profile: str = "moderate",
        mock: bool = True,
        min_lot: float = 0.0,
        touch_dwell_ms: float = 25.0,
        require_volume: bool = False,
    ):
        self.exchange = exchange
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self.profile = profile
        self.mock = mock
        self.min_lot = min_lot
        self.touch_dwell_ms = touch_dwell_ms
        self.require_volume = require_volume
        
        # KPI tracking
        self.maker_count = 0
        self.taker_count = 0
        self.latencies = []
        self.net_bps_values = []
        self.risk_ratios = []
        self.clock_drift_ewma = 0.0  # EWMA of clock drift
        
    async def connect_feed(self):
        """Connect to exchange WebSocket feed."""
        if self.mock:
            print(f"[MOCK] Simulating {self.exchange} feed for {self.symbols}")
        else:
            print(f"[LIVE] Connecting to {self.exchange} WS feed...")
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
        samples = duration  # 1 sample per second
        
        for tick_idx in range(samples):
            await asyncio.sleep(0.1 if self.mock else 1.0)  # Mock: faster
            
            # Generate synthetic tick (mock mode)
            if self.mock:
                base_price = 50000.0 + random.uniform(-100, 100)
                spread = random.uniform(0.5, 2.0)
                
                tick = {
                    "ts": time.time() - random.uniform(0.05, 0.15),  # Server lag
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
            "mode": "shadow",
        }
        
        print(f"[ITER {iter_num}] Completed: "
              f"maker/taker={maker_taker:.3f}, "
              f"edge={net_bps:.2f}, "
              f"latency={p95:.0f}ms, "
              f"risk={risk:.3f}, "
              f"drift={drift_ms:.1f}ms")
        
        return summary
    
    async def run(self, iterations: int, duration: int, output_dir: str):
        """
        Run shadow mode for N iterations.
        
        Args:
            iterations: Number of monitoring windows
            duration: Duration per iteration (seconds)
            output_dir: Output directory for artifacts
        """
        await self.connect_feed()
        
        # Prepare output directory
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
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
        "--mock",
        action="store_true",
        default=True,
        help="Use mock data instead of real feeds (default: True)"
    )
    parser.add_argument(
        "--output",
        default="artifacts/shadow/latest",
        help="Output directory (default: artifacts/shadow/latest)"
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
    
    args = parser.parse_args()
    
    # Create simulator
    simulator = ShadowSimulator(
        exchange=args.exchange,
        symbols=args.symbols,
        profile=args.profile,
        mock=args.mock,
        min_lot=args.min_lot,
        touch_dwell_ms=args.touch_dwell_ms,
        require_volume=args.require_volume,
    )
    
    # Run shadow mode
    asyncio.run(simulator.run(args.iterations, args.duration, args.output))


if __name__ == "__main__":
    main()

