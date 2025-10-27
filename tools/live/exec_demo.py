"""
CLI Demo for Shadow Execution Engine.

Pure stdlib implementation for demonstration and testing.
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from tools.live.exchange import FakeExchangeClient
from tools.live.exchange_bybit import BybitRestClient
from tools.live.execution_loop import ExecutionLoop, ExecutionParams
from tools.live.order_store import InMemoryOrderStore
from tools.live.order_store_durable import DurableOrderStore
from tools.live.risk_monitor import RuntimeRiskMonitor
from tools.live.secrets import SecretProvider
from tools.obs import health_server, metrics
from tools.state.redis_client import RedisKV


def main(argv: list[str] | None = None) -> int:
    """Main entry point for shadow execution demo."""
    parser = argparse.ArgumentParser(
        description="Shadow Execution Engine Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--shadow",
        action="store_true",
        help="Enable shadow mode (required flag)",
    )

    parser.add_argument(
        "--exchange",
        type=str,
        choices=["fake", "bybit"],
        default="fake",
        help="Exchange client to use (default: fake)",
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["shadow", "dryrun"],
        default="shadow",
        help="Trading mode (default: shadow)",
    )

    parser.add_argument(
        "--network",
        action="store_true",
        help="Enable network calls (default: False)",
    )

    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use testnet mode (safe endpoints only, default: False)",
    )

    parser.add_argument(
        "--api-env",
        type=str,
        choices=["dev", "shadow", "soak", "prod"],
        default="dev",
        help="API environment for SecretProvider (default: dev)",
    )
    
    parser.add_argument(
        "--maker-only",
        action="store_true",
        default=True,
        help="Enable maker-only mode (post-only orders, default: True)",
    )
    
    parser.add_argument(
        "--no-maker-only",
        dest="maker_only",
        action="store_false",
        help="Disable maker-only mode",
    )
    
    parser.add_argument(
        "--post-only-offset-bps",
        type=float,
        default=1.5,
        help="Post-only price offset in basis points (default: 1.5)",
    )
    
    parser.add_argument(
        "--min-qty-pad",
        type=float,
        default=1.1,
        help="Minimum quantity padding multiplier (default: 1.1)",
    )
    
    parser.add_argument(
        "--symbol-filter",
        type=str,
        default=None,
        help="Comma-separated list of symbols to trade (overrides --symbols)",
    )
    
    # P0.10: Live mode and reconciliation flags
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live mode (alias for --network without --testnet). Requires MM_LIVE_ENABLE=1.",
    )
    
    parser.add_argument(
        "--recon-interval-s",
        type=int,
        default=60,
        help="Reconciliation interval in seconds (default: 60)",
    )
    
    parser.add_argument(
        "--fee-maker-bps",
        type=float,
        default=1.0,
        help="Maker fee in basis points (default: 1.0)",
    )
    
    parser.add_argument(
        "--fee-taker-bps",
        type=float,
        default=7.0,
        help="Taker fee in basis points (default: 7.0)",
    )
    
    parser.add_argument(
        "--rebate-maker-bps",
        type=float,
        default=2.0,
        help="Maker rebate in basis points (default: 2.0, positive = income)",
    )
    
    parser.add_argument(
        "--warmup-filters",
        action="store_true",
        help="Warm up symbol filters cache on startup (requires --network)",
    )

    parser.add_argument(
        "--no-warmup-filters",
        action="store_true",
        help="Explicitly disable auto-warmup (overrides default for testnet/live)",
    )

    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated list of symbols (default: BTCUSDT,ETHUSDT)",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of iterations (default: 50)",
    )

    parser.add_argument(
        "--max-inv",
        type=float,
        default=10000.0,
        help="Max inventory USD per symbol (default: 10000)",
    )

    parser.add_argument(
        "--max-total",
        type=float,
        default=50000.0,
        help="Max total notional USD (default: 50000)",
    )

    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=1.5,
        help="Edge freeze threshold in BPS (default: 1.5)",
    )

    parser.add_argument(
        "--fill-rate",
        type=float,
        default=0.7,
        help="Fill rate probability 0.0-1.0 (default: 0.7)",
    )

    parser.add_argument(
        "--reject-rate",
        type=float,
        default=0.05,
        help="Reject rate probability 0.0-1.0 (default: 0.05)",
    )

    parser.add_argument(
        "--latency-ms",
        type=int,
        default=100,
        help="Simulated latency in ms (default: 100)",
    )

    parser.add_argument(
        "--durable-state",
        action="store_true",
        help="Enable durable state persistence (Redis + disk snapshot)",
    )

    parser.add_argument(
        "--state-dir",
        type=str,
        default="artifacts/state",
        help="Directory for state snapshots (default: artifacts/state)",
    )

    parser.add_argument(
        "--recover",
        action="store_true",
        help="Recover from previous snapshot on startup",
    )

    parser.add_argument(
        "--obs",
        action="store_true",
        help="Enable observability server (health/ready/metrics endpoints)",
    )

    parser.add_argument(
        "--obs-host",
        type=str,
        default="127.0.0.1",
        help="Observability server bind host (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--obs-port",
        type=int,
        default=8080,
        help="Observability server port (default: 8080)",
    )

    args = parser.parse_args(argv)

    # P0.11: Auto-warmup default for testnet/live network modes
    if args.network and args.api_env in {"testnet", "live"}:
        if not args.no_warmup_filters and not args.warmup_filters:
            args.warmup_filters = True
            print("[INFO] Auto-enabling --warmup-filters for testnet/live network mode", file=sys.stderr)

    if not args.shadow:
        print("Error: --shadow flag is required", file=sys.stderr)
        return 1

    # Parse symbols (use --symbol-filter if provided, otherwise --symbols)
    symbol_list = args.symbol_filter if args.symbol_filter else args.symbols
    symbols = [s.strip() for s in symbol_list.split(",") if s.strip()]
    if not symbols:
        print("Error: At least one symbol is required", file=sys.stderr)
        return 1
    
    # P0.10: Handle --live flag (sets network_enabled=True, testnet=False)
    if args.live:
        args.network = True
        args.testnet = False
        print("[INFO] Live mode enabled (--live implies --network without --testnet)", file=sys.stderr)
        print("[INFO] Kill-switch requires MM_LIVE_ENABLE=1 environment variable", file=sys.stderr)

    # Run shadow demo
    try:
        # Create exchange client based on --exchange flag
        if args.exchange == "fake":
            exchange = FakeExchangeClient(
                fill_rate=args.fill_rate,
                reject_rate=args.reject_rate,
                latency_ms=args.latency_ms,
                seed=42,
            )
        elif args.exchange == "bybit":
            # Create SecretProvider with InMemorySecretStore
            from tools.live.secrets import InMemorySecretStore
            secret_provider = SecretProvider(store=InMemorySecretStore())
            
            exchange = BybitRestClient(
                secret_provider=secret_provider,
                api_env=args.api_env,
                network_enabled=args.network,
                testnet=args.testnet,
                fill_rate=args.fill_rate,
                fill_latency_ms=args.latency_ms,
                seed=42,
            )
        else:
            print(f"Error: Unsupported exchange: {args.exchange}", file=sys.stderr)
            return 1

        # Create components
        if args.durable_state:
            # Use DurableOrderStore with Redis (in-memory fake)
            redis_client = RedisKV()
            state_dir = Path(args.state_dir)
            state_dir.mkdir(parents=True, exist_ok=True)
            
            order_store = DurableOrderStore(
                redis_client=redis_client,
                snapshot_dir=state_dir,
            )
        else:
            # Use InMemoryOrderStore (default)
            order_store = InMemoryOrderStore()
        
        risk_monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=args.max_inv,
            max_total_notional_usd=args.max_total,
            edge_freeze_threshold_bps=args.edge_threshold,
        )
        
        # P0.10: Create fee schedule
        from decimal import Decimal
        from tools.live import fees as fees_module
        
        fee_schedule = fees_module.FeeSchedule(
            maker_bps=Decimal(str(args.fee_maker_bps)),
            taker_bps=Decimal(str(args.fee_taker_bps)),
            maker_rebate_bps=Decimal(str(args.rebate_maker_bps)),
        )

        # Create execution loop
        loop = ExecutionLoop(
            exchange=exchange,
            order_store=order_store,
            risk_monitor=risk_monitor,
            enable_idempotency=args.durable_state,
            network_enabled=args.network,
            testnet=args.testnet,
            maker_only=args.maker_only,
            post_only_offset_bps=args.post_only_offset_bps,
            min_qty_pad=args.min_qty_pad,
            recon_interval_s=args.recon_interval_s,
            fee_schedule=fee_schedule,
        )
        
        # P0.10: Warm up symbol filters cache if requested
        warmup_filters_enabled = False
        if args.warmup_filters:
            if not args.network:
                print("[WARN] --warmup-filters requires --network, skipping warmup", file=sys.stderr)
            else:
                print("[INFO] Warming up symbol filters cache...", file=sys.stderr)
                for symbol in symbols:
                    try:
                        # Access filters via cache, forcing a fetch if not cached
                        filters = loop._symbol_filters_cache.get(
                            symbol,
                            lambda: exchange.get_symbol_filters(symbol)
                        )
                        print(f"[INFO] Warmed up filters for {symbol}: "
                              f"tickSize={filters.tick_size}, stepSize={filters.step_size}, "
                              f"minQty={filters.min_qty}", file=sys.stderr)
                    except Exception as e:
                        print(f"[WARN] Failed to warm up filters for {symbol}: {e}", file=sys.stderr)
                
                warmup_filters_enabled = True
                print("[INFO] Symbol filters cache warm-up complete", file=sys.stderr)
        
        # Recover from snapshot if requested
        if args.recover and args.durable_state:
            recovery_report = loop.recover_from_restart()
            # Log recovery to stderr (not included in JSON output)
            print(f"[RECOVERY] {recovery_report}", file=sys.stderr)
        
        # Start observability server if requested
        obs_server = None
        if args.obs:
            # Define readiness providers based on components
            class MMHealthProviders:
                """Health providers for MM-Bot."""
                def __init__(self, risk_mon, exch):
                    self.risk_mon = risk_mon
                    self.exch = exch
                
                def state_ready(self) -> bool:
                    """State is always ready (in-memory or Redis fake)."""
                    return True
                
                def risk_ready(self) -> bool:
                    """Risk is ready if not frozen."""
                    return not self.risk_mon.is_frozen()
                
                def exchange_ready(self) -> bool:
                    """Exchange is always ready (fake or dry-run)."""
                    return True
            
            providers = MMHealthProviders(risk_monitor, exchange)
            obs_server = health_server.start_server(
                host=args.obs_host,
                port=args.obs_port,
                providers=providers,
                metrics_renderer=metrics.render_prometheus,
            )
            print(f"[OBS] Server started: http://{args.obs_host}:{args.obs_port}", file=sys.stderr)
            print(f"[OBS] Endpoints: /health /ready /metrics", file=sys.stderr)

        # Run simulation
        params = ExecutionParams(
            symbols=symbols,
            iterations=args.iterations,
            max_inventory_usd_per_symbol=args.max_inv,
            max_total_notional_usd=args.max_total,
            edge_freeze_threshold_bps=args.edge_threshold,
        )

        report = loop.run_shadow(params)
        
        # P0.10: Add warmup_filters to report if enabled
        if warmup_filters_enabled:
            if "execution" not in report:
                report["execution"] = {}
            report["execution"]["warmup_filters"] = True
        
        # Save snapshot if durable state enabled
        if args.durable_state and hasattr(order_store, "save_snapshot"):
            order_store.save_snapshot()
            print("[SNAPSHOT] Saved to disk", file=sys.stderr)

        # Output deterministic JSON
        report_json = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
        sys.stdout.write(report_json)
        
        # Stop observability server if running
        if obs_server is not None:
            obs_server.stop()
            print("[OBS] Server stopped", file=sys.stderr)
        
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

