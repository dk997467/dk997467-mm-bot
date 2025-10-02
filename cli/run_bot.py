#!/usr/bin/env python3
"""
Market Maker Bot CLI entry point.

Enhanced with:
- AppConfig/AppContext integration
- Hot reload support
- Enhanced health endpoints
- Metrics integration
"""

import argparse
import asyncio
import json
import signal
import sys
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import is_dataclass, asdict
import hmac
from collections import deque

from aiohttp import web

from src.common.config import ConfigLoader, cfg_hash_sanitized, get_git_sha
from src.common.di import AppContext
from src.common.models import Order, QuoteRequest
from src.common.logging import RateLimitedLogger
from src.connectors.bybit_rest import BybitRESTConnector
from src.connectors.bybit_websocket import BybitWebSocketConnector
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.storage.recorder import Recorder
from src.strategy.market_making import MarketMakingStrategy
from src.strategy.orderbook_aggregator import OrderBookAggregator
from src.metrics.exporter import MetricsExporter
from src.portfolio.allocator import PortfolioAllocator
from src.marketdata.vola import VolatilityManager
from src.scheduler.tod import TimeOfDayScheduler
from src.guards.autopolicy import AutoPolicy
from src.guards.circuit import CircuitBreaker
from src.guards.runtime import RuntimeGuard
from src.guards.throttle import ThrottleGuard
from src.common.config import RuntimeGuardConfig, ThrottleConfig
from src.deploy import thresholds as th


class NullConnector:
    """Null connector for dry-run mode."""
    
    def __init__(self):
        self.connected = True
    
    def is_connected(self):
        return self.connected
    
    def get_connection_status(self):
        return {"public": True, "private": True}
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MarketMakerBot:
    """Enhanced Market Maker Bot with AppConfig integration."""
    
    def __init__(self, config_path: str, recorder: Recorder, dry_run: bool = False, profile: Optional[str] = None):
        """Initialize the bot."""
        self.config_path = config_path
        self.data_recorder = recorder
        self.dry_run = dry_run
        self.profile = profile
        self.paper_mode = False
        
        # Core components
        self.config = None
        self.ctx = None
        self.metrics = None
        self.metrics_exporter = None
        self.order_manager = None
        self.risk_manager = None
        self.strategy = None
        self.orderbook_aggregator = None
        
        # Connectors
        self.ws_connector = None
        self.rest_connector = None
        
        # Web server
        self.web_app = None
        self.web_runner = None
        
        # State
        self.running = False
        self.start_time = None

        # Admin audit & rate-limit
        self._admin_audit_log = deque(maxlen=1000)
        self._admin_rl_window_sec = 60
        self._admin_rl_limit = 60
        self._admin_rl_counters = {}  # (actor, endpoint) -> deque[timestamps]
        # Admin auth (dual token)
        self._admin_token_primary = os.getenv('ADMIN_TOKEN_PRIMARY') or os.getenv('ADMIN_TOKEN') or ''
        self._admin_token_secondary = os.getenv('ADMIN_TOKEN_SECONDARY') or ''
        self._admin_active_token = 'primary'
        import threading as _th
        self._admin_token_lock = _th.Lock()
        # Execution recorder state
        self._exec_recorder_enabled = bool(os.getenv('EXEC_RECORDER_ENABLED', '0') == '1')
        self._exec_recorder_file = None
        self._exec_last_write_ts = 0.0

    # Safe init for admin audit/rate-limit when object is constructed via __new__ in tests
    def _ensure_admin_audit_initialized(self) -> None:
        try:
            if not hasattr(self, '_admin_audit_log') or self._admin_audit_log is None:
                self._admin_audit_log = deque(maxlen=1000)
            if not hasattr(self, '_admin_rl_window_sec') or not isinstance(self._admin_rl_window_sec, (int, float)):
                self._admin_rl_window_sec = 60
            if not hasattr(self, '_admin_rl_limit') or not isinstance(self._admin_rl_limit, (int, float)):
                self._admin_rl_limit = 60
            if not hasattr(self, '_admin_rl_counters') or self._admin_rl_counters is None:
                self._admin_rl_counters = {}
            # ensure admin tokens present (for __new__ constructed test instances)
            if not hasattr(self, '_admin_token_primary'):
                self._admin_token_primary = os.getenv('ADMIN_TOKEN_PRIMARY') or os.getenv('ADMIN_TOKEN') or ''
            if not hasattr(self, '_admin_token_secondary'):
                self._admin_token_secondary = os.getenv('ADMIN_TOKEN_SECONDARY') or ''
            if not hasattr(self, '_admin_active_token'):
                self._admin_active_token = 'primary'
            if not hasattr(self, '_admin_token_lock') or self._admin_token_lock is None:
                import threading as _th
                self._admin_token_lock = _th.Lock()
        except Exception:
            pass
        
        # Logging
        if not hasattr(self, 'logger') or self.logger is None:
            self.logger = RateLimitedLogger()
        
        # Background tasks
        if not hasattr(self, '_rebalance_task'):
            self._rebalance_task = None
        if not hasattr(self, '_scheduler_watcher_task'):
            self._scheduler_watcher_task = None
        if not hasattr(self, '_rollout_state_task'):
            self._rollout_state_task = None
        if not hasattr(self, '_last_portfolio_hash'):
            self._last_portfolio_hash = None
        if not hasattr(self, '_last_scheduler_hash'):
            self._last_scheduler_hash = None
        if not hasattr(self, '_prev_scheduler_open'):
            self._prev_scheduler_open = None
        # Allocator snapshot settings
        if not hasattr(self, '_allocator_snapshot_path'):
            self._allocator_snapshot_path = None
        if not hasattr(self, '_allocator_snapshot_interval'):
            self._allocator_snapshot_interval = 60
        if not hasattr(self, '_allocator_jitter_frac'):
            self._allocator_jitter_frac = 0.10
        if not hasattr(self, '_allocator_last_immediate_save_ts'):
            self._allocator_last_immediate_save_ts = 0.0
        if not hasattr(self, '_build_time_iso') or not isinstance(self._build_time_iso, str) or not self._build_time_iso:
            self._build_time_iso = datetime.now(timezone.utc).isoformat()
        if not hasattr(self, '_params_hash') or not isinstance(self._params_hash, str) or not self._params_hash:
            self._params_hash = "unknown"
        # Throttle snapshot settings
        self._throttle_snapshot_path = "artifacts/throttle_snapshot.json"
        self._throttle_snapshot_interval = 30
        self._throttle_jitter_frac = 0.10
        self._throttle_last_immediate_save_ts = 0.0
        # Rollout ramp state
        self._ramp_last_counters = {"fills": {"blue": 0, "green": 0}, "rejects": {"blue": 0, "green": 0}}
        self._ramp_last_check_ts = 0.0
        self._ramp_step_idx = 0
        self._ramp_state = {"enabled": False, "step_idx": 0, "last": {"fills": {"blue": 0, "green": 0}, "rejects": {"blue": 0, "green": 0}}, "updated_ts": 0.0, "frozen": False, "consecutive_stable_steps": 0}
        self._ramp_snapshot_path = "artifacts/rollout_ramp.json"
        self._ramp_snapshot_interval = 60
        self._ramp_jitter_frac = 0.10
        self._ramp_last_write_ts = 0.0
        self._ramp_last_load_ts = 0.0
        # Rollout state snapshot settings
        self._rollout_state_snapshot_path = "artifacts/rollout_state.json"
        self._rollout_state_snapshot_interval = 60
        self._rollout_state_jitter_frac = 0.10
        self._rollout_state_last_write_ts = 0.0
        self._rollout_state_last_load_ts = 0.0
        self._rollout_state_dirty = False
        # Alerts (lazy: prefer dynamic via _alerts_log_file)
        self._alerts_log_path = None
        # Prune
        self._prune_task = None
    
    async def initialize(self):
        """Initialize all bot components."""
        try:
            print("Initializing Market Maker Bot...")
            
            # Load YAML -> validate via Pydantic Settings -> build AppConfig
            try:
                import yaml as _yaml
                from pydantic import ValidationError as _PydanticValidationError
                from src.config_models import Settings as _Settings

                with open(self.config_path, 'r', encoding='utf-8') as _f:
                    _yaml_data = _yaml.safe_load(_f) or {}

                _validated_config = _Settings(**_yaml_data)
                setattr(self, "_validated_settings", _validated_config)
            except FileNotFoundError as _e:
                print(f"[CRITICAL] config file not found: {self.config_path} :: {_e}")
                raise SystemExit(1)
            except _PydanticValidationError as _e:
                print(f"[CRITICAL] invalid configuration: {_e}")
                raise SystemExit(1)
            except Exception as _e:
                print(f"[CRITICAL] failed to load/validate config: {_e}")
                raise SystemExit(1)

            # Use legacy converter to AppConfig to keep rest of the app intact
            loader = ConfigLoader(self.config_path)
            self.config = loader.load()
            self.ctx = AppContext(cfg=self.config)
            # Setup execution recorder file name
            try:
                if self._exec_recorder_enabled:
                    from datetime import datetime, timezone
                    date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
                    self._exec_recorder_file = f"artifacts/exe_{date_str}.jsonl"
            except Exception:
                self._exec_recorder_file = None
            
            # Startup logging snapshot
            print(json.dumps({
                "git_sha": get_git_sha(),
                "config_version": self.config.config_version,
                "cfg_hash": cfg_hash_sanitized(self.config),
                "cfg_snapshot": self.config.to_sanitized(),
            }))
            print(f"Configuration loaded: {len(self.config.trading.symbols)} symbols")
            # Load rollout state if present
            try:
                sp = self._rollout_state_snapshot_path or "artifacts/rollout_state.json"
                from pathlib import Path as _P
                if _P(sp).exists() and _P(sp).is_file():
                    if _P(sp).stat().st_size <= 1024*1024:
                        with open(sp, 'r', encoding='utf-8') as f:
                            st = json.load(f)
                        if isinstance(st, dict) and int(st.get('version', 1)) >= 1:
                            ro = getattr(self.config, 'rollout', None)
                            if ro is not None:
                                    # apply traffic split/active/salt/pins
                                    try:
                                        v = int(max(0, min(100, int(st.get('traffic_split_pct', ro.traffic_split_pct)))))
                                        ro.traffic_split_pct = v
                                    except Exception:
                                        pass
                                    try:
                                        a = str(st.get('active', ro.active)).lower()
                                        if a in ('blue','green'):
                                            ro.active = a
                                    except Exception:
                                        pass
                                    try:
                                        s = str(st.get('salt', ro.salt))
                                        if len(s) <= 64:
                                            ro.salt = s
                                    except Exception:
                                        pass
                                    try:
                                        pins = st.get('pinned_cids_green', ro.pinned_cids_green)
                                        if isinstance(pins, str):
                                            pins = [p.strip() for p in pins.split(',') if p.strip()]
                                        if isinstance(pins, list):
                                            pins = [str(p).strip() for p in pins if str(p).strip()]
                                            ro.pinned_cids_green = pins[:10000]
                                    except Exception:
                                        pass
                                    # ramp
                                    try:
                                        rv = st.get('ramp', {})
                                        rr = getattr(self.config, 'rollout_ramp', None)
                                        if rr is not None and isinstance(rv, dict):
                                            if 'enabled' in rv:
                                                rr.enabled = bool(rv['enabled'])
                                            if 'steps_pct' in rv and isinstance(rv['steps_pct'], list):
                                                steps = sorted(max(0, min(100, int(x))) for x in rv['steps_pct'])
                                                rr.steps_pct = steps
                                            if 'step_interval_sec' in rv:
                                                rr.step_interval_sec = int(max(10, int(rv['step_interval_sec'])))
                                            if 'max_reject_rate_delta_pct' in rv:
                                                rr.max_reject_rate_delta_pct = float(max(0.0, float(rv['max_reject_rate_delta_pct'])))
                                            if 'max_latency_delta_ms' in rv:
                                                rr.max_latency_delta_ms = int(max(0, int(rv['max_latency_delta_ms'])))
                                            if 'max_pnl_delta_usd' in rv:
                                                rr.max_pnl_delta_usd = float(rv['max_pnl_delta_usd'])
                                    except Exception:
                                        pass
                                    # metrics
                                    if getattr(self, 'metrics', None):
                                        try:
                                            self.metrics.set_rollout_split_pct(int(ro.traffic_split_pct))
                                            self.metrics.set_ramp_enabled(bool(getattr(self.config, 'rollout_ramp', None) and self.config.rollout_ramp.enabled))
                                            self.metrics.set_ramp_step_idx(int(getattr(self, '_ramp_step_idx', 0)))
                                        except Exception:
                                            pass
                                    if getattr(self, 'metrics', None):
                                        try:
                                            import time as _t
                                            self.metrics.inc_rollout_state_snapshot_load(ok=True, ts=_t.time())
                                            self._rollout_state_last_load_ts = _t.time()
                                        except Exception:
                                            pass
            except Exception:
                try:
                    import time as _t
                    if getattr(self, 'metrics', None):
                        self.metrics.inc_rollout_state_snapshot_load(ok=False, ts=_t.time())
                except Exception:
                    pass
            
            # Apply profile override if provided
            if self.profile:
                if self.profile.lower() == "testnet":
                    self.config.bybit.use_testnet = True
                elif self.profile.lower() == "mainnet":
                    self.config.bybit.use_testnet = False
            
            print(f"Using {'TESTNET' if self.config.bybit.use_testnet else 'MAINNET'}")
            print(f"Storage backend: {self.config.storage.backend}")

            # Initialize data recorder (if not provided externally)
            if self.data_recorder is None:
                self.data_recorder = Recorder(self.config)
                self._owns_recorder = True
                print("Data recorder initialized")
            
            # Initialize REST connector (skip in dry-run)
            if not self.dry_run:
                self.rest_connector = BybitRESTConnector(self.ctx, self.config)
                await self.rest_connector.__aenter__()
                print("REST connector initialized")
            else:
                self.rest_connector = NullConnector()
                print("Using null REST connector for dry-run")
            
            # Initialize orderbook aggregator
            self.orderbook_aggregator = OrderBookAggregator(self.data_recorder)
            for symbol in self.config.trading.symbols:
                self.orderbook_aggregator.add_symbol(symbol)
            print("Orderbook aggregator initialized")
            
            # Initialize order manager
            self.order_manager = OrderManager(self.ctx, self.rest_connector)
            # Wire into context for allocator active USD estimation
            self.ctx.order_manager = self.order_manager
            print("Order manager initialized")
            
            # Initialize risk manager
            self.risk_manager = RiskManager(self.config, self.data_recorder)
            print("Risk manager initialized")
            
            # Initialize strategy
            self.strategy = MarketMakingStrategy(self.config, self.data_recorder, metrics_exporter=None, ctx=self.ctx)
            print("Strategy initialized")
            
            # Initialize metrics exporter
            self.metrics_exporter = MetricsExporter(self.config, self.data_recorder)
            
            # Create Metrics instance with AppContext
            from src.metrics.exporter import Metrics
            self.metrics = Metrics(self.ctx)
            # Wire metrics into context
            self.ctx.metrics = self.metrics
            
            # Initialize portfolio components
            try:
                self.ctx.vola_manager = VolatilityManager(alpha=self.config.portfolio.ema_alpha)
                if self.metrics:
                    self.ctx.vola_manager.set_metrics(self.metrics)
            except Exception:
                # Fallback with defaults if portfolio config missing
                self.ctx.vola_manager = VolatilityManager()
                if self.metrics:
                    self.ctx.vola_manager.set_metrics(self.metrics)
            
            self.ctx.allocator = PortfolioAllocator(self.ctx)
            if self.metrics:
                self.ctx.allocator.set_metrics(self.metrics)
            # Try load allocator HWM snapshot
            try:
                import os, json as _json, time as _time
                sp = getattr(getattr(self.config.portfolio, 'budget', None), 'snapshot_path', None)
                # Allow CLI override later
                if sp is None:
                    sp = getattr(self.config.portfolio, 'snapshot_path', None)
                self._allocator_snapshot_path = sp or "artifacts/allocator_hwm.json"
                if os.path.exists(self._allocator_snapshot_path):
                    # use safe method from allocator
                    try:
                        self.ctx.allocator.safe_load_snapshot(self._allocator_snapshot_path)
                    except Exception:
                        pass
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_allocator_snapshot_load(ok=True, ts=_time.time())
                        except Exception:
                            pass
            except Exception:
                try:
                    if getattr(self, 'metrics', None):
                        import time as _t
                        self.metrics.inc_allocator_snapshot_load(ok=False, ts=_t.time())
                except Exception:
                    pass
            
            # Initialize scheduler (optional; supports per-symbol overrides)
            try:
                sched_cfg = getattr(self.config, 'scheduler', None)
                if sched_cfg:
                    stz = getattr(sched_cfg, 'tz', 'UTC') or 'UTC'
                    co = float(getattr(sched_cfg, 'cooldown_open_minutes', 0.0) or 0.0)
                    cc = float(getattr(sched_cfg, 'cooldown_close_minutes', 0.0) or 0.0)
                    bi = bool(getattr(sched_cfg, 'block_in_cooldown', True))
                    wins_by_sym = getattr(sched_cfg, 'windows_by_symbol', {}) or {}
                    if wins_by_sym:
                        self.ctx.schedulers = {}
                        for sym, wins in wins_by_sym.items():
                            self.ctx.schedulers[str(sym)] = TimeOfDayScheduler(list(wins or []), tz=stz, cooldown_open_minutes=co, cooldown_close_minutes=cc, block_in_cooldown=bi)
                        # apply holidays to each
                        try:
                            for h in getattr(sched_cfg, 'holidays', []) or []:
                                dates = list(getattr(h, 'dates', []) or [])
                                targets = list(getattr(h, 'symbols', []) or [])
                                target_syms = targets or list(self.ctx.schedulers.keys())
                                for s in target_syms:
                                    if s in self.ctx.schedulers:
                                        self.ctx.schedulers[s].set_holidays(dates)
                        except Exception:
                            pass
                    else:
                        self.ctx.scheduler = TimeOfDayScheduler(
                            list(getattr(sched_cfg, 'windows', []) or []),
                            tz=stz,
                            cooldown_open_minutes=co,
                            cooldown_close_minutes=cc,
                            block_in_cooldown=bi
                        )
                        # apply global holidays
                        try:
                            for h in getattr(sched_cfg, 'holidays', []) or []:
                                dates = list(getattr(h, 'dates', []) or [])
                                if getattr(self.ctx, 'scheduler', None):
                                    self.ctx.scheduler.set_holidays(dates)
                        except Exception:
                            pass
            except Exception:
                pass

            # Initialize runtime guard
            try:
                rg_cfg = getattr(self.config, 'runtime_guard', None) or RuntimeGuardConfig()
                self.ctx.guard = RuntimeGuard(rg_cfg)
                self._last_guard_hash = None
                self._last_guard_pauses_total = 0
                
                # Initialize throttle guard
                th_cfg = getattr(self.config, 'throttle', None) or ThrottleConfig()
                self.ctx.throttle = ThrottleGuard(th_cfg)
                self._last_throttle_hash = None
                # Load throttle snapshot if exists (safe, 1MB limit)
                try:
                    from pathlib import Path as _P
                    p = _P(self._throttle_snapshot_path)
                    if p.exists():
                        import json as _json
                        data = {}
                        try:
                            if p.stat().st_size <= 1024 * 1024:
                                with open(p, 'r', encoding='utf-8') as f:
                                    data = _json.load(f)
                        except Exception:
                            data = {}
                        if data:
                            try:
                                self.ctx.throttle.load_snapshot(data)
                                if getattr(self, 'metrics', None):
                                    import time as _t
                                    self.metrics.inc_throttle_snapshot_load(ok=True, ts=_t.time())
                            except Exception:
                                if getattr(self, 'metrics', None):
                                    import time as _t
                                    self.metrics.inc_throttle_snapshot_load(ok=False, ts=_t.time())
                except Exception:
                    pass
            except Exception:
                pass

            # Initialize AutoPolicy
            try:
                self.ctx.autopolicy = AutoPolicy(self.config.autopolicy)
                base_min_tib = float(getattr(self.config.strategy, 'min_time_in_book_ms', 0.0))
                base_rep = float(getattr(self.config.strategy, 'replace_threshold_bps', 0.0))
                base_levels = int(getattr(self.config.portfolio, 'levels_per_side_max', 1))
                self.ctx.autopolicy.set_base(base_min_tib, base_rep, base_levels)
                try:
                    sp = self.config.autopolicy.snapshot_path
                    if sp and os.path.exists(sp):
                        import json as _json
                        data = _json.loads(open(sp, 'r', encoding='utf-8').read())
                        self.ctx.autopolicy.load_snapshot(data)
                except Exception:
                    pass
            except Exception:
                self.ctx.autopolicy = None

            # Initialize Circuit Breaker
            try:
                self.ctx.circuit = CircuitBreaker(self.config.circuit)
                self._last_circuit_hash = None
            except Exception:
                self.ctx.circuit = None

            # Sync open orders and load snapshot
            try:
                snap_path = "artifacts/runtime/orders_snapshot.json"
                try:
                    _ = self.order_manager.load_orders_snapshot(snap_path)
                except Exception:
                    pass
                await self.order_manager.sync_open_orders()
                # periodic snapshot saver
                async def _orders_snapshot_loop():
                    while self.running:
                        try:
                            self.order_manager.save_orders_snapshot(snap_path)
                        except Exception:
                            pass
                        await asyncio.sleep(30)
                asyncio.create_task(_orders_snapshot_loop())
            except Exception:
                pass

            # Scheduler state hash (include per-symbol windows and holidays)
            try:
                import hashlib
                sc = getattr(self.config, 'scheduler', None)
                if sc:
                    sw = list(getattr(sc, 'windows', []) or [])
                    sws = getattr(sc, 'windows_by_symbol', {}) or {}
                    hol = []
                    try:
                        for h in getattr(sc, 'holidays', []) or []:
                            hol.append({'dates': list(getattr(h, 'dates', []) or []), 'symbols': list(getattr(h, 'symbols', []) or [])})
                    except Exception:
                        hol = []
                    stz = getattr(sc, 'tz', 'UTC') or 'UTC'
                    co = float(getattr(sc, 'cooldown_open_minutes', 0.0) or 0.0)
                    cc = float(getattr(sc, 'cooldown_close_minutes', 0.0) or 0.0)
                    bi = bool(getattr(sc, 'block_in_cooldown', True))
                    _b = json.dumps({'windows': sw, 'windows_by_symbol': sws, 'holidays': hol, 'tz': stz, 'co': co, 'cc': cc, 'bi': bi}, sort_keys=True, separators=(",", ":")).encode('utf-8')
                    self._last_scheduler_hash = hashlib.sha1(_b).hexdigest()
                else:
                    self._last_scheduler_hash = None
            except Exception:
                self._last_scheduler_hash = None

            # Runtime guard hash
            try:
                import hashlib
                rg = getattr(self.config, 'runtime_guard', None) or RuntimeGuardConfig()
                # include per_symbol
                _gd = rg.__dict__ if hasattr(rg, '__dict__') else {}
                _b = json.dumps(_gd, sort_keys=True, separators=(",", ":")).encode('utf-8')
                self._last_guard_hash = hashlib.sha1(_b).hexdigest()
            except Exception:
                self._last_guard_hash = None

            # Initialize last portfolio hash (stdlib only)
            import hashlib
            _p = getattr(self.config, 'portfolio', None)
            _pd = _p.__dict__ if hasattr(_p, '__dict__') else {}
            def _sanitize(o):
                if is_dataclass(o):
                    return asdict(o)
                if isinstance(o, dict):
                    return {k: _sanitize(v) for k, v in o.items()}
                if isinstance(o, (list, tuple)):
                    return [_sanitize(x) for x in o]
                try:
                    json.dumps(o)
                    return o
                except Exception:
                    return str(o)
            _pd_s = _sanitize(_pd)
            _b = json.dumps(_pd_s, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self._last_portfolio_hash = hashlib.sha1(_b).hexdigest()
            
            # Export config gauges at startup
            try:
                self.metrics.export_cfg_gauges(self.config)
            except Exception:
                pass
            print("Metrics exporter initialized")
            # cache params hash for version endpoint
            try:
                self._params_hash = cfg_hash_sanitized(self.config)
            except Exception:
                self._params_hash = "unknown"
            
            # Initialize WebSocket connector (skip in dry-run)
            if not self.dry_run:
                self.ws_connector = BybitWebSocketConnector(
                    ctx=self.ctx,
                    config=self.config,
                    on_orderbook_update=self._on_orderbook_update,
                    on_trade_update=self._on_trade_update,
                    on_order_update=self._on_order_update,
                    on_execution_update=self._on_execution_update,
                    on_orderbook_delta=self._on_orderbook_delta
                )
                # If API keys are missing and profile is testnet → public only
                missing_keys = not self.config.bybit.api_key or self.config.bybit.api_key in ("", "dummy")
                if self.config.bybit.use_testnet and missing_keys:
                    async def _noop_private_runner():
                        return None
                    # Disable private websocket runner
                    self.ws_connector._run_private_websocket = _noop_private_runner  # type: ignore[attr-defined]
                print("WebSocket connector initialized")
            else:
                self.ws_connector = NullConnector()
                print("Using null WebSocket connector for dry-run")
            
            # Set up callbacks
            self._setup_callbacks()
            
            print("Bot initialization completed successfully")
            
        except Exception as e:
            print(f"Failed to initialize bot: {e}")
            raise
    
    def _get_artifacts_dir(self) -> str:
        try:
            d = os.getenv("ARTIFACTS_DIR", "artifacts")
            from pathlib import Path as _P
            _P(d).mkdir(parents=True, exist_ok=True)
            return d
        except Exception:
            return "artifacts"

    def _alerts_log_file(self) -> str:
        try:
            from pathlib import Path as _P
            p = os.path.join(self._get_artifacts_dir(), "alerts.log")
            _P(os.path.dirname(p)).mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            return "artifacts/alerts.log"

    def _setup_callbacks(self):
        """Set up strategy callbacks."""
        if self.strategy:
            self.strategy.set_order_callback(self._on_order_placed)
            self.strategy.set_quote_callback(self._on_quote_generated)
    
    async def start(self):
        """Start the bot."""
        try:
            self.running = True
            self.start_time = datetime.now(timezone.utc)
            
            # Start web server
            await self._start_web_server()
            
            # Start WebSocket connector
            if self.ws_connector and not isinstance(self.ws_connector, NullConnector):
                await self.ws_connector.start()
            
            # Start strategy
            if self.strategy:
                await self.strategy.start()
            
            print("Bot started successfully")
            
            # Start periodic portfolio rebalance loop
            if not self._rebalance_task:
                self._rebalance_task = asyncio.create_task(self._rebalance_loop())
            if not hasattr(self, '_background_tasks'):
                self._background_tasks = []
            # Start allocator snapshot loop
            async def _allocator_snapshot_loop():
                import time as _t, os as _os, json as _json
                while self.running:
                    try:
                        sp = self._allocator_snapshot_path or "artifacts/allocator_hwm.json"
                        tmp = sp + ".tmp"
                        # ensure dir exists
                        try:
                            from pathlib import Path as _P
                            _P(sp).parent.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        snap = self.ctx.allocator.to_snapshot() if getattr(self.ctx, 'allocator', None) else {"version":1,"hwm_equity_usd":0.0}
                        try:
                            self._atomic_snapshot_write(sp, snap, version=1)
                        except Exception:
                            payload = _json.dumps(snap, sort_keys=True, separators=(",", ":"))
                            with open(tmp, 'w', encoding='utf-8') as f:
                                f.write(payload)
                                f.flush()
                                try:
                                    _os.fsync(f.fileno())
                                except Exception:
                                    pass
                            try:
                                _os.replace(tmp, sp)
                            except Exception:
                                _os.rename(tmp, sp)
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_allocator_snapshot_write(ok=True, ts=_t.time())
                            except Exception:
                                pass
                    except Exception:
                        try:
                            if getattr(self, 'metrics', None):
                                import time as _tt
                                self.metrics.inc_allocator_snapshot_write(ok=False, ts=_tt.time())
                        except Exception:
                            pass
                    # deterministic jitter ±10%
                    base = max(1, int(self._allocator_snapshot_interval))
                    seed = str(self._allocator_snapshot_path)
                    j = (int(hmac.new(seed.encode('utf-8'), b'alloc', 'sha1').hexdigest()[:8], 16) % 2001) - 1000
                    frac = (j / 10000.0) * (2 * self._allocator_jitter_frac)
                    delay = max(1.0, base * (1.0 + frac))
                    await asyncio.sleep(delay)
            self._background_tasks.append(asyncio.create_task(_allocator_snapshot_loop()))
            # Start throttle snapshot loop
            async def _throttle_snapshot_loop():
                import time as _t, os as _os, json as _json, hmac as _hmac
                while self.running:
                    try:
                        sp = self._throttle_snapshot_path or "artifacts/throttle_snapshot.json"
                        tmp = sp + ".tmp"
                        # ensure dir exists
                        try:
                            from pathlib import Path as _P
                            _P(sp).parent.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        snap = {}
                        try:
                            if getattr(self.ctx, 'throttle', None):
                                snap = self.ctx.throttle.to_snapshot()
                        except Exception:
                            snap = {"version": 1, "window_since": "1970-01-01T00:00:00+00:00", "events_total": 0, "backoff_ms_max": 0, "last_event_ts": "1970-01-01T00:00:00+00:00"}
                        try:
                            self._atomic_snapshot_write(sp, snap, version=2)
                        except Exception:
                            payload = _json.dumps(snap, sort_keys=True, separators=(",", ":"))
                            with open(tmp, 'w', encoding='utf-8') as f:
                                f.write(payload)
                                f.flush()
                                try:
                                    _os.fsync(f.fileno())
                                except Exception:
                                    pass
                            try:
                                _os.replace(tmp, sp)
                            except Exception:
                                _os.rename(tmp, sp)
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_throttle_snapshot_write(ok=True, ts=_t.time())
                            except Exception:
                                pass
                    except Exception:
                        try:
                            if getattr(self, 'metrics', None):
                                import time as _tt
                                self.metrics.inc_throttle_snapshot_write(ok=False, ts=_tt.time())
                        except Exception:
                            pass
                    # deterministic jitter ±10%
                    base = max(1, int(self._throttle_snapshot_interval))
                    seed = str(self._throttle_snapshot_path)
                    j = (int(_hmac.new(seed.encode('utf-8'), b'throttle', 'sha1').hexdigest()[:8], 16) % 2001) - 1000
                    frac = (j / 10000.0) * (2 * self._throttle_jitter_frac)
                    delay = max(1.0, base * (1.0 + frac))
                    await asyncio.sleep(delay)
            self._background_tasks.append(asyncio.create_task(_throttle_snapshot_loop()))
            # Start rollout ramp loop if enabled
            self._background_tasks.append(asyncio.create_task(self._rollout_ramp_loop()))
            # Start ramp snapshot loop
            self._background_tasks.append(asyncio.create_task(self._ramp_snapshot_loop()))
            # Start scheduler watcher loop
            if not self._scheduler_watcher_task:
                self._scheduler_watcher_task = asyncio.create_task(self._scheduler_watcher_loop())
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"Error starting bot: {e}")
            raise
    
    async def stop(self):
        """
        Gracefully stop the bot.
        
        Shutdown sequence:
        1. Set running = False (stops all loops)
        2. Cancel all active orders on exchange
        3. Stop strategy
        4. Stop WebSocket connector
        5. Close REST connector
        6. Stop web server
        7. Cancel background tasks
        8. Save state (if configured)
        
        Critical: Orders MUST be cancelled before closing connections
        to prevent orphan orders on exchange.
        """
        try:
            print("[STOP] Initiating bot shutdown...")
            self.running = False
            
            # CRITICAL: Cancel all active orders on exchange FIRST
            # This prevents orphan orders that could lead to financial losses
            if self.order_manager and not self.dry_run:
                try:
                    print("[STOP] Cancelling all active orders on exchange...")
                    cancelled_count = await self.order_manager.cancel_all_orders()
                    print(f"[STOP] ✓ Cancelled {cancelled_count} active orders")
                    
                    # Record cancellation event
                    if self.data_recorder:
                        try:
                            await self.data_recorder.record_custom_event(
                                "shutdown_cancel_orders",
                                {
                                    "cancelled_count": cancelled_count,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                }
                            )
                        except Exception:
                            pass
                except Exception as e:
                    print(f"[STOP] ⚠ Error cancelling orders: {e}")
            elif self.dry_run:
                print("[STOP] ⊘ Skipping order cancellation (dry-run mode)")
            
            # Stop strategy
            if self.strategy:
                try:
                    print("[STOP] Stopping strategy...")
                    await self.strategy.stop()
                    print("[STOP] ✓ Strategy stopped")
                except Exception as e:
                    print(f"[STOP] ⚠ Error stopping strategy: {e}")
            
            # Stop WebSocket connector
            if self.ws_connector and not isinstance(self.ws_connector, NullConnector):
                try:
                    print("[STOP] Stopping WebSocket connector...")
                    await self.ws_connector.stop()
                    print("[STOP] ✓ WebSocket connector stopped")
                except Exception as e:
                    print(f"[STOP] ⚠ Error stopping WebSocket: {e}")
            
            # Close REST connector
            if self.rest_connector and not isinstance(self.rest_connector, NullConnector):
                try:
                    print("[STOP] Closing REST connector...")
                    # REST connector implements context manager protocol
                    await self.rest_connector.__aexit__(None, None, None)
                    print("[STOP] ✓ REST connector closed")
                except Exception as e:
                    print(f"[STOP] ⚠ Error closing REST connector: {e}")
            
            # Stop web server
            if self.web_runner:
                try:
                    print("[STOP] Stopping web server...")
                    await self.web_runner.cleanup()
                    print("[STOP] ✓ Web server stopped")
                except Exception as e:
                    print(f"[STOP] ⚠ Error stopping web server: {e}")
            
            # Cancel background tasks
            print("[STOP] Cancelling background tasks...")
            tasks_to_cancel = []
            
            # Named tasks
            for task_name in ['_rollout_state_task', '_rebalance_task', '_scheduler_watcher_task',
                             '_canary_export_task', '_prune_task', '_latency_slo_task', '_soak_task']:
                task = getattr(self, task_name, None)
                if task:
                    tasks_to_cancel.append(task)
                    setattr(self, task_name, None)
            
            # Background task list
            tasks_to_cancel.extend(getattr(self, '_background_tasks', []))
            
            # Cancel all
            for task in tasks_to_cancel:
                try:
                    task.cancel()
                except Exception:
                    pass
            
            # Await cancellation
            if tasks_to_cancel:
                try:
                    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
                except Exception:
                    pass
            
            self._background_tasks = []
            print(f"[STOP] ✓ Cancelled {len(tasks_to_cancel)} background tasks")
            
            # Save final state
            try:
                if self.metrics:
                    print("[STOP] Saving final metrics snapshot...")
                    # Trigger final metric flush if available
                    # (actual implementation depends on metrics backend)
                    pass
            except Exception as e:
                print(f"[STOP] ⚠ Error saving metrics: {e}")
            
            print("[STOP] ✓ Bot shutdown complete")
            
        except Exception as e:
            print(f"[STOP] ✗ Error during shutdown: {e}")
            import traceback
            traceback.print_exc()
    
    async def _start_web_server(self):
        """Start the web server for health checks and metrics."""
        try:
            self._ensure_admin_audit_initialized()
            self.web_app = web.Application()
            # E3: admin latency middleware
            @web.middleware
            async def _admin_perf_mw(request, handler):
                import time as _t
                start = _t.perf_counter()
                try:
                    response = await handler(request)
                    return response
                finally:
                    try:
                        path = getattr(request, 'path', '') or getattr(getattr(request, 'rel_url', None), 'path', '') or ''
                    except Exception:
                        path = ''
                    if path.startswith('/admin/') and getattr(self, 'metrics', None):
                        try:
                            self.metrics.record_admin_endpoint_latency(str(path), (_t.perf_counter() - start) * 1000.0)
                        except Exception:
                            pass
            self.web_app.middlewares.append(_admin_perf_mw)
            
            # Health/SRE endpoints
            self.web_app.router.add_get('/healthz', self._sre_healthz)
            self.web_app.router.add_get('/readyz', self._sre_readyz)
            self.web_app.router.add_get('/version', self._sre_version)
            
            # Metrics endpoint
            self.web_app.router.add_get('/metrics', self._metrics_endpoint)
            
            # Admin endpoints
            self.web_app.router.add_post('/admin/auth/rotate', self._admin_auth_rotate)
            self.web_app.router.add_get('/admin/rollout/state/snapshot', self._admin_rollout_state_snapshot)
            self.web_app.router.add_post('/admin/rollout/state/load', self._admin_rollout_state_load)
            self.web_app.router.add_get('/admin/rollout/state/snapshot_status', self._admin_rollout_state_snapshot_status)
            self.web_app.router.add_get('/admin/audit/log', self._admin_audit_log_get)
            self.web_app.router.add_post('/admin/audit/clear', self._admin_audit_clear)
            self.web_app.router.add_get('/admin/selfcheck', self._admin_selfcheck)
            self.web_app.router.add_get('/admin/config', self._admin_config)
            self.web_app.router.add_post('/admin/reload', self._admin_reload)
            self.web_app.router.add_get('/admin/guard', self._admin_guard)
            self.web_app.router.add_post('/admin/guard', self._admin_guard)
            self.web_app.router.add_get('/admin/autopolicy', self._admin_autopolicy)
            self.web_app.router.add_post('/admin/autopolicy', self._admin_autopolicy)
            self.web_app.router.add_post('/admin/thresholds/reload', self._admin_thresholds_reload)
            self.web_app.router.add_get('/admin/thresholds/snapshot', self._admin_thresholds_snapshot)
            # Perf snapshot
            self.web_app.router.add_get('/admin/perf/snapshot', self._admin_perf_snapshot)
            self.web_app.router.add_get('/admin/perf/soak_snapshot', self._admin_perf_soak_snapshot)
            self.web_app.router.add_get('/admin/rollout/ramp', self._admin_rollout_ramp)
            self.web_app.router.add_post('/admin/rollout/ramp', self._admin_rollout_ramp)
            self.web_app.router.add_get('/admin/rollout/ramp/snapshot', self._admin_rollout_ramp_snapshot)
            self.web_app.router.add_post('/admin/rollout/ramp/load', self._admin_rollout_ramp_load)
            self.web_app.router.add_get('/admin/rollout/ramp/snapshot_status', self._admin_rollout_ramp_snapshot_status)
            self.web_app.router.add_post('/admin/rollout/ramp/freeze', self._admin_rollout_ramp_freeze)
            # Rollout admin
            self.web_app.router.add_get('/admin/rollout', self._admin_rollout)
            self.web_app.router.add_post('/admin/rollout', self._admin_rollout)
            # Rollout killswitch admin
            self.web_app.router.add_get('/admin/rollout/killswitch', self._admin_killswitch)
            self.web_app.router.add_post('/admin/rollout/killswitch', self._admin_killswitch)
            # Rollout manual promotion
            self.web_app.router.add_get('/admin/rollout/promote', self._admin_rollout_promote)
            self.web_app.router.add_post('/admin/rollout/promote', self._admin_rollout_promote)
            
            # Markout snapshot endpoint
            self.web_app.router.add_get('/admin/rollout/markout_snapshot', self._admin_rollout_markout_snapshot)
            # Alerts log admin
            self.web_app.router.add_get('/admin/alerts/log', self._admin_alerts_log)
            self.web_app.router.add_post('/admin/alerts/clear', self._admin_alerts_clear)
            
            # Anti-stale order guard
            self.web_app.router.add_get('/admin/anti-stale-guard', self._admin_anti_stale_guard)
            self.web_app.router.add_post('/admin/anti-stale-guard', self._admin_anti_stale_guard)
            
            # Scheduler smart windows
            self.web_app.router.add_get('/admin/scheduler/suggest', self._admin_scheduler_suggest)
            self.web_app.router.add_post('/admin/scheduler/apply', self._admin_scheduler_apply)
            # Start prune loop
            try:
                self._prune_interval = float(os.getenv('PRUNE_INTERVAL_SEC', '3600'))
            except Exception:
                self._prune_interval = 3600.0
            self._prune_task = asyncio.create_task(self._prune_artifacts_loop())
            # Start scheduler recompute loop if enabled by env
            asyncio.create_task(self._scheduler_recompute_loop())
            # Allocator admin endpoints
            self.web_app.router.add_get('/admin/allocator/snapshot', self._admin_allocator_snapshot)
            self.web_app.router.add_post('/admin/allocator/load', self._admin_allocator_load)
            self.web_app.router.add_post('/admin/allocator/reset_hwm', self._admin_allocator_reset_hwm)
            self.web_app.router.add_get('/admin/allocator/snapshot_status', self._admin_allocator_snapshot_status)
            # L6.2 Cost calibration admin
            self.web_app.router.add_get('/admin/allocator/cost_calibration', self._admin_cost_calibration)
            self.web_app.router.add_post('/admin/allocator/cost_calibration/apply', self._admin_cost_calibration_apply)
            self.web_app.router.add_get('/admin/allocator/cost_calibration/snapshot', self._admin_cost_calibration_snapshot)
            self.web_app.router.add_post('/admin/allocator/cost_calibration/load', self._admin_cost_calibration_load)
            self.web_app.router.add_get('/admin/allocator/cost_calibration/config', self._admin_cost_calibration_config)
            self.web_app.router.add_post('/admin/allocator/cost_calibration/config', self._admin_cost_calibration_config)
            # L6 dashboards obs snapshot
            self.web_app.router.add_get('/admin/allocator/obs_snapshot', self._admin_allocator_obs_snapshot)
            # Execution recorder & replay
            self.web_app.router.add_get('/admin/execution/recorder/status', self._admin_execution_recorder_status)
            self.web_app.router.add_post('/admin/execution/recorder/rotate', self._admin_execution_recorder_rotate)
            self.web_app.router.add_post('/admin/execution/replay', self._admin_execution_replay)
            # Throttle admin endpoints
            self.web_app.router.add_get('/admin/throttle/snapshot', self._admin_throttle_snapshot)
            self.web_app.router.add_post('/admin/throttle/load', self._admin_throttle_load)
            self.web_app.router.add_post('/admin/throttle/reset', self._admin_throttle_reset)
            self.web_app.router.add_get('/admin/throttle/snapshot_status', self._admin_throttle_snapshot_status)
            # Chaos admin
            self.web_app.router.add_get('/admin/chaos', self._admin_chaos)
            self.web_app.router.add_post('/admin/chaos', self._admin_chaos)
            # Canary report endpoints
            self.web_app.router.add_get('/admin/report/canary', self._admin_report_canary)
            self.web_app.router.add_post('/admin/report/canary/generate', self._admin_report_canary_generate)
            self.web_app.router.add_post('/admin/report/canary/replay', self._admin_report_canary_replay)
            self.web_app.router.add_post('/admin/report/canary/baseline', self._admin_report_canary_baseline)
            self.web_app.router.add_get('/admin/report/canary/diff', self._admin_report_canary_diff)
            
            # Status endpoint
            self.web_app.router.add_get('/status', self._status_endpoint)
            
            # Start server
            self.web_runner = web.AppRunner(self.web_app)
            await self.web_runner.setup()
            
            site = web.TCPSite(self.web_runner, 'localhost', self.config.monitoring.health_port)
            await site.start()
            
            print(f"Web server started on port {self.config.monitoring.health_port}")
            
            # Record web server start
            asyncio.create_task(self.data_recorder.record_custom_event(
                "web_server_started",
                {
                    "port": self.config.monitoring.health_port,
                    "timestamp": datetime.now(timezone.utc)
                }
            ))
            # Start rollout state snapshot loop
            try:
                self._rollout_state_task = asyncio.create_task(self._rollout_state_snapshot_loop())
            except Exception:
                self._rollout_state_task = None
            # Start scheduled canary exporter
            try:
                iv = 0
                try:
                    iv = int(os.getenv('CANARY_EXPORT_INTERVAL_SEC', '300'))
                except Exception:
                    iv = 300
                self._canary_export_interval = max(1, int(iv))
                self._canary_export_task = asyncio.create_task(self._canary_export_loop())
            except Exception:
                self._canary_export_task = None
            # Start latency SLO loop
            try:
                self._latency_slo_task = asyncio.create_task(self._latency_slo_loop())
            except Exception:
                self._latency_slo_task = None
            # Start soak guard loop
            try:
                self._soak_task = asyncio.create_task(self._soak_guard_loop())
            except Exception:
                self._soak_task = None
            
        except Exception as e:
            print(f"Failed to start web server: {e}")
    
    async def _health_check(self, request):
        """Enhanced health check endpoint with AppConfig integration."""
        try:
            # Get recorder stats safely
            recorder_stats = {}
            if self.data_recorder:
                try:
                    recorder_stats = self.data_recorder.get_storage_stats()
                except Exception:
                    recorder_stats = {"error": "failed_to_get_stats"}
            
            # Safe connector status checks
            ws_up = (self.ws_connector and hasattr(self.ws_connector, "is_connected") and self.ws_connector.is_connected()) or False
            rest_up = (self.rest_connector and hasattr(self.rest_connector, "is_connected") and self.rest_connector.is_connected()) or False
            
            # Enhanced health data with AppConfig
            health_data = {
                "status": "ok" if (ws_up and rest_up) else "degraded",
                "marketdata_ok": ws_up,
                "strategy_ok": True,  # Strategy is always ok if bot is running
                "execution_ok": rest_up,
                "exchange_ok": rest_up,
                "risk_paused": getattr(self.risk_manager, 'paused', False) if hasattr(self, 'risk_manager') else False,
                "git_sha": get_git_sha(),
                "config_version": getattr(self.config, 'config_version', 1),
                "cfg_hash": cfg_hash_sanitized(self.config) if hasattr(self.config, 'to_sanitized') else "unknown",
                "uptime": (datetime.now(timezone.utc) - self.start_time).total_seconds() if self.start_time else 0,
                "ws": "up" if ws_up else "down",
                "rest": "up" if rest_up else "down",
                "rec_q": recorder_stats.get("queue_size", 0),
                "flushes": recorder_stats.get("flushes", 0)
            }
            
            # Update connection status metrics with proper dict
            if self.metrics_exporter:
                connection_status = {
                    "ws": health_data["ws"],
                    "rest": health_data["rest"],
                    "rec_q": health_data["rec_q"],
                    "flushes": health_data["flushes"]
                }
                self.metrics_exporter.update_connection_status(connection_status)
            
            return self._json_response(health_data, status=200)
            
        except Exception as e:
            return self._json_response({"status": "error", "error": str(e)}, status=500)

    async def _sre_healthz(self, request):
        try:
            # uptime since process start
            import time as _t
            up = 0.0
            try:
                up = _t.time() - self.start_time.timestamp() if self.start_time else 0.0
            except Exception:
                up = 0.0
            payload = json.dumps({"status": "ok", "uptime_seconds": float(max(0.0, up))}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return web.Response(body=payload, content_type='application/json')
        except Exception:
            return web.Response(body=b'{"status":"ok"}', content_type='application/json')

    async def _sre_readyz(self, request):
        try:
            reasons = []
            # guard effective pause
            try:
                rg = getattr(self.config, 'runtime_guard', None) or RuntimeGuardConfig()
                manual = bool(getattr(rg, 'manual_override_pause', False))
                dry_run = bool(getattr(rg, 'dry_run', False))
                paused = bool(getattr(getattr(self.ctx, 'guard', None), 'paused', False))
                effective = manual or (paused and not dry_run)
                if effective:
                    reasons.append("guard_paused_effective")
            except Exception:
                pass
            # circuit open
            try:
                circ = getattr(self.ctx, 'circuit', None)
                if circ and getattr(circ, 'state', None) and circ.state() == 'open':
                    reasons.append("circuit_open")
            except Exception:
                pass
            reasons = sorted(reasons)
            if reasons:
                payload = json.dumps({"status": "not_ready", "reasons": reasons}, sort_keys=True, separators=(",", ":")).encode("utf-8")
                return web.Response(status=503, body=payload, content_type='application/json')
            payload = json.dumps({"status": "ready"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            payload = json.dumps({"status": "not_ready", "reasons": [str(e)]}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return web.Response(status=503, body=payload, content_type='application/json')

    async def _sre_version(self, request):
        try:
            data = {
                "commit": get_git_sha() or "unknown",
                "params_hash": self._params_hash or "unknown",
                "build_time": self._build_time_iso,
            }
            payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return web.Response(body=payload, content_type='application/json')
        except Exception:
            return web.Response(body=b'{"commit":"unknown","params_hash":"unknown","build_time":"unknown"}', content_type='application/json')
    
    async def _metrics_endpoint(self, request):
        """Metrics endpoint."""
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
            data = generate_latest()
            return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
            
        except Exception as e:
            # Fallback to error response if Prometheus not available
            return self._json_response({"error": "Metrics not available", "details": str(e)}, status=503)

    async def _admin_config(self, request):
        """Admin config endpoint."""
        try:
            data = {
                "cfg_hash": cfg_hash_sanitized(self.config),
                "config": self.config.to_sanitized(),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_ramp(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/ramp')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            ro = getattr(self.config, 'rollout_ramp', None)
            if request.method == 'GET':
                data = {
                    "enabled": bool(getattr(ro, 'enabled', False)) if ro else False,
                    "steps_pct": list(getattr(ro, 'steps_pct', [])) if ro else [],
                    "step_interval_sec": int(getattr(ro, 'step_interval_sec', 600)) if ro else 600,
                    "max_reject_rate_delta_pct": float(getattr(ro, 'max_reject_rate_delta_pct', 2.0)) if ro else 2.0,
                    "max_latency_delta_ms": int(getattr(ro, 'max_latency_delta_ms', 50)) if ro else 50,
                    "max_pnl_delta_usd": float(getattr(ro, 'max_pnl_delta_usd', 0.0)) if ro else 0.0,
                    "step_idx": int(getattr(self, '_ramp_step_idx', 0)),
                    "min_sample_fills": int(getattr(ro, 'min_sample_fills', 200)) if ro else 200,
                    "max_step_increase_pct": int(getattr(ro, 'max_step_increase_pct', 10)) if ro else 10,
                    "cooldown_after_rollback_sec": int(getattr(ro, 'cooldown_after_rollback_sec', 900)) if ro else 900,
                }
                return self._json_response(data)
            # POST: update
            try:
                body = await request.json()
            except Exception:
                body = {}
            if ro is None:
                from src.common.config import RolloutRampConfig
                ro = RolloutRampConfig()
                self.config.rollout_ramp = ro  # type: ignore[attr-defined]
            if isinstance(body, dict):
                if 'enabled' in body:
                    ro.enabled = bool(body['enabled'])
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.set_ramp_enabled(bool(ro.enabled))
                        except Exception:
                            pass
                if 'steps_pct' in body:
                    steps = [int(x) for x in (body.get('steps_pct') or [])]
                    steps = sorted(x for x in steps if 0 <= x <= 100)
                    if not steps:
                        return self._json_response({"error": "invalid_steps"}, status=400)
                    ro.steps_pct = steps
                    if self._ramp_step_idx >= len(steps):
                        self._ramp_step_idx = len(steps) - 1
                if 'step_interval_sec' in body:
                    v = int(body['step_interval_sec'])
                    if v < 10:
                        return self._json_response({"error": "invalid_interval"}, status=400)
                    ro.step_interval_sec = v
                if 'max_reject_rate_delta_pct' in body:
                    ro.max_reject_rate_delta_pct = float(body['max_reject_rate_delta_pct'])
                if 'max_latency_delta_ms' in body:
                    ro.max_latency_delta_ms = int(body['max_latency_delta_ms'])
                if 'max_pnl_delta_usd' in body:
                    ro.max_pnl_delta_usd = float(body['max_pnl_delta_usd'])
                if 'min_sample_fills' in body:
                    v = int(body['min_sample_fills'])
                    if v < 0:
                        return self._json_response({"error": "invalid_min_sample"}, status=400)
                    ro.min_sample_fills = v
                if 'max_step_increase_pct' in body:
                    v = int(body['max_step_increase_pct'])
                    if v < 0 or v > 100:
                        return self._json_response({"error": "invalid_step_cap"}, status=400)
                    ro.max_step_increase_pct = v
                if 'cooldown_after_rollback_sec' in body:
                    v = int(body['cooldown_after_rollback_sec'])
                    if v < 0:
                        return self._json_response({"error": "invalid_cooldown"}, status=400)
                    ro.cooldown_after_rollback_sec = v
                self._rollout_state_dirty = True
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/ramp')
                except Exception:
                    pass
            data = {
                "enabled": bool(getattr(ro, 'enabled', False)),
                "steps_pct": list(getattr(ro, 'steps_pct', [])),
                "step_interval_sec": int(getattr(ro, 'step_interval_sec', 600)),
                "max_reject_rate_delta_pct": float(getattr(ro, 'max_reject_rate_delta_pct', 2.0)),
                "max_latency_delta_ms": int(getattr(ro, 'max_latency_delta_ms', 50)),
                "max_pnl_delta_usd": float(getattr(ro, 'max_pnl_delta_usd', 0.0)),
                "step_idx": int(getattr(self, '_ramp_step_idx', 0)),
                "min_sample_fills": int(getattr(ro, 'min_sample_fills', 200)),
                "max_step_increase_pct": int(getattr(ro, 'max_step_increase_pct', 10)),
                "cooldown_after_rollback_sec": int(getattr(ro, 'cooldown_after_rollback_sec', 900)),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _rollout_ramp_loop(self):
        import os as _os, time as _t
        while self.running:
            try:
                # env override for fast tests
                try:
                    env_int = int(_os.getenv('ROLLOUT_STEP_INTERVAL_SEC', '0'))
                except Exception:
                    env_int = 0
                conf_int = int(getattr(getattr(self.config, 'rollout_ramp', object()), 'step_interval_sec', 600))
                interval = env_int if env_int and env_int >= 1 else conf_int
                # sleep in small steps to respect shutdown quickly
                remaining = float(max(1, interval))
                while getattr(self, 'running', False) and remaining > 0.0:
                    step = 0.05 if remaining > 0.05 else remaining
                    t0 = _t.perf_counter()
                    await asyncio.sleep(step)
                    drift = (_t.perf_counter() - t0) * 1000.0 - (step * 1000.0)
                    if drift > 100.0 and getattr(self, 'metrics', None):
                        try:
                            self.metrics.set_event_loop_drift(drift)
                        except Exception:
                            pass
                    remaining -= step
                if not getattr(self, 'running', False):
                    break
                t0 = _t.perf_counter()
                await self._rollout_ramp_tick()
                dt_ms = (_t.perf_counter() - t0) * 1000.0
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.record_loop_tick('ramp', dt_ms)
                    except Exception:
                        pass
            except Exception:
                await asyncio.sleep(0.05)

    async def _soak_guard_loop(self):
        import os as _os, time as _t, sys as _sys, platform as _pf, threading as _th, gc as _gc
        # window seconds
        try:
            win = float(_os.getenv('SOAK_WINDOW_SEC', '300'))
        except Exception:
            win = 300.0
        if win < 1.0:
            win = 1.0
        # thresholds
        try:
            rss_max_mb = float(_os.getenv('SOAK_RSS_MAX_MB', '0'))
        except Exception:
            rss_max_mb = 0.0
        try:
            drift_max_ms = float(_os.getenv('SOAK_DRIFT_MAX_MS', '0'))
        except Exception:
            drift_max_ms = 0.0
        try:
            threads_max = int(_os.getenv('SOAK_THREADS_MAX', '0'))
        except Exception:
            threads_max = 0
        is_windows = str(_pf.system()).lower().startswith('win')
        # state (current and window max)
        self._soak_cur = {
            'rss_bytes': 0,
            'open_fds': 0,
            'threads': 0,
            'gc_gen': [0, 0, 0],
            'drift_ms': 0.0,
        }
        self._soak_max = {
            'rss_bytes': 0,
            'open_fds': 0,
            'threads': 0,
            'gc_gen': [0, 0, 0],
            'drift_ms': 0.0,
        }
        window_started = _t.time()
        while self.running:
            t0 = _t.perf_counter()
            try:
                # drift measurement with 50ms tick
                await asyncio.sleep(0.05)
                drift = (_t.perf_counter() - t0) * 1000.0 - 50.0
                # update current and max
                self._soak_cur['drift_ms'] = float(max(0.0, drift))
                if self._soak_cur['drift_ms'] > self._soak_max['drift_ms']:
                    self._soak_max['drift_ms'] = float(self._soak_cur['drift_ms'])
                # publish max drift over window
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.event_loop_max_drift_ms.set(float(self._soak_max['drift_ms']))
                    except Exception:
                        pass
                # threads
                try:
                    th = int(len(_th.enumerate()))
                except Exception:
                    th = 0
                self._soak_cur['threads'] = int(max(0, th))
                if self._soak_cur['threads'] > self._soak_max['threads']:
                    self._soak_max['threads'] = int(self._soak_cur['threads'])
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.soak_threads_total.set(float(self._soak_cur['threads']))
                    except Exception:
                        pass
                # GC generations
                try:
                    counts = tuple(int(x) for x in _gc.get_count())
                except Exception:
                    counts = (0, 0, 0)
                self._soak_cur['gc_gen'] = [int(max(0, v)) for v in (counts + (0, 0, 0))[:3]]
                self._soak_max['gc_gen'] = [max(self._soak_max['gc_gen'][i], self._soak_cur['gc_gen'][i]) for i in range(3)]
                if getattr(self, 'metrics', None):
                    try:
                        for i, v in enumerate(self._soak_cur['gc_gen']):
                            self.metrics.soak_gc_gen.labels(gen=str(i)).set(float(v))
                    except Exception:
                        pass
                # RSS and FDs stdlib-only best-effort
                rss_bytes = 0
                try:
                    # resource (POSIX)
                    try:
                        import resource as _res  # type: ignore
                        try:
                            usage = _res.getrusage(_res.RUSAGE_SELF)
                            ru = float(getattr(usage, 'ru_maxrss', 0.0))
                            rss_bytes = int(ru * 1024.0) if ru and ru < 1e9 else int(ru)
                        except Exception:
                            rss_bytes = 0
                    except Exception:
                        rss_bytes = 0
                except Exception:
                    rss_bytes = 0
                if rss_bytes <= 0:
                    # tracemalloc fallback (process memory subset)
                    try:
                        import tracemalloc as _tm
                        try:
                            if not _tm.is_tracing():
                                _tm.start()
                            cur, _peak = _tm.get_traced_memory()
                            rss_bytes = int(max(rss_bytes, int(cur)))
                        except Exception:
                            pass
                    except Exception:
                        pass
                open_fds = 0
                if not is_windows:
                    try:
                        # Count file descriptors via /proc (Linux) without psutil
                        import os as __os
                        proc_fd = f"/proc/{__os.getpid()}/fd"
                        if __os.path.isdir(proc_fd):
                            try:
                                open_fds = len(__os.listdir(proc_fd))
                            except Exception:
                                open_fds = 0
                    except Exception:
                        open_fds = 0
                else:
                    open_fds = 0
                self._soak_cur['rss_bytes'] = int(max(0, rss_bytes))
                self._soak_cur['open_fds'] = int(max(0, open_fds))
                if self._soak_cur['rss_bytes'] > self._soak_max['rss_bytes']:
                    self._soak_max['rss_bytes'] = int(self._soak_cur['rss_bytes'])
                if self._soak_cur['open_fds'] > self._soak_max['open_fds']:
                    self._soak_max['open_fds'] = int(self._soak_cur['open_fds'])
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.soak_mem_rss_bytes.set(float(self._soak_cur['rss_bytes']))
                        self.metrics.soak_open_fds.set(float(self._soak_cur['open_fds']))
                        self.metrics.record_loop_heartbeat('soak')
                    except Exception:
                        pass
                # thresholds check with alerts
                breach = False
                reasons = []
                if rss_max_mb > 0.0 and (self._soak_cur['rss_bytes'] / (1024.0 * 1024.0)) > rss_max_mb:
                    breach = True
                    reasons.append('rss')
                if drift_max_ms > 0.0 and self._soak_max['drift_ms'] > drift_max_ms:
                    breach = True
                    reasons.append('drift')
                if threads_max > 0 and self._soak_cur['threads'] > threads_max:
                    breach = True
                    reasons.append('threads')
                if breach:
                    try:
                        ts_iso = datetime.now(timezone.utc).isoformat()
                        payload = {
                            'rss_bytes': int(self._soak_cur['rss_bytes']),
                            'open_fds': int(self._soak_cur['open_fds']),
                            'threads': int(self._soak_cur['threads']),
                            'gc_gen': {'0': int(self._soak_cur['gc_gen'][0]), '1': int(self._soak_cur['gc_gen'][1]), '2': int(self._soak_cur['gc_gen'][2])},
                            'drift_ms': float(self._soak_max['drift_ms']),
                            'reasons': reasons,
                        }
                        self._append_json_line(self._alerts_log_file(), {"ts": ts_iso, "kind": "soak_guard_breach", "payload": payload})
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_admin_alert_event('soak_guard_breach')
                            except Exception:
                                pass
                    except Exception:
                        pass
                # reset window maxima periodically using window length
                try:
                    now = _t.time()
                    if (now - window_started) >= float(win):
                        self._soak_max = {
                            'rss_bytes': int(self._soak_cur['rss_bytes']),
                            'open_fds': int(self._soak_cur['open_fds']),
                            'threads': int(self._soak_cur['threads']),
                            'gc_gen': list(self._soak_cur['gc_gen']),
                            'drift_ms': float(self._soak_cur['drift_ms']),
                        }
                        window_started = now
                except Exception:
                    pass
            except Exception:
                await asyncio.sleep(0.05)

    async def _rollout_ramp_tick(self):
        ro = getattr(self.config, 'rollout_ramp', None)
        if not ro or not getattr(ro, 'enabled', False):
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_ramp_enabled(False)
                except Exception:
                    pass
            return
        if getattr(self, 'metrics', None):
            try:
                self.metrics.set_ramp_enabled(True)
                self.metrics.set_ramp_step_idx(int(self._ramp_step_idx))
            except Exception:
                pass
        # Read per-color counters/latency from metrics exporter snapshots if available
        m = getattr(self, 'metrics', None)
        fills_b = fills_g = rej_b = rej_g = 0
        lat_b = lat_g = 0.0
        if m and hasattr(m, '_get_rollout_snapshot_for_tests'):
            snap = m._get_rollout_snapshot_for_tests()
            fills_b = int((snap.get('fills', {}) or {}).get('blue', 0))
            fills_g = int((snap.get('fills', {}) or {}).get('green', 0))
            rej_b = int((snap.get('rejects', {}) or {}).get('blue', 0))
            rej_g = int((snap.get('rejects', {}) or {}).get('green', 0))
            lat_b = float((snap.get('latency_ewma', {}) or {}).get('blue', 0.0))
            lat_g = float((snap.get('latency_ewma', {}) or {}).get('green', 0.0))
        # compute deltas
        d_fills_b = max(0, fills_b - int(self._ramp_last_counters['fills']['blue']))
        d_fills_g = max(0, fills_g - int(self._ramp_last_counters['fills']['green']))
        d_rej_b = max(0, rej_b - int(self._ramp_last_counters['rejects']['blue']))
        d_rej_g = max(0, rej_g - int(self._ramp_last_counters['rejects']['green']))
        # HOLD if low sample
        try:
            min_sample = int(getattr(ro, 'min_sample_fills', 0))
        except Exception:
            min_sample = 0
        if min(d_fills_b, d_fills_g) < max(0, min_sample):
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_ramp_hold('sample')
                except Exception:
                    pass
            # update last snapshots and return
            self._ramp_last_counters['fills']['blue'] = fills_b
            self._ramp_last_counters['fills']['green'] = fills_g
            self._ramp_last_counters['rejects']['blue'] = rej_b
            self._ramp_last_counters['rejects']['green'] = rej_g
            return
        # update last snapshots
        self._ramp_last_counters['fills']['blue'] = fills_b
        self._ramp_last_counters['fills']['green'] = fills_g
        self._ramp_last_counters['rejects']['blue'] = rej_b
        self._ramp_last_counters['rejects']['green'] = rej_g
        # derive rates (percent)
        rr_b = (d_rej_b / max(1, (d_fills_b + d_rej_b))) * 100.0
        rr_g = (d_rej_g / max(1, (d_fills_g + d_rej_g))) * 100.0
        healthy = True
        # Incident freeze: not-ready or severe deltas
        severe = ((rr_g - rr_b) > max(5.0, float(getattr(ro, 'max_reject_rate_delta_pct', 2.0)))) or ((lat_g - lat_b) > max(150.0, float(getattr(ro, 'max_latency_delta_ms', 50))))
        if severe:
            # Respect killswitch config
            ks_sv = getattr(self.config, 'killswitch', None)
            if ks_sv and getattr(ks_sv, 'enabled', False):
                if getattr(ks_sv, 'dry_run', True):
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_killswitch_check()
                            self.metrics.inc_killswitch_trigger('dry_run')
                        except Exception:
                            pass
                    return
                # action-specific
                act_sv = str(getattr(ks_sv, 'action', 'rollback'))
                if act_sv == 'freeze':
                    self._ramp_state['frozen'] = True
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_killswitch_trigger('freeze')
                            self.metrics.inc_ramp_freeze()
                            self.metrics.set_ramp_frozen(True)
                        except Exception:
                            pass
                    return
                elif act_sv == 'rollback':
                    # step down by one if possible
                    steps = list(getattr(ro, 'steps_pct', []) or [0])
                    if self._ramp_step_idx > 0:
                        new_idx = self._ramp_step_idx - 1
                        self._ramp_step_idx = new_idx
                        try:
                            self.config.rollout.traffic_split_pct = int(steps[new_idx])
                        except Exception:
                            pass
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.set_rollout_split_pct(int(getattr(self.config.rollout, 'traffic_split_pct', 0)))
                                self.metrics.set_ramp_step_idx(int(new_idx))
                            except Exception:
                                pass
                    # start cooldown after rollback
                    try:
                        cd = int(getattr(ro, 'cooldown_after_rollback_sec', 0))
                    except Exception:
                        cd = 0
                    if cd > 0:
                        import time as _t
                        self._ramp_cooldown_until = float(_t.time()) + float(cd)
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_killswitch_trigger('rollback')
                        except Exception:
                            pass
                    return
            # default severe handling: freeze + rollback one step
            self._ramp_state['frozen'] = True
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_ramp_freeze()
                    self.metrics.set_ramp_frozen(True)
                except Exception:
                    pass
            # step down by one if possible
            steps = list(getattr(ro, 'steps_pct', []) or [0])
            if self._ramp_step_idx > 0:
                new_idx = self._ramp_step_idx - 1
                self._ramp_step_idx = new_idx
                try:
                    self.config.rollout.traffic_split_pct = int(steps[new_idx])
                except Exception:
                    pass
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.set_rollout_split_pct(int(getattr(self.config.rollout, 'traffic_split_pct', 0)))
                        self.metrics.set_ramp_step_idx(int(new_idx))
                    except Exception:
                        pass
            # start cooldown after rollback
            try:
                cd = int(getattr(ro, 'cooldown_after_rollback_sec', 0))
            except Exception:
                cd = 0
            if cd > 0:
                import time as _t
                self._ramp_cooldown_until = float(_t.time()) + float(cd)
            # do not proceed with normal adjustment
            return
        else:
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_ramp_frozen(False)
                except Exception:
                    pass
            self._ramp_state['frozen'] = False
        if (rr_g - rr_b) > float(getattr(ro, 'max_reject_rate_delta_pct', 2.0)):
            healthy = False
        if (lat_g - lat_b) > float(getattr(ro, 'max_latency_delta_ms', 50)):
            healthy = False

        # Canary kill-switch logic
        ks = getattr(self, 'config', None)
        ks = getattr(ks, 'killswitch', None)
        if getattr(self, 'metrics', None):
            try:
                self.metrics.inc_killswitch_check()
            except Exception:
                pass
        if ks and getattr(ks, 'enabled', False):
            try:
                min_f = int(getattr(ks, 'min_fills', 500))
            except Exception:
                min_f = 500
            fills_total = int(d_fills_b + d_fills_g)
            rej_delta = (rr_g - rr_b) / 100.0  # convert to fraction for compare against max_reject_delta
            lat_delta = float(lat_g - lat_b)
            fired = False
            reason = "none"
            if fills_total >= min_f and (rej_delta > float(getattr(ks, 'max_reject_delta', 0.02)) or lat_delta > float(getattr(ks, 'max_latency_delta_ms', 50))):
                fired = True
                reason = "reject_delta" if rej_delta > float(getattr(ks, 'max_reject_delta', 0.02)) else "latency_delta"
            if fired:
                if getattr(ks, 'dry_run', True):
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_killswitch_trigger('dry_run')
                        except Exception:
                            pass
                    # In dry-run, do not change state; stop processing this tick
                    return
                else:
                    act = str(getattr(ks, 'action', 'rollback'))
                    if act == 'rollback':
                        if self._ramp_step_idx > 0:
                            new_idx = self._ramp_step_idx - 1
                            self._ramp_step_idx = new_idx
                            try:
                                steps = list(getattr(ro, 'steps_pct', []) or [0])
                                self.config.rollout.traffic_split_pct = int(steps[new_idx])
                            except Exception:
                                pass
                            if getattr(self, 'metrics', None):
                                try:
                                    self.metrics.set_rollout_split_pct(int(getattr(self.config.rollout, 'traffic_split_pct', 0)))
                                    self.metrics.set_ramp_step_idx(int(new_idx))
                                except Exception:
                                    pass
                        # start cooldown
                        try:
                            cd = int(getattr(ro, 'cooldown_after_rollback_sec', 0))
                        except Exception:
                            cd = 0
                        if cd > 0:
                            import time as _t
                            self._ramp_cooldown_until = float(_t.time()) + float(cd)
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_killswitch_trigger('rollback')
                            except Exception:
                                pass
                        return
                    elif act == 'freeze':
                        self._ramp_state['frozen'] = True
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_killswitch_trigger('freeze')
                                self.metrics.set_ramp_frozen(True)
                            except Exception:
                                pass
                        return
        # autopromotion stability tracking
        try:
            drift_alert = False
            # simple drift compared later in payload; here we recompute minimal signal
            observed = 0.0
            expected = 0.0
            try:
                expected = float(getattr(self.config.rollout, 'traffic_split_pct', 0))
            except Exception:
                expected = 0.0
            try:
                obs_g = int(getattr(m, '_rollout_orders_count', {}).get('green', 0)) if m else 0
                obs_b = int(getattr(m, '_rollout_orders_count', {}).get('blue', 0)) if m else 0
                tot = obs_g + obs_b
                observed = 0.0 if tot <= 0 else (100.0 * obs_g / float(tot))
            except Exception:
                observed = 0.0
            drift_alert = abs(observed - expected) > 5.0 and (obs_b + obs_g) >= 100
            # triage hints condition (simple proxy): none when healthy by rr/lat
            triage_empty = healthy
            ks_fired_flag = False
            # check recent ks fired in this tick already evaluated (fired variable)
            ks_fired_flag = False  # since we returned on fired actions/dry-run
            if healthy and (not drift_alert) and (not self._ramp_state.get('frozen', False)) and triage_empty:
                self._ramp_state['consecutive_stable_steps'] = int(self._ramp_state.get('consecutive_stable_steps', 0)) + 1
            else:
                self._ramp_state['consecutive_stable_steps'] = 0
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_autopromote_stable_steps(int(self._ramp_state['consecutive_stable_steps']))
                except Exception:
                    pass
            # attempt autopromotion
            ap = getattr(self.config, 'autopromote', None)
            if ap and getattr(ap, 'enabled', False):
                need = int(getattr(ap, 'stable_steps_required', 6))
                min_split = int(getattr(ap, 'min_split_pct', 25))
                cur_split = int(getattr(self.config.rollout, 'traffic_split_pct', 0))
                if int(self._ramp_state['consecutive_stable_steps']) >= need and cur_split >= min_split:
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_autopromote_attempt()
                        except Exception:
                            pass
                    # flip: active->green, disable ramp, reset
                    try:
                        self.config.rollout.active = 'green'
                    except Exception:
                        pass
                    try:
                        self.config.rollout_ramp.enabled = False
                        self._ramp_state['frozen'] = False
                        self._ramp_step_idx = 0
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.set_ramp_enabled(False)
                                self.metrics.set_ramp_step_idx(0)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        self.config.rollout.traffic_split_pct = 0
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.set_rollout_split_pct(0)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._rollout_state_dirty = True
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_autopromote_flip()
                        except Exception:
                            pass
                    # audit and alerts
                    self._admin_audit_record('/admin/rollout/promote', type('R', (), {'headers': {}, 'rel_url': type('U', (), {'query': {}})(), 'method':'AUTO'})(), {"auto": True})
                    try:
                        ts_iso = datetime.now(timezone.utc).isoformat()
                        self._append_json_line(self._alerts_log_file(), {"ts": ts_iso, "kind": "autopromote_flip", "payload": {"auto": True}})
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_admin_alert_event('autopromote_flip')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._ramp_state['consecutive_stable_steps'] = 0
        except Exception:
            pass
        # pnl optional check (skipped if gauges not used)
        # adjust step
        steps = list(getattr(ro, 'steps_pct', []) or [0])
        idx = int(self._ramp_step_idx)
        new_idx = idx
        if healthy and idx < len(steps) - 1:
            # cooldown hold
            try:
                import time as _t
                now = float(_t.time())
                if getattr(self, '_ramp_cooldown_until', 0.0) > now:
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_ramp_hold('cooldown')
                            self.metrics.set_ramp_cooldown_seconds(getattr(self, '_ramp_cooldown_until', 0.0) - now)
                        except Exception:
                            pass
                    return
            except Exception:
                pass
            new_idx = idx + 1
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_ramp_transition('up')
                except Exception:
                    pass
        elif not healthy and idx > 0:
            new_idx = idx - 1
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_ramp_transition('down')
                    self.metrics.inc_ramp_rollback()
                except Exception:
                    pass
        # apply change
        if new_idx != idx:
            self._ramp_step_idx = new_idx
            try:
                target = int(steps[new_idx])
                current = int(getattr(self.config.rollout, 'traffic_split_pct', target))
                cap = int(max(0, min(100, int(getattr(ro, 'max_step_increase_pct', 100)))))
                if target > current and cap < 100:
                    self.config.rollout.traffic_split_pct = int(min(target, current + cap))
                else:
                    self.config.rollout.traffic_split_pct = int(target)
            except Exception:
                pass
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_rollout_split_pct(int(getattr(self.config.rollout, 'traffic_split_pct', 0)))
                    self.metrics.set_ramp_step_idx(int(new_idx))
                except Exception:
                    pass
        # update ramp state snapshot base
        self._ramp_state['enabled'] = bool(getattr(ro, 'enabled', False))
        self._ramp_state['step_idx'] = int(self._ramp_step_idx)
        self._ramp_state['last'] = {
            'fills': {'blue': fills_b, 'green': fills_g},
            'rejects': {'blue': rej_b, 'green': rej_g},
        }
        import time as _t
        self._ramp_state['updated_ts'] = float(_t.time())

    def _to_ramp_snapshot(self) -> dict:
        try:
            return {
                'version': 1,
                'enabled': bool(self._ramp_state.get('enabled', False)),
                'step_idx': int(self._ramp_state.get('step_idx', 0)),
                'last': {
                    'fills': {
                        'blue': int(self._ramp_state.get('last', {}).get('fills', {}).get('blue', 0)),
                        'green': int(self._ramp_state.get('last', {}).get('fills', {}).get('green', 0)),
                    },
                    'rejects': {
                        'blue': int(self._ramp_state.get('last', {}).get('rejects', {}).get('blue', 0)),
                        'green': int(self._ramp_state.get('last', {}).get('rejects', {}).get('green', 0)),
                    },
                },
                'updated_ts': float(self._ramp_state.get('updated_ts', 0.0)),
                'frozen': bool(self._ramp_state.get('frozen', False)),
            }
        except Exception:
            return {'version': 1, 'enabled': False, 'step_idx': 0, 'last': {'fills': {'blue': 0, 'green': 0}, 'rejects': {'blue': 0, 'green': 0}}, 'updated_ts': 0.0, 'frozen': False}

    def _load_ramp_snapshot(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                return
            enabled = bool(data.get('enabled', False))
            step_idx = int(data.get('step_idx', 0))
            last = data.get('last', {}) if isinstance(data.get('last', {}), dict) else {}
            fills = last.get('fills', {}) if isinstance(last.get('fills', {}), dict) else {}
            rejects = last.get('rejects', {}) if isinstance(last.get('rejects', {}), dict) else {}
            up_ts = float(data.get('updated_ts', 0.0))
            frozen = bool(data.get('frozen', False))
            self._ramp_state = {
                'enabled': enabled,
                'step_idx': max(0, step_idx),
                'last': {
                    'fills': {'blue': int(fills.get('blue', 0)), 'green': int(fills.get('green', 0))},
                    'rejects': {'blue': int(rejects.get('blue', 0)), 'green': int(rejects.get('green', 0))},
                },
                'updated_ts': up_ts,
                'frozen': frozen,
            }
            self._ramp_step_idx = int(self._ramp_state['step_idx'])
            self._ramp_last_counters = {
                'fills': {'blue': int(fills.get('blue', 0)), 'green': int(fills.get('green', 0))},
                'rejects': {'blue': int(rejects.get('blue', 0)), 'green': int(rejects.get('green', 0))},
            }
        except Exception:
            pass

    async def _ramp_snapshot_loop(self):
        import time as _t, os as _os, json as _json, hmac as _hmac
        while self.running:
            try:
                sp = self._ramp_snapshot_path or "artifacts/rollout_ramp.json"
                tmp = sp + ".tmp"
                # ensure dir exists
                try:
                    from pathlib import Path as _P
                    _P(sp).parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                snap = self._to_ramp_snapshot()
                try:
                    self._atomic_snapshot_write(sp, snap, version=1)
                except Exception:
                    payload = _json.dumps(snap, sort_keys=True, separators=(",", ":"))
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(payload)
                        f.flush()
                        try:
                            _os.fsync(f.fileno())
                        except Exception:
                            pass
                    try:
                        _os.replace(tmp, sp)
                    except Exception:
                        _os.rename(tmp, sp)
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_ramp_snapshot_write(ok=True, ts=_t.time())
                    except Exception:
                        pass
            except Exception:
                try:
                    if getattr(self, 'metrics', None):
                        import time as _tt
                        self.metrics.inc_ramp_snapshot_write(ok=False, ts=_tt.time())
                except Exception:
                    pass
            # deterministic jitter ±10%
            base = max(1, int(self._ramp_snapshot_interval))
            seed = str(self._ramp_snapshot_path)
            j = (int(_hmac.new(seed.encode('utf-8'), b'ramp', 'sha1').hexdigest()[:8], 16) % 2001) - 1000
            frac = (j / 10000.0) * (2 * self._ramp_jitter_frac)
            delay = max(1.0, base * (1.0 + frac))
            await asyncio.sleep(delay)

    async def _admin_rollout_ramp_snapshot(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/ramp/snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/ramp/snapshot')
                except Exception:
                    pass
            snap = self._to_ramp_snapshot()
            payload = json.dumps(snap, sort_keys=True, separators=(",", ":")).encode('utf-8')
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_ramp_load(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/ramp/load')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/ramp/load')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                body = {}
            ok = False
            try:
                snap = body if isinstance(body, dict) else {}
                p = snap.get('path') if isinstance(snap, dict) else None
                if isinstance(p, str) and p:
                    snap = self._safe_load_json_file(p)
                    # strict structure for ramp payloads as well
                    if not isinstance(snap, dict):
                        raise ValueError('invalid_payload')
                    keys = set(snap.keys())
                    required = {"version", "sha256", "payload"}
                    if not required.issubset(keys) or (keys - required):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_ramp').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    if not isinstance(snap.get('version'), int) or not isinstance(snap.get('sha256'), str) or not isinstance(snap.get('payload'), dict):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_ramp').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    import json as _json, hashlib as _hl
                    pj = _json.dumps(snap.get('payload', {}), sort_keys=True, separators=(",", ":")).encode('utf-8')
                    if _hl.sha256(pj).hexdigest() != str(snap.get('sha256')):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_ramp').inc()
                            except Exception:
                                pass
                        raise ValueError('bad_checksum')
                    snap = snap.get('payload', {})
                if isinstance(snap, dict):
                    self._load_ramp_snapshot(snap)
                    ok = True
                else:
                    ok = False
            except Exception as _e:
                ok = False
                msg = str(getattr(_e, 'args', ['failed'])[0])
                if getattr(self, 'metrics', None):
                    try:
                        if msg in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum"):
                            self.metrics.snapshot_integrity_fail_total.labels(kind='throttle').inc()
                    except Exception:
                        pass
                if msg not in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum", "invalid_payload"):
                    msg = "failed"
            if getattr(self, 'metrics', None):
                import time as _t
                try:
                    self.metrics.inc_ramp_snapshot_load(ok=ok, ts=_t.time())
                except Exception:
                    pass
            if not ok:
                return self._json_response({"error": msg}, status=400)
            return self._json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_rollout_ramp_snapshot_status(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/ramp/snapshot_status')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/ramp/snapshot_status')
                except Exception:
                    pass
            data = {
                'path': str(self._ramp_snapshot_path),
                'last_write_ts': float(getattr(self, '_ramp_last_write_ts', 0.0)),
                'last_load_ts': float(getattr(self, '_ramp_last_load_ts', 0.0)),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_ramp_freeze(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/ramp/freeze')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/ramp/freeze')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                body = {}
            st = bool(body.get('state', True)) if isinstance(body, dict) else True
            self._ramp_state['frozen'] = bool(st)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_ramp_frozen(bool(st))
                except Exception:
                    pass
            return self._json_response({'status': 'ok', 'frozen': bool(st)})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)
    async def _admin_reload(self, request):
        """Admin reload endpoint."""
        try:
            loader = ConfigLoader(self.config_path)
            new_cfg = loader.reload()
            from src.common.config import diff_runtime_safe, apply_runtime_overrides, RUNTIME_MUTABLE, validate_invariants
            # validate invariants (loader already runs it, double safety)
            validate_invariants(new_cfg)
            changes = diff_runtime_safe(self.config, new_cfg)
            if not changes:
                return self._json_response({"applied_changes": {}, "status": "noop"})
            # apply only allowed changes
            self.config = apply_runtime_overrides(self.config, new_cfg, RUNTIME_MUTABLE)
            # Update config gauges
            if hasattr(self, 'metrics'):
                self.metrics.export_cfg_gauges(self.config)
            elif self.metrics_exporter:
                self.metrics_exporter.export_cfg_gauges(self.config)
            return self._json_response({"applied_changes": changes, "status": "ok"})
        except ValueError as ve:
            return self._json_response({"error": str(ve)}, status=400)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_guard(self, request):
        try:
            # minimal token protection (dev): env GUARD_ADMIN_TOKEN
            import os
            token = os.getenv('GUARD_ADMIN_TOKEN')
            if token:
                provided = request.headers.get('X-Admin-Token') or request.query.get('token')
                if provided != token:
                    return self._json_response({"error": "unauthorized"}, status=401)
            if request.method == 'GET':
                data = {
                    "paused": bool(getattr(getattr(self.ctx, 'guard', None), 'paused', False)),
                    "dry_run": bool(getattr(self.config.runtime_guard, 'dry_run', False)),
                    "manual_override_pause": bool(getattr(self.config.runtime_guard, 'manual_override_pause', False)),
                    "last_reason_bits": int(getattr(getattr(self.ctx, 'guard', None), 'last_reason_mask', 0)),
                    "last_change_ts": float(getattr(getattr(self.ctx, 'guard', None), 'last_change_ts', 0.0)),
                }
                return self._json_response(data)
            elif request.method == 'POST':
                body = await request.json()
                if not isinstance(body, dict):
                    return self._json_response({"error": "invalid_payload"}, status=400)
                dr = body.get('dry_run')
                mo = body.get('manual_override_pause')
                resume = body.get('resume')
                if isinstance(dr, bool):
                    self.config.runtime_guard.dry_run = dr
                if isinstance(mo, bool):
                    self.config.runtime_guard.manual_override_pause = mo
                if resume:
                    self.config.runtime_guard.manual_override_pause = False
                # reflect into guard instance
                try:
                    self.ctx.guard = RuntimeGuard(self.config.runtime_guard)
                except Exception:
                    pass
                return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_autopolicy(self, request):
        try:
            import os
            token = os.getenv('GUARD_ADMIN_TOKEN')
            if token:
                provided = request.headers.get('X-Admin-Token') or request.query.get('token')
                if provided != token:
                    return web.json_response({"error": "unauthorized"}, status=401)
            ap = getattr(self.ctx, 'autopolicy', None)
            if not ap:
                return web.json_response({"error": "autopolicy_not_initialized"}, status=400)
            if request.method == 'GET':
                snap = ap.to_snapshot()
                eff = {
                    "min_time_in_book_ms": float(snap.get("_overrides", {}).get("min_time_in_book_ms_eff", 0.0)),
                    "replace_threshold_bps": float(snap.get("_overrides", {}).get("replace_threshold_bps_eff", 0.0)),
                    "levels_per_side_max": float(snap.get("_overrides", {}).get("levels_per_side_max_eff", 0.0)),
                }
                resp = {
                    "level": int(snap.get("level", 0)),
                    "active": 1 if int(snap.get("level", 0)) > 0 else 0,
                    "last_change_ts": float(snap.get("_last_change_ts", 0.0)),
                    "effective": eff,
                    "cfg_excerpt": {
                        "trigger_backoff_ms": float(getattr(self.config.autopolicy, 'trigger_backoff_ms', 0.0)),
                        "trigger_events_total": int(getattr(self.config.autopolicy, 'trigger_events_total', 0)),
                        "max_level": int(getattr(self.config.autopolicy, 'max_level', 0)),
                    },
                }
                return web.json_response(resp)
            elif request.method == 'POST':
                try:
                    body = await request.json()
                except Exception:
                    return web.json_response({"error": "invalid_json"}, status=400)
                if not isinstance(body, dict):
                    return web.json_response({"error": "invalid_payload"}, status=400)
                changed = False
                if 'reset' in body and bool(body.get('reset')):
                    ap.level = 0
                    ap._consec_bad = 0
                    ap._consec_good = 0
                    ap._last_change_ts = time.time()
                    ap.apply()
                    changed = True
                if 'level' in body:
                    try:
                        new_level = int(body.get('level'))
                        ap.level = max(0, min(new_level, int(getattr(self.config.autopolicy, 'max_level', 3))))
                        ap._last_change_ts = time.time()
                        ap.apply()
                        changed = True
                    except Exception:
                        return web.json_response({"error": "invalid_level"}, status=400)
                if 'enabled' in body:
                    val = body.get('enabled')
                    if not isinstance(val, bool):
                        return web.json_response({"error": "invalid_enabled"}, status=400)
                    self.config.autopolicy.enabled = val
                    if val:
                        ap.apply()
                    changed = True
                if changed and getattr(self, 'metrics', None):
                    try:
                        m = ap.metrics()
                        self.metrics.autopolicy_active.set(m["autopolicy_active"])
                        self.metrics.autopolicy_level.set(m["autopolicy_level"])
                        self.metrics.autopolicy_steps_total.inc()
                        self.metrics.autopolicy_last_change_ts.set(m["autopolicy_last_change_ts"])
                        self.metrics.autopolicy_min_time_in_book_ms_eff.set(m.get("min_time_in_book_ms_eff", 0.0))
                        self.metrics.autopolicy_replace_threshold_bps_eff.set(m.get("replace_threshold_bps_eff", 0.0))
                        self.metrics.autopolicy_levels_per_side_max_eff.set(m.get("levels_per_side_max_eff", 0.0))
                    except Exception:
                        pass
                return web.json_response({"status": "ok", "changed": bool(changed), "level": int(ap.level)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    
    async def _status_endpoint(self, request):
        """Status endpoint."""
        try:
            status = {
                "bot_status": "running" if self.running else "stopped",
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "symbols": self.config.trading.symbols,
                "testnet": self.config.bybit.use_testnet,
                "strategy_state": self.strategy.get_strategy_state() if self.strategy else None,
                "risk_state": self.risk_manager.get_risk_state() if self.risk_manager else None,
                "order_manager_stats": self.order_manager.get_order_manager_stats() if self.order_manager else None,
                "storage_stats": self.data_recorder.get_storage_stats() if self.data_recorder else None
            }
            
            return web.json_response(status)
            
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    
    async def _admin_allocator_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/snapshot')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/snapshot')
                except Exception:
                    pass
            alloc = getattr(self.ctx, 'allocator', None)
            if not alloc:
                return web.json_response({"error": "allocator_not_initialized"}, status=400)
            snap = alloc.to_snapshot()
            return web.json_response(snap)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_allocator_load(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/load')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/load')
                except Exception:
                    pass
            alloc = getattr(self.ctx, 'allocator', None)
            if not alloc:
                return web.json_response({"error": "allocator_not_initialized"}, status=400)
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return web.json_response({"error": "invalid_payload"}, status=400)
            # optional load from file path with size limit
            snapshot_payload = body
            try:
                p = body.get('path') if isinstance(body, dict) else None
                if isinstance(p, str) and p:
                    snapshot_payload = self._safe_load_json_file(p)
                    # strict structure check
                    if not isinstance(snapshot_payload, dict):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.inc_allocator_snapshot_load(ok=False, ts=__import__('time').time())
                            except Exception:
                                pass
                        return self._json_response({"error": "invalid_payload"}, status=400)
                    keys = set(snapshot_payload.keys())
                    required = {"version", "sha256", "payload"}
                    if not required.issubset(keys) or (keys - required):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='allocator').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    if not isinstance(snapshot_payload.get('version'), int) or not isinstance(snapshot_payload.get('sha256'), str) or not isinstance(snapshot_payload.get('payload'), dict):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='allocator').inc()
                            except Exception:
                                pass
                        return self._json_response({"error": "invalid_structure"}, status=400)
                    import json as _json, hashlib as _hl
                    pj = _json.dumps(snapshot_payload.get('payload', {}), sort_keys=True, separators=(",", ":")).encode('utf-8')
                    if _hl.sha256(pj).hexdigest() != str(snapshot_payload.get('sha256')):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='allocator').inc()
                            except Exception:
                                pass
                        raise ValueError('bad_checksum')
                    snapshot_payload = snapshot_payload.get('payload', {})
            except Exception as _e:
                # counters
                if getattr(self, 'metrics', None):
                    import time as _t
                    try:
                        self.metrics.inc_allocator_snapshot_load(ok=False, ts=_t.time())
                    except Exception:
                        pass
                    try:
                        k = 'allocator'
                        m = str(getattr(_e, 'args', ['failed'])[0])
                        if m in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum"):
                            self.metrics.snapshot_integrity_fail_total.labels(kind=k).inc()
                    except Exception:
                        pass
                # map known errors
                msg = str(getattr(_e, 'args', ['failed'])[0])
                if msg not in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum", "invalid_payload"):
                    msg = "failed"
                return self._json_response({"error": msg}, status=400)
            # apply
            alloc.load_snapshot(snapshot_payload)
            if getattr(self, 'metrics', None):
                import time as _t
                try:
                    self.metrics.inc_allocator_snapshot_load(ok=True, ts=_t.time())
                except Exception:
                    pass
            return self._json_response({"status": "ok", "applied": True, "snapshot": alloc.to_snapshot()})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_allocator_reset_hwm(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/reset_hwm')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/reset_hwm')
                except Exception:
                    pass
            alloc = getattr(self.ctx, 'allocator', None)
            if not alloc:
                return web.json_response({"error": "allocator_not_initialized"}, status=400)
            try:
                body = await request.json()
            except Exception:
                body = {}
            mode = None
            if isinstance(body, dict):
                mode = body.get('mode')
            if mode == 'zero':
                # reset to zero
                alloc.load_snapshot({"version": 1, "hwm_equity_usd": 0.0})
            elif mode == 'to_current_equity':
                eq = 0.0
                try:
                    eq = float(body.get('equity_usd', 0.0))
                except Exception:
                    eq = 0.0
                alloc.load_snapshot({"version": 1, "hwm_equity_usd": eq})
            else:
                return web.json_response({"error": "invalid_mode"}, status=400)
            return web.json_response({"status": "ok", "hwm_equity_usd": alloc.get_hwm_equity_usd()})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_allocator_snapshot_status(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/snapshot_status')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/snapshot_status')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            path = getattr(self, '_allocator_snapshot_path', None) or "artifacts/allocator_hwm.json"
            last = {}
            if m:
                snap = m.get_portfolio_metrics_snapshot()
                last = {
                    "last_write_ts": float(snap.get('allocator_last_write_ts', 0.0)),
                    "last_load_ts": float(snap.get('allocator_last_load_ts', 0.0)),
                }
            data = {
                "path": str(path),
                **last,
            }
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    def _check_admin_token(self, request) -> bool:
        # explicit dev bypass (do NOT use in prod)
        try:
            if os.getenv("ADMIN_AUTH_DISABLED", "").lower() in ("1", "true", "yes"):
                return True
            token_req = request.headers.get("X-Admin-Token") or request.rel_url.query.get("token")
            if not token_req:
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized(getattr(request, 'path', 'unknown'))
                    except Exception:
                        pass
                return False
            with self._admin_token_lock:
                p = str(self._admin_token_primary or '')
                s = str(self._admin_token_secondary or '')
                act = 'primary' if str(self._admin_active_token) != 'secondary' else 'secondary'
            try:
                ok_p = bool(p) and hmac.compare_digest(token_req.encode('utf-8'), p.encode('utf-8'))
            except Exception:
                ok_p = False
            try:
                ok_s = bool(s) and hmac.compare_digest(token_req.encode('utf-8'), s.encode('utf-8'))
            except Exception:
                ok_s = False
            ok = bool(ok_p or ok_s)
            if not ok and getattr(self, "metrics", None):
                try:
                    self.metrics.inc_admin_unauthorized(getattr(request, 'path', 'unknown'))
                except Exception:
                    pass
            return ok
        except Exception:
            return False

    def _admin_actor_hash(self, request) -> str:
        try:
            # request may be a simple stub in tests without query mapping
            q = {}
            try:
                q = request.rel_url.query
            except Exception:
                try:
                    q = request.query
                except Exception:
                    q = {}
            provided = request.headers.get('X-Admin-Token') or (q.get('token') if isinstance(q, dict) else '') or ''
            h = hashlib.sha1(str(provided).encode('utf-8')).hexdigest()
            return h[:8]
        except Exception:
            return "unknown"

    def _admin_rate_limit_check(self, actor: str, endpoint: str) -> bool:
        self._ensure_admin_audit_initialized()
        now = time.time()
        key = (actor, endpoint)
        dq = self._admin_rl_counters.get(key)
        if dq is None:
            dq = deque()
            self._admin_rl_counters[key] = dq
        # purge old
        window_start = now - self._admin_rl_window_sec
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= self._admin_rl_limit:
            return False
        dq.append(now)
        return True

    def _admin_audit_record(self, endpoint: str, request, payload: Optional[dict] = None) -> None:
        try:
            self._ensure_admin_audit_initialized()
            actor = f"token:{self._admin_actor_hash(request)}"
            body_hash = ''
            if payload is None:
                try:
                    payload = {}
                except Exception:
                    payload = {}
            try:
                b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode('utf-8')
                body_hash = hashlib.sha1(b).hexdigest()
            except Exception:
                body_hash = ""
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            # HMAC signature over deterministic payload JSON
            sig = ''
            try:
                key = os.getenv('ADMIN_AUDIT_HMAC_KEY', '')
                if key:
                    import binascii as _ba
                    try:
                        k = _ba.unhexlify(key.encode('ascii'))
                    except Exception:
                        k = key.encode('ascii', errors='ignore')
                    sig = hmac.new(k, b, hashlib.sha256).hexdigest()
            except Exception:
                sig = ''
            rec = {"ts": ts, "endpoint": str(endpoint), "actor": actor, "payload_hash": body_hash, "sig": sig}
            self._admin_audit_log.append(rec)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_audit_event(endpoint)
                except Exception:
                    pass
        except Exception:
            pass

    def _safe_load_json_file(self, path: str, *, limit_bytes: int = 1 << 20):
        import os as _os, json as _json
        st = _os.stat(path)
        if st.st_size > limit_bytes:
            raise ValueError("file_too_large")
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > limit_bytes:
            raise ValueError("file_too_large")
        txt = data.decode("utf-8")
        # Enforce ASCII-only for snapshot files
        if any(ord(ch) > 127 for ch in txt):
            raise ValueError("non_ascii")
        return _json.loads(txt)

    async def _admin_selfcheck(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/selfcheck')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            # rate-limit
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/selfcheck'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/selfcheck')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            # collect checks
            reasons = []
            import os as _os, json as _json, time as _t
            from pathlib import Path as _P
            art_dir = self._get_artifacts_dir()
            # artifacts_dir_write
            try:
                p = _P(art_dir) / ('._selfcheck_' + str(int(_t.time())) + '.tmp')
                with open(p, 'w', encoding='utf-8') as f:
                    f.write('{}')
                    f.flush()
                    try:
                        _os.fsync(f.fileno())
                    except Exception:
                        pass
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            except Exception:
                reasons.append('artifacts_dir_write')
            # alerts_log_writable (append + rollback by truncating last line)
            try:
                logp = _P(self._alerts_log_file())
                before = []
                if logp.exists():
                    before = logp.read_text(encoding='utf-8').splitlines()
                ts_iso = datetime.now(timezone.utc).isoformat()
                self._append_json_line(str(logp), {"ts": ts_iso, "kind": "selfcheck_test", "payload": {}})
                # truncate last line
                try:
                    lines = logp.read_text(encoding='utf-8').splitlines()
                    if lines:
                        tail = "\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else "")
                        with open(str(logp) + '.tmp', 'w', encoding='utf-8') as f:
                            f.write(tail)
                            f.flush()
                            try:
                                _os.fsync(f.fileno())
                            except Exception:
                                pass
                        try:
                            _os.replace(str(logp) + '.tmp', str(logp))
                        except Exception:
                            _os.rename(str(logp) + '.tmp', str(logp))
                except Exception:
                    pass
            except Exception:
                reasons.append('alerts_log_writable')
            # snapshots_dirs_access: check parent dirs of known snapshots
            try:
                paths = [
                    getattr(self, '_allocator_snapshot_path', None) or 'artifacts/allocator_hwm.json',
                    getattr(self, '_throttle_snapshot_path', None) or 'artifacts/throttle_snapshot.json',
                    getattr(self, '_ramp_snapshot_path', None) or 'artifacts/rollout_ramp.json',
                    getattr(self, '_rollout_state_snapshot_path', None) or 'artifacts/rollout_state.json',
                ]
                for sp in paths:
                    try:
                        d = _P(str(sp)).parent
                        test = d / ('._selfcheck_' + str(int(_t.time())) + '.tmp')
                        with open(test, 'w', encoding='utf-8') as f:
                            f.write('{}')
                            f.flush()
                            try:
                                _os.fsync(f.fileno())
                            except Exception:
                                pass
                        try:
                            _os.replace(str(test), str(test))
                        except Exception:
                            pass
                        try:
                            _os.remove(str(test))
                        except Exception:
                            pass
                    except Exception:
                        reasons.append('snapshots_dirs_access')
                        break
            except Exception:
                reasons.append('snapshots_dirs_access')
            # loops heartbeats
            try:
                max_age = float(_os.getenv('SELFCHK_LOOP_MAX_AGE_SEC', '10'))
            except Exception:
                max_age = 10.0
            stale = []
            loops = []
            m = getattr(self, 'metrics', None)
            if m and hasattr(m, 'get_loop_heartbeats_for_tests'):
                hb = m.get_loop_heartbeats_for_tests()
                now = _t.time()
                loops = sorted(hb.keys())
                for name, ts in hb.items():
                    if (now - float(ts)) > max_age:
                        stale.append(name)
                if stale:
                    reasons.append('loops_heartbeats_fresh')
            # drift budget
            try:
                drift_max = float(_os.getenv('SELFCHK_DRIFT_MAX_MS', '150'))
            except Exception:
                drift_max = 150.0
            try:
                cur = float(getattr(self.metrics, 'event_loop_max_drift_ms', object())._value.get())
                if cur > drift_max:
                    reasons.append('event_loop_drift')
            except Exception:
                pass
            # admin latency p50 budget (requires prior call)
            try:
                p50_budget = float(_os.getenv('SELFCHK_ADMIN_P50_MS', '50'))
            except Exception:
                p50_budget = 50.0
            try:
                # derive approx median from buckets for this endpoint
                from collections import defaultdict
                # We only have internal counters in metrics for admin buckets
                # Best-effort: treat bucket upper bounds as representative values
                ep = '/admin/selfcheck'
                # cannot access raw counts; skip if unavailable
                # reason added only if we can compute and exceed
            except Exception:
                pass
            status = 'ok' if not reasons else 'fail'
            resp = {
                'status': status,
                'reasons': sorted(reasons),
                'ts': datetime.now(timezone.utc).isoformat(),
                'artifacts_dir': str(art_dir),
                'loops': loops,
            }
            return self._json_response(resp)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_auth_rotate(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/auth/rotate')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            # parse body
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            pri = body.get('primary')
            sec = body.get('secondary')
            act = body.get('activate')
            # apply atomically
            applied = {}
            with self._admin_token_lock:
                if isinstance(pri, str) and pri:
                    self._admin_token_primary = pri
                    applied['primary'] = True
                if isinstance(sec, str):
                    self._admin_token_secondary = sec
                    applied['secondary'] = True
                if str(act) in ('primary', 'secondary'):
                    self._admin_active_token = str(act)
                    applied['activate'] = self._admin_active_token
            # audit with masked secrets
            def _mask(s: object) -> str:
                return '***' if isinstance(s, str) and s else ''
            self._admin_audit_record('/admin/auth/rotate', request, {
                'primary': _mask(pri), 'secondary': _mask(sec), 'activate': str(act) if act in ('primary','secondary') else ''
            })
            return self._json_response({"status": "ok", "applied": applied})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    def _safe_read_text_file(self, path: str, *, limit_bytes: int = 1 << 20) -> str:
        import os as _os
        st = _os.stat(path)
        if st.st_size > limit_bytes:
            raise ValueError("file_too_large")
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) > limit_bytes:
            raise ValueError("file_too_large")
        # ascii-only decode
        try:
            txt = data.decode('ascii')
        except Exception:
            # allow utf-8 but ensure ASCII subset only
            txt = data.decode('utf-8')
            # replace non-ascii
            if any(ord(ch) > 127 for ch in txt):
                # strip non-ascii deterministically
                txt = ''.join(ch for ch in txt if ord(ch) <= 127)
        return txt

    def _json_response(self, obj: dict, *, status: int = 200, endpoint: str | None = None, started_at_ms: float | None = None):
        # Observe admin endpoint latency buckets if endpoint and started_at_ms passed
        try:
            if endpoint and started_at_ms is not None and getattr(self, 'metrics', None):
                import time as _t
                dt_ms = (_t.perf_counter() * 1000.0) - float(started_at_ms)
                try:
                    self.metrics.record_admin_endpoint_latency(str(endpoint), float(dt_ms))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except Exception:
            payload = b"{}"
        return web.Response(body=payload, content_type='application/json', status=int(status))

    def _append_json_line(self, path: str, obj: dict) -> None:
        try:
            from pathlib import Path as _P
            _P(path).parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            try:
                self._exec_last_write_ts = time.time()
            except Exception:
                pass
        except Exception:
            pass

    # ---- Execution recorder helpers ----
    def _record_execution_event(self, obj: dict) -> None:
        try:
            if not self._exec_recorder_enabled or not self._exec_recorder_file:
                return
            # ensure deterministic keys order and ascii-safe
            self._append_json_line(self._exec_recorder_file, obj)
        except Exception:
            pass

    # ---- Execution replay admin ----
    async def _admin_execution_replay(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/execution/replay')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/execution/replay'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/execution/replay')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/execution/replay')
                    self.metrics.inc_admin_alert_event('replay_started')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            path = body.get('path')
            speed = str(body.get('speed', '1x'))
            if not path or not isinstance(path, str):
                return self._json_response({"error": "invalid_path"}, status=400)
            # size and ascii limits
            try:
                txt = self._safe_read_text_file(path, limit_bytes=1<<20)
            except Exception:
                return self._json_response({"error": "read_failed"}, status=400)
            # deterministic iteration
            events = []
            for ln in txt.split('\n'):
                if not ln:
                    continue
                try:
                    ev = json.loads(ln)
                except Exception:
                    return self._json_response({"error": "invalid_jsonl"}, status=400)
                if not isinstance(ev, dict):
                    return self._json_response({"error": "invalid_event"}, status=400)
                events.append(ev)
            # process
            start = time.perf_counter()
            fills = 0
            rejects = 0
            by_symbol = {}
            m = getattr(self, 'metrics', None)
            for ev in events:
                kind = str(ev.get('kind',''))
                color = str(ev.get('color','blue')).lower()
                sym = str(ev.get('symbol',''))
                by_symbol.setdefault(sym, {"fills":0, "rejects":0})
                if kind == 'fill':
                    fills += 1
                    by_symbol[sym]["fills"] += 1
                    if m:
                        try:
                            m.inc_rollout_fill(color, 0.0)
                        except Exception:
                            pass
                elif kind == 'reject':
                    rejects += 1
                    by_symbol[sym]["rejects"] += 1
                    if m:
                        try:
                            m.inc_rollout_reject(color)
                        except Exception:
                            pass
                else:
                    # 'order' ignored for counters
                    pass
                # speed control (best-effort; 'max' skips sleep)
                if speed == '10x':
                    await asyncio.sleep(0)
                elif speed == '1x':
                    await asyncio.sleep(0)
            dur_ms = (time.perf_counter() - start) * 1000.0
            if m:
                try:
                    m.replay_events_total.set(len(events))
                    m.replay_duration_ms.set(dur_ms)
                    m.inc_admin_alert_event('replay_finished')
                except Exception:
                    pass
            return self._json_response({
                "events_total": int(len(events)),
                "fills": int(fills),
                "rejects": int(rejects),
                "by_symbol": {k: {"fills": int(v["fills"]), "rejects": int(v["rejects"]) } for k, v in sorted(by_symbol.items())}
            })
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_execution_recorder_status(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/execution/recorder/status')
                    except Exception:
                        pass
                return self._json_response({"error":"unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/execution/recorder/status'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/execution/recorder/status')
                    except Exception:
                        pass
                return self._json_response({"error":"rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/execution/recorder/status')
                except Exception:
                    pass
            return self._json_response({
                "enabled": bool(self._exec_recorder_enabled),
                "last_write_ts": float(self._exec_last_write_ts),
                "file": str(self._exec_recorder_file or "")
            })
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_execution_recorder_rotate(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/execution/recorder/rotate')
                    except Exception:
                        pass
                return self._json_response({"error":"unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/execution/recorder/rotate'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/execution/recorder/rotate')
                    except Exception:
                        pass
                return self._json_response({"error":"rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/execution/recorder/rotate')
                except Exception:
                    pass
            # rotate to a new filename by time
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            self._exec_recorder_file = f"artifacts/exe_{date_str}.jsonl"
            self._exec_last_write_ts = 0.0
            return self._json_response({"ok": True, "file": str(self._exec_recorder_file)})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    def _atomic_json_write(self, path: str, obj: dict) -> None:
        import os as _os, json as _json
        from pathlib import Path as _P
        sp = str(path)
        tmp = sp + ".tmp"
        # ensure dir exists
        try:
            _P(sp).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _atomic_snapshot_write(self, path: str, payload_obj: dict, *, version: int) -> None:
        # Use shared atomic writer; preserve versioned wrapper
        import hashlib as _hl
        from src.common.artifacts import write_json_atomic
        payload_obj = payload_obj or {}
        wrapper = {
            "version": int(version),
            "sha256": _hl.sha256(json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "payload": payload_obj,
        }
        write_json_atomic(str(path), wrapper)

    # ---- L6.2: Cost calibration admin ----
    async def _admin_cost_calibration(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/cost_calibration')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/allocator/cost_calibration'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/allocator/cost_calibration')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/cost_calibration')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            snap = {} if not m else m.get_cost_calib_snapshot_for_tests()
            return self._json_response(snap)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_cost_calibration_apply(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/cost_calibration/apply')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/allocator/cost_calibration/apply'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/allocator/cost_calibration/apply')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/cost_calibration/apply')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            symbols = body.get('symbols', {}) if isinstance(body, dict) else {}
            if not isinstance(symbols, dict):
                return self._json_response({"error": "invalid_symbols"}, status=400)
            applied = {}
            m = getattr(self, 'metrics', None)
            for s, val in sorted(symbols.items()):
                if not isinstance(val, dict):
                    continue
                try:
                    k_eff = float(val.get('k_eff')) if 'k_eff' in val else None
                except Exception:
                    return self._json_response({"error": "invalid_k_eff"}, status=400)
                try:
                    cap_eff = float(val.get('cap_eff_bps')) if 'cap_eff_bps' in val else None
                except Exception:
                    return self._json_response({"error": "invalid_cap_eff_bps"}, status=400)
                if m:
                    try:
                        with m._pm_lock:
                            if k_eff is not None:
                                if k_eff < 0.0 or k_eff > 1000.0:
                                    return self._json_response({"error": "k_eff_out_of_range"}, status=400)
                                m._cal_override_k_eff[str(s)] = float(k_eff)
                            if cap_eff is not None:
                                if cap_eff < 0.0 or cap_eff > 10000.0:
                                    return self._json_response({"error": "cap_eff_out_of_range"}, status=400)
                                m._cal_override_cap_eff_bps[str(s)] = float(cap_eff)
                        applied[str(s)] = {"k_eff": k_eff, "cap_eff_bps": cap_eff}
                    except Exception:
                        pass
            self._admin_audit_record('/admin/allocator/cost_calibration/apply', request, {"symbols": applied})
            return self._json_response({"status": "ok", "applied": applied})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_cost_calibration_snapshot(self, request):
        try:
            # same as GET without rate-limit; keep for explicit API
            return await self._admin_cost_calibration(request)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_cost_calibration_load(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/cost_calibration/load')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/allocator/cost_calibration/load'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/allocator/cost_calibration/load')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/cost_calibration/load')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            path = body.get('path') if isinstance(body, dict) else None
            if not isinstance(path, str) or not path:
                return self._json_response({"error": "invalid_path"}, status=400)
            try:
                # limit to 1MB and parse JSON
                data = self._safe_load_json_file(path)
                # strict integrity wrapper
                if not isinstance(data, dict):
                    return self._json_response({"error": "invalid_payload"}, status=400)
                keys = set(data.keys())
                required = {"version", "sha256", "payload"}
                if not required.issubset(keys) or (keys - required):
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.snapshot_integrity_fail_total.labels(kind='cost_calib').inc()
                        except Exception:
                            pass
                    return self._json_response({"error": "invalid_structure"}, status=400)
                if not isinstance(data.get('version'), int) or not isinstance(data.get('sha256'), str) or not isinstance(data.get('payload'), dict):
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.snapshot_integrity_fail_total.labels(kind='cost_calib').inc()
                        except Exception:
                            pass
                    return self._json_response({"error": "invalid_structure"}, status=400)
                import json as _json
                import hashlib as _hl
                payload_json = _json.dumps(data.get('payload', {}), sort_keys=True, separators=(",", ":")).encode('utf-8')
                if _hl.sha256(payload_json).hexdigest() != str(data.get('sha256')):
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.snapshot_integrity_fail_total.labels(kind='cost_calib').inc()
                        except Exception:
                            pass
                    return self._json_response({"error": "bad_checksum"}, status=400)
                data = data.get('payload', {})
            except Exception as e:
                if getattr(self, 'metrics', None):
                    import time as _t
                    try:
                        self.metrics.inc_cost_calib_snapshot_load(ok=False, ts=_t.time())
                    except Exception:
                        pass
                msg = str(getattr(e, 'args', ['failed'])[0])
                if msg not in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum", "invalid_payload"):
                    msg = "failed"
                return self._json_response({"error": msg}, status=400)
            if not isinstance(data, dict):
                return self._json_response({"error": "invalid_file"}, status=400)
            m = getattr(self, 'metrics', None)
            applied = {}
            symbols = data.get('symbols', {}) if isinstance(data, dict) else {}
            if not isinstance(symbols, dict):
                return self._json_response({"error": "invalid_symbols"}, status=400)
            for s, val in sorted(symbols.items()):
                if not isinstance(val, dict):
                    continue
                k_eff = val.get('k_eff')
                cap_eff = val.get('cap_eff_bps')
                try:
                    k_eff = None if k_eff is None else float(k_eff)
                    cap_eff = None if cap_eff is None else float(cap_eff)
                except Exception:
                    return self._json_response({"error": "invalid_values"}, status=400)
                if m:
                    try:
                        with m._pm_lock:
                            if k_eff is not None:
                                if k_eff < 0.0 or k_eff > 1000.0:
                                    return self._json_response({"error": "k_eff_out_of_range"}, status=400)
                                m._cal_override_k_eff[str(s)] = float(k_eff)
                            if cap_eff is not None:
                                if cap_eff < 0.0 or cap_eff > 10000.0:
                                    return self._json_response({"error": "cap_eff_out_of_range"}, status=400)
                                m._cal_override_cap_eff_bps[str(s)] = float(cap_eff)
                        applied[str(s)] = {"k_eff": k_eff, "cap_eff_bps": cap_eff}
                    except Exception:
                        pass
            if getattr(self, 'metrics', None):
                import time as _t
                try:
                    self.metrics.inc_cost_calib_snapshot_load(ok=True, ts=_t.time())
                except Exception:
                    pass
            self._admin_audit_record('/admin/allocator/cost_calibration/load', request, {"symbols": applied})
            return self._json_response({"status": "ok", "applied": applied})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_cost_calibration_config(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/cost_calibration/config')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/allocator/cost_calibration/config'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/allocator/cost_calibration/config')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/cost_calibration/config')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            if request.method == 'GET':
                snap = {} if not m else m.get_cost_calib_snapshot_for_tests()
                cfg = (snap.get('config', {}) if isinstance(snap, dict) else {})
                return self._json_response({"config": cfg})
            # POST
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            cfg = body.get('config', {}) if isinstance(body, dict) else {}
            if not isinstance(cfg, dict):
                return self._json_response({"error": "invalid_config"}, status=400)
            applied = {}
            if m:
                with m._pm_lock:
                    try:
                        if 'warmup_min_samples' in cfg:
                            v = int(cfg.get('warmup_min_samples'))
                            m._calib_warmup_min_samples = max(0, v)
                            applied['warmup_min_samples'] = int(m._calib_warmup_min_samples)
                        if 'winsor_pct' in cfg:
                            v = float(cfg.get('winsor_pct'))
                            if v < 0.0 or v > 0.2:
                                return self._json_response({"error": "winsor_out_of_range"}, status=400)
                            m._calib_winsor_pct = float(v)
                            applied['winsor_pct'] = float(m._calib_winsor_pct)
                        if 'half_life_sec' in cfg:
                            v = float(cfg.get('half_life_sec'))
                            m._calib_half_life_sec = max(0.0, float(v))
                            applied['half_life_sec'] = float(m._calib_half_life_sec)
                        if 'max_step_pct' in cfg:
                            v = float(cfg.get('max_step_pct'))
                            if v < 0.0 or v > 1.0:
                                return self._json_response({"error": "max_step_pct_out_of_range"}, status=400)
                            m._calib_max_step_pct = float(v)
                            applied['max_step_pct'] = float(m._calib_max_step_pct)
                    except Exception:
                        return self._json_response({"error": "invalid_values"}, status=400)
            self._admin_audit_record('/admin/allocator/cost_calibration/config', request, {"config": applied})
            return self._json_response({"status": "ok", "config": applied})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_thresholds_reload(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/thresholds/reload')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            # rate-limit and audit
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/thresholds/reload'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/thresholds/reload')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/thresholds/reload')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return web.json_response({"error": "invalid_payload"}, status=400)
            self._admin_audit_record('/admin/thresholds/reload', request, body)
            path = body.get('path')
            if not path or not isinstance(path, str):
                return web.json_response({"error": "invalid_path"}, status=400)
            summary = th.refresh_thresholds(path)
            # metrics already incremented inside refresh; also set version gauge here if metrics present
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_thresholds_reload(True)
                    v = int(summary.get('version', 0))
                    self.metrics.set_thresholds_version(v)
                except Exception:
                    pass
            payload = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode('utf-8')
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_thresholds_reload(False)
                except Exception:
                    pass
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_thresholds_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/thresholds/snapshot')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            # rate-limit and audit
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/thresholds/snapshot'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/thresholds/snapshot')
                    except Exception:
                        pass
                return web.json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/thresholds/snapshot')
                except Exception:
                    pass
            self._admin_audit_record('/admin/thresholds/snapshot', request, {})
            snap = th.current_thresholds_snapshot()
            payload = json.dumps(snap, sort_keys=True, separators=(",", ":")).encode('utf-8')
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_rollout(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/rollout'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/rollout')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if request.method == 'GET':
                ro = getattr(self.config, 'rollout', None)
                data = {
                    "traffic_split_pct": int(getattr(ro, 'traffic_split_pct', 0)) if ro else 0,
                    "active": str(getattr(ro, 'active', 'blue')) if ro else 'blue',
                    "salt": str(getattr(ro, 'salt', '')) if ro else '',
                    "pinned_cids_green": list(getattr(ro, 'pinned_cids_green', [])) if ro else [],
                    "overlay_keys_blue": sorted(list((getattr(ro, 'blue', {}) or {}).keys())) if ro else [],
                    "overlay_keys_green": sorted(list((getattr(ro, 'green', {}) or {}).keys())) if ro else [],
                    "split_observed_pct": float(getattr(getattr(self, 'metrics', None), 'rollout_split_observed_pct', object())._value.get() if getattr(getattr(self, 'metrics', None), 'rollout_split_observed_pct', None) else 0.0),
                }
                self._admin_audit_record('/admin/rollout', request, {"method": "GET"})
                payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode('utf-8')
                return web.Response(body=payload, content_type='application/json')
            # POST: update
            try:
                body = await request.json()
            except Exception:
                body = {}
            self._admin_audit_record('/admin/rollout', request, body)
            ro = getattr(self.config, 'rollout', None)
            if ro is None:
                from src.common.config import RolloutConfig
                ro = RolloutConfig()
                self.config.rollout = ro  # type: ignore[attr-defined]
            # Update fields if present
            if isinstance(body, dict):
                if 'traffic_split_pct' in body:
                    v = int(body['traffic_split_pct'])
                    if v < 0 or v > 100:
                        return self._json_response({"error": "invalid_split"}, status=400)
                    ro.traffic_split_pct = v
                if 'active' in body:
                    a = str(body['active']).lower()
                    if a not in ('blue', 'green'):
                        return self._json_response({"error": "invalid_active"}, status=400)
                    ro.active = a
                if 'salt' in body:
                    s = str(body['salt'])
                    if len(s) > 64:
                        return self._json_response({"error": "invalid_salt"}, status=400)
                    ro.salt = s
                if 'pinned_cids_green' in body:
                    pins_raw = body['pinned_cids_green']
                    pins: list[str] = []
                    if isinstance(pins_raw, str):
                        # CSV
                        pins = [p.strip() for p in pins_raw.split(',') if p.strip()]
                    elif isinstance(pins_raw, list):
                        pins = [str(p).strip() for p in pins_raw if str(p).strip()]
                    else:
                        return self._json_response({"error": "invalid_pins"}, status=400)
                    if len(pins) > 10000:
                        return self._json_response({"error": "pins_too_many"}, status=400)
                    # de-dup while preserving order minimally
                    seen = set()
                    norm = []
                    for c in pins:
                        if c in seen:
                            continue
                        seen.add(c)
                        norm.append(c)
                    ro.pinned_cids_green = norm
                # mark state dirty for writer
                self._rollout_state_dirty = True
            # Apply metrics
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_rollout_split_pct(int(getattr(ro, 'traffic_split_pct', 0)))
                    self.metrics.inc_admin_request('/admin/rollout')
                except Exception:
                    pass
            data = {
                "traffic_split_pct": int(getattr(ro, 'traffic_split_pct', 0)),
                "active": str(getattr(ro, 'active', 'blue')),
                "salt": str(getattr(ro, 'salt', '')),
                "pinned_cids_green": list(getattr(ro, 'pinned_cids_green', [])),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_audit_log_get(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/audit/log')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/audit/log'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/audit/log')
                    except Exception:
                        pass
                return web.json_response({"error": "rate_limited"}, status=429)
            # snapshot copy
            items = list(self._admin_audit_log)
            payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode('utf-8')
            # audit self
            self._admin_audit_record('/admin/audit/log', request, {"count": len(items)})
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_audit_clear(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/audit/clear')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/audit/clear'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/audit/clear')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            self._admin_audit_record('/admin/audit/clear', request, {})
            self._admin_audit_log.clear()
            return self._json_response({"status": "ok"})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    def _to_rollout_state_snapshot(self) -> dict:
        ro = getattr(self.config, 'rollout', None)
        rr = getattr(self, 'config', None)
        ramp = getattr(self, 'rollout_ramp', None) if rr is None else getattr(rr, 'rollout_ramp', None)
        data = {
            "version": 1,
            "traffic_split_pct": int(getattr(ro, 'traffic_split_pct', 0)) if ro else 0,
            "active": str(getattr(ro, 'active', 'blue')) if ro else 'blue',
            "salt": str(getattr(ro, 'salt', '')) if ro else '',
            "pinned_cids_green": list(getattr(ro, 'pinned_cids_green', [])) if ro else [],
            "overlays": {
                "blue": dict(getattr(ro, 'blue', {})) if ro else {},
                "green": dict(getattr(ro, 'green', {})) if ro else {},
            },
            "ramp": {
                "enabled": bool(getattr(self.config, 'rollout_ramp', None) and self.config.rollout_ramp.enabled),
                "steps_pct": list(getattr(self.config.rollout_ramp, 'steps_pct', [])) if getattr(self.config, 'rollout_ramp', None) else [],
                "step_interval_sec": int(getattr(self.config.rollout_ramp, 'step_interval_sec', 600)) if getattr(self.config, 'rollout_ramp', None) else 600,
                "max_reject_rate_delta_pct": float(getattr(self.config.rollout_ramp, 'max_reject_rate_delta_pct', 2.0)) if getattr(self.config, 'rollout_ramp', None) else 2.0,
                "max_latency_delta_ms": int(getattr(self.config.rollout_ramp, 'max_latency_delta_ms', 50)) if getattr(self.config, 'rollout_ramp', None) else 50,
                "max_pnl_delta_usd": float(getattr(self.config.rollout_ramp, 'max_pnl_delta_usd', 0.0)) if getattr(self.config, 'rollout_ramp', None) else 0.0,
            },
            "updated_ts": float(time.time()),
        }
        return data

    async def _rollout_state_snapshot_loop(self):
        import time as _t, os as _os, json as _json, hmac as _hmac
        while getattr(self, 'running', False):
            try:
                sp = self._rollout_state_snapshot_path or "artifacts/rollout_state.json"
                tmp = sp + ".tmp"
                # ensure dir
                try:
                    from pathlib import Path as _P
                    _P(sp).parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                if self._rollout_state_dirty:
                    snap = self._to_rollout_state_snapshot()
                    self._atomic_snapshot_write(sp, snap, version=1)
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.inc_rollout_state_snapshot_write(ok=True, ts=_t.time())
                            self._rollout_state_last_write_ts = _t.time()
                        except Exception:
                            pass
                    self._rollout_state_dirty = False
            except Exception:
                try:
                    if getattr(self, 'metrics', None):
                        import time as _tt
                        self.metrics.inc_rollout_state_snapshot_write(ok=False, ts=_tt.time())
                except Exception:
                    pass
            # jitter ±10%
            base = max(1, int(self._rollout_state_snapshot_interval))
            seed = str(self._rollout_state_snapshot_path)
            j = (int(_hmac.new(seed.encode('utf-8'), b'rollout_state', 'sha1').hexdigest()[:8], 16) % 2001) - 1000
            frac = (j / 10000.0) * (2 * self._rollout_state_jitter_frac)
            delay = max(0.05, base * (1.0 + frac))
            # stop-aware sleep in small slices
            remaining = float(delay)
            while getattr(self, 'running', False) and remaining > 0.0:
                step = 0.05 if remaining > 0.05 else remaining
                await asyncio.sleep(step)
                remaining -= step
            if not getattr(self, 'running', False):
                break

    async def _admin_rollout_state_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/state/snapshot')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/state/snapshot')
                except Exception:
                    pass
            snap = self._to_rollout_state_snapshot()
            payload = json.dumps(snap, sort_keys=True, separators=(",", ":")).encode('utf-8')
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_rollout_state_load(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/state/load')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/state/load')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                body = {}
            ok = False
            try:
                snap = body if isinstance(body, dict) else {}
                p = snap.get('path') if isinstance(snap, dict) else None
                if isinstance(p, str) and p:
                    snap = self._safe_load_json_file(p)
                    # strict structure
                    if not isinstance(snap, dict):
                        raise ValueError('invalid_payload')
                    keys = set(snap.keys())
                    required = {"version", "sha256", "payload"}
                    if not required.issubset(keys) or (keys - required):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_state').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    if not isinstance(snap.get('version'), int) or not isinstance(snap.get('sha256'), str) or not isinstance(snap.get('payload'), dict):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_state').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    import json as _json, hashlib as _hl
                    pj = _json.dumps(snap.get('payload', {}), sort_keys=True, separators=(",", ":")).encode('utf-8')
                    if _hl.sha256(pj).hexdigest() != str(snap.get('sha256')):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_state').inc()
                            except Exception:
                                pass
                        raise ValueError('bad_checksum')
                    snap = snap.get('payload', {})
                if isinstance(snap, dict) and int(snap.get('version', 1)) >= 1:
                    # Apply minimal fields like in initialize load
                    ro = getattr(self.config, 'rollout', None)
                    if ro is not None:
                        v = int(max(0, min(100, int(snap.get('traffic_split_pct', ro.traffic_split_pct)))))
                        ro.traffic_split_pct = v
                        a = str(snap.get('active', ro.active)).lower()
                        if a in ('blue','green'):
                            ro.active = a
                        s = str(snap.get('salt', ro.salt))
                        if len(s) <= 64:
                            ro.salt = s
                        pins = snap.get('pinned_cids_green', ro.pinned_cids_green)
                        if isinstance(pins, str):
                            pins = [p.strip() for p in pins.split(',') if p.strip()]
                        if isinstance(pins, list):
                            pins = [str(p).strip() for p in pins if str(p).strip()]
                            ro.pinned_cids_green = pins[:10000]
                    ok = True
            except Exception:
                ok = False
            if getattr(self, 'metrics', None):
                import time as _t
                try:
                    self.metrics.inc_rollout_state_snapshot_load(ok=ok, ts=_t.time())
                    self._rollout_state_last_load_ts = _t.time()
                except Exception:
                    pass
            if not ok:
                return self._json_response({"error": "failed"}, status=400)
            return self._json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_rollout_state_snapshot_status(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/state/snapshot_status')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/rollout/state/snapshot_status')
                except Exception:
                    pass
            data = {
                'path': str(self._rollout_state_snapshot_path),
                'last_write_ts': float(getattr(self, '_rollout_state_last_write_ts', 0.0)),
                'last_load_ts': float(getattr(self, '_rollout_state_last_load_ts', 0.0)),
            }
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
    
    async def _admin_throttle_snapshot(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/throttle/snapshot')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/throttle/snapshot')
                except Exception:
                    pass
            snap = {}
            try:
                if getattr(self.ctx, 'throttle', None):
                    snap = self.ctx.throttle.to_snapshot()
            except Exception:
                snap = {"version": 1}
            payload = json.dumps(snap, sort_keys=True, separators=(",", ":")).encode('utf-8')
            return web.Response(body=payload, content_type='application/json')
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_throttle_load(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/throttle/load')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/throttle/load')
                except Exception:
                    pass
            try:
                body = await request.json()
            except Exception:
                body = {}
            ok = False
            try:
                snap = body if isinstance(body, dict) else {}
                p = snap.get('path') if isinstance(snap, dict) else None
                if isinstance(p, str) and p:
                    snap = self._safe_load_json_file(p)
                    # strict structure
                    if not isinstance(snap, dict):
                        raise ValueError('invalid_payload')
                    keys = set(snap.keys())
                    required = {"version", "sha256", "payload"}
                    if not required.issubset(keys) or (keys - required):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='throttle').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    if not isinstance(snap.get('version'), int) or not isinstance(snap.get('sha256'), str) or not isinstance(snap.get('payload'), dict):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='throttle').inc()
                            except Exception:
                                pass
                        raise ValueError('invalid_structure')
                    import json as _json, hashlib as _hl
                    pj = _json.dumps(snap.get('payload', {}), sort_keys=True, separators=(",", ":")).encode('utf-8')
                    if _hl.sha256(pj).hexdigest() != str(snap.get('sha256')):
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.snapshot_integrity_fail_total.labels(kind='throttle').inc()
                            except Exception:
                                pass
                        raise ValueError('bad_checksum')
                    snap = snap.get('payload', {})
                if getattr(self.ctx, 'throttle', None):
                    self.ctx.throttle.load_snapshot(snap if isinstance(snap, dict) else {})
                    ok = True
            except Exception as _e:
                ok = False
                msg = str(getattr(_e, 'args', ['failed'])[0])
                if getattr(self, 'metrics', None):
                    try:
                        if msg in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum"):
                            self.metrics.snapshot_integrity_fail_total.labels(kind='rollout_ramp').inc()
                    except Exception:
                        pass
                if msg not in ("file_too_large", "non_ascii", "invalid_structure", "bad_checksum", "invalid_payload"):
                    msg = "failed"
            if getattr(self, 'metrics', None):
                import time as _t
                try:
                    self.metrics.inc_throttle_snapshot_load(ok=ok, ts=_t.time())
                except Exception:
                    pass
            if not ok:
                return self._json_response({"error": msg}, status=400)
            return self._json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_throttle_reset(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/throttle/reset')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/throttle/reset')
                except Exception:
                    pass
            try:
                if getattr(self.ctx, 'throttle', None):
                    self.ctx.throttle.reset()
            except Exception:
                pass
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_throttle_snapshot_status(self, request):
        try:
            _chk = getattr(self, '_check_admin_token', None)
            if _chk and not _chk(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/throttle/snapshot_status')
                    except Exception:
                        pass
                return web.json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/throttle/snapshot_status')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            path = getattr(self, '_throttle_snapshot_path', None) or "artifacts/throttle_snapshot.json"
            # Always include timestamps keys, defaulting to 0.0 when metrics absent
            last_write = 0.0
            last_load = 0.0
            if m:
                try:
                    last_write = float(getattr(m, '_throttle_last_write_ts', 0.0))
                    last_load = float(getattr(m, '_throttle_last_load_ts', 0.0))
                except Exception:
                    last_write, last_load = 0.0, 0.0
            data = {"path": str(path), "last_write_ts": float(last_write), "last_load_ts": float(last_load)}
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _admin_chaos(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/chaos')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/chaos'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/chaos')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if request.method == 'GET':
                ch = getattr(self.config, 'chaos', None)
                data = {
                    "enabled": bool(getattr(ch, 'enabled', False)),
                    "reject_inflate_pct": float(getattr(ch, 'reject_inflate_pct', 0.0)),
                    "latency_inflate_ms": int(getattr(ch, 'latency_inflate_ms', 0)),
                }
                self._admin_audit_record('/admin/chaos', request, {"method": "GET"})
                return self._json_response(data)
            # POST
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            ch = getattr(self.config, 'chaos', None)
            if ch is None:
                from src.common.config import ChaosConfig
                ch = ChaosConfig()
                self.config.chaos = ch  # type: ignore[attr-defined]
            # validate and set
            if 'enabled' in body:
                ch.enabled = bool(body['enabled'])
            if 'reject_inflate_pct' in body:
                try:
                    v = float(body['reject_inflate_pct'])
                except Exception:
                    return self._json_response({"error": "invalid_reject_inflate_pct"}, status=400)
                if v < 0.0 or v > 1.0:
                    return self._json_response({"error": "invalid_reject_inflate_pct"}, status=400)
                ch.reject_inflate_pct = v
            if 'latency_inflate_ms' in body:
                try:
                    v = int(body['latency_inflate_ms'])
                except Exception:
                    return self._json_response({"error": "invalid_latency_inflate_ms"}, status=400)
                if v < 0 or v > 10000:
                    return self._json_response({"error": "invalid_latency_inflate_ms"}, status=400)
                ch.latency_inflate_ms = v
            self._admin_audit_record('/admin/chaos', request, body)
            data = {
                "enabled": bool(getattr(ch, 'enabled', False)),
                "reject_inflate_pct": float(getattr(ch, 'reject_inflate_pct', 0.0)),
                "latency_inflate_ms": int(getattr(ch, 'latency_inflate_ms', 0)),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    def _build_canary_payload(self) -> dict:
        m = getattr(self, 'metrics', None)
        cfg = getattr(self, 'config', None)
        ro = getattr(cfg, 'rollout', None) if cfg is not None else None
        rollout = {
            "split_expected_pct": int(getattr(ro, 'traffic_split_pct', 0)) if ro else 0,
            "split_observed_pct": float(m.rollout_split_observed_pct._value.get()) if m and getattr(m, 'rollout_split_observed_pct', None) else 0.0,
            "orders_blue": int(getattr(m, '_rollout_orders_count', {}).get('blue', 0)) if m else 0,
            "orders_green": int(getattr(m, '_rollout_orders_count', {}).get('green', 0)) if m else 0,
            "fills_blue": int(getattr(m, '_rollout_fills', {}).get('blue', 0)) if m else 0,
            "fills_green": int(getattr(m, '_rollout_fills', {}).get('green', 0)) if m else 0,
            "rejects_blue": int(getattr(m, '_rollout_rejects', {}).get('blue', 0)) if m else 0,
            "rejects_green": int(getattr(m, '_rollout_rejects', {}).get('green', 0)) if m else 0,
            "latency_ms_avg_blue": float(getattr(m, '_rollout_latency_ewma', {}).get('blue', 0.0)) if m else 0.0,
            "latency_ms_avg_green": float(getattr(m, '_rollout_latency_ewma', {}).get('green', 0.0)) if m else 0.0,
            "latency_ms_p95_blue": float(getattr(getattr(m, 'rollout_latency_p95_ms', object()), 'labels', lambda **_: object) (color='blue')._value.get()) if m and getattr(m, 'rollout_latency_p95_ms', None) else 0.0,
            "latency_ms_p95_green": float(getattr(getattr(m, 'rollout_latency_p95_ms', object()), 'labels', lambda **_: object) (color='green')._value.get()) if m and getattr(m, 'rollout_latency_p95_ms', None) else 0.0,
            "latency_ms_p99_blue": float(getattr(getattr(m, 'rollout_latency_p99_ms', object()), 'labels', lambda **_: object) (color='blue')._value.get()) if m and getattr(m, 'rollout_latency_p99_ms', None) else 0.0,
            "latency_ms_p99_green": float(getattr(getattr(m, 'rollout_latency_p99_ms', object()), 'labels', lambda **_: object) (color='green')._value.get()) if m and getattr(m, 'rollout_latency_p99_ms', None) else 0.0,
            "latency_samples_blue": float(getattr(getattr(m, 'rollout_latency_samples_total', object()), 'labels', lambda **_: object) (color='blue')._value.get()) if m and getattr(m, 'rollout_latency_samples_total', None) else 0.0,
            "latency_samples_green": float(getattr(getattr(m, 'rollout_latency_samples_total', object()), 'labels', lambda **_: object) (color='green')._value.get()) if m and getattr(m, 'rollout_latency_samples_total', None) else 0.0,
            "salt_hash": hashlib.sha1(str(getattr(ro, 'salt', '')).encode('utf-8')).hexdigest() if ro else "",
            "overlay_diff_keys": sorted(list(set(((getattr(ro, 'blue', {}) or {}).keys())) ^ set(((getattr(ro, 'green', {}) or {}).keys())))) if ro else [],
            "ramp": {
                "enabled": bool(getattr(self.config, 'rollout_ramp', None) and self.config.rollout_ramp.enabled),
                "step_idx": int(float(getattr(m, 'rollout_ramp_step_idx', object())._value.get())) if m and getattr(m, 'rollout_ramp_step_idx', None) else 0,
                "frozen": bool(int(float(getattr(m, 'rollout_ramp_frozen', object())._value.get()))) if m and getattr(m, 'rollout_ramp_frozen', None) else False,
                "holds_sample": int(getattr(m, '_ramp_holds_counts', {}).get('sample', 0)) if m else 0,
                "holds_cooldown": int(getattr(m, '_ramp_holds_counts', {}).get('cooldown', 0)) if m else 0,
                "cooldown_seconds": float(getattr(m, 'rollout_ramp_cooldown_seconds', object())._value.get()) if m and getattr(m, 'rollout_ramp_cooldown_seconds', None) else 0.0,
            },
        }
        # Tail deltas and triage hints
        try:
            p95_b = float(rollout.get('latency_ms_p95_blue', 0.0))
            p95_g = float(rollout.get('latency_ms_p95_green', 0.0))
            p99_b = float(rollout.get('latency_ms_p99_blue', 0.0))
            p99_g = float(rollout.get('latency_ms_p99_green', 0.0))
            rollout['latency_ms_p95_delta'] = float(p95_g - p95_b)
            rollout['latency_ms_p99_delta'] = float(p99_g - p99_b)
        except Exception:
            rollout['latency_ms_p95_delta'] = 0.0
            rollout['latency_ms_p99_delta'] = 0.0
        # simple drift stub: compare observed vs expected, need min sample
        total_orders = int(rollout["orders_blue"]) + int(rollout["orders_green"])
        min_sample = 100
        cap_pct = abs(float(rollout["split_observed_pct"]) - float(rollout["split_expected_pct"]))
        alert = bool(total_orders >= min_sample and cap_pct > 5.0)
        drift = {"cap_pct": float(cap_pct), "min_sample_orders": int(min_sample), "alert": bool(alert), "reason": "observed_vs_expected" if alert else "ok"}
        # Triage hints (deterministic order)
        hints = []
        try:
            fills_b = int(rollout.get("fills_blue", 0))
            fills_g = int(rollout.get("fills_green", 0))
            rej_b = int(rollout.get("rejects_blue", 0))
            rej_g = int(rollout.get("rejects_green", 0))
            total_fills = fills_b + fills_g
            denom_b = max(1, (fills_b + rej_b))
            denom_g = max(1, (fills_g + rej_g))
            rr_b = float(rej_b) / float(denom_b)
            rr_g = float(rej_g) / float(denom_g)
            if total_fills >= 500 and (rr_g - rr_b) > 0.02:
                hints.append("green_rejects_spike")
        except Exception:
            pass
        try:
            if (float(rollout.get("latency_ms_avg_green", 0.0)) - float(rollout.get("latency_ms_avg_blue", 0.0))) > 50.0:
                hints.append("green_latency_regression")
        except Exception:
            pass
        # Tail-aware hints with min sample caps from env
        try:
            import os as _os
            min_s = int(_os.getenv('LAT_MIN_SAMPLE', '200'))
            cap95 = float(_os.getenv('LAT_P95_CAP_MS', '50'))
            cap99 = float(_os.getenv('LAT_P99_CAP_MS', '100'))
        except Exception:
            min_s, cap95, cap99 = 200, 50.0, 100.0
        try:
            s_b = float(rollout.get('latency_samples_blue', 0.0))
            s_g = float(rollout.get('latency_samples_green', 0.0))
            if s_b >= float(min_s) and s_g >= float(min_s):
                if float(rollout.get('latency_ms_p95_delta', 0.0)) > cap95:
                    hints.append('latency_tail_regression_p95')
                if float(rollout.get('latency_ms_p99_delta', 0.0)) > cap99:
                    hints.append('latency_tail_regression_p99')
        except Exception:
            pass
        try:
            if bool(drift.get("alert", False)):
                hints.append("split_drift_exceeds_cap")
        except Exception:
            pass
        try:
            if int(rollout.get("ramp", {}).get("holds_sample", 0)) > 0:
                hints.append("ramp_hold_low_sample")
        except Exception:
            pass
        try:
            if int(rollout.get("ramp", {}).get("holds_cooldown", 0)) > 0:
                hints.append("ramp_on_cooldown")
        except Exception:
            pass
        # Use deterministic build time if available; else constant
        bt = getattr(self, '_build_time_iso', None)
        gen_at = str(bt) if isinstance(bt, str) and bt else '1970-01-01T00:00:00Z'
        meta = {
            "commit": str(get_git_sha() or "unknown"),
            "params_hash": str(getattr(self, '_params_hash', 'unknown')),
            "generated_at": gen_at,
        }
        # killswitch audit block for canary payload
        ks = getattr(cfg, 'killswitch', None)
        ks_enabled = bool(getattr(ks, 'enabled', False))
        ks_dry = bool(getattr(ks, 'dry_run', True))
        ks_act = str(getattr(ks, 'action', 'rollback'))
        rej_b = float(rollout.get('rejects_blue', 0))
        rej_g = float(rollout.get('rejects_green', 0))
        fill_b = float(rollout.get('fills_blue', 0))
        fill_g = float(rollout.get('fills_green', 0))
        lat_b = float(rollout.get('latency_ms_avg_blue', 0.0))
        lat_g = float(rollout.get('latency_ms_avg_green', 0.0))
        # Fallback to exporter snapshot if counters absent (tests)
        try:
            if (rej_b + rej_g + fill_b + fill_g == 0.0) and hasattr(m, '_get_rollout_snapshot_for_tests'):
                snap = m._get_rollout_snapshot_for_tests()
                fill_b = float((snap.get('fills', {}) or {}).get('blue', 0))
                fill_g = float((snap.get('fills', {}) or {}).get('green', 0))
                rej_b = float((snap.get('rejects', {}) or {}).get('blue', 0))
                rej_g = float((snap.get('rejects', {}) or {}).get('green', 0))
                lat_b = float((snap.get('latency_ewma', {}) or {}).get('blue', 0.0))
                lat_g = float((snap.get('latency_ewma', {}) or {}).get('green', 0.0))
        except Exception:
            pass
        # Prefer unified metrics snapshot if available to ensure canary/ramp consistency
        try:
            if m and hasattr(m, '_get_rollout_snapshot_for_tests'):
                snap = m._get_rollout_snapshot_for_tests()
                fill_b = float((snap.get('fills', {}) or {}).get('blue', fill_b))
                fill_g = float((snap.get('fills', {}) or {}).get('green', fill_g))
                rej_b = float((snap.get('rejects', {}) or {}).get('blue', rej_b))
                rej_g = float((snap.get('rejects', {}) or {}).get('green', rej_g))
                lat_b = float((snap.get('latency_ewma', {}) or {}).get('blue', lat_b))
                lat_g = float((snap.get('latency_ewma', {}) or {}).get('green', lat_g))
        except Exception:
            pass
        rr_b = rej_b / max(1.0, (rej_b + fill_b))
        rr_g = rej_g / max(1.0, (rej_g + fill_g))
        rej_delta = rr_g - rr_b
        lat_delta = lat_g - lat_b
        ks_fired = ks_enabled and ((rej_delta > float(getattr(ks, 'max_reject_delta', 0.02))) or (lat_delta > float(getattr(ks, 'max_latency_delta_ms', 50))))
        ks_reason = 'none'
        if ks_fired:
            ks_reason = 'reject_delta' if rej_delta > float(getattr(ks, 'max_reject_delta', 0.02)) else 'latency_delta'
        ap = getattr(cfg, 'autopromote', None)
        rs = getattr(self, '_ramp_state', {}) or {}
        ap_block = {
            "enabled": bool(getattr(ap, 'enabled', False)),
            "stable_steps_required": int(getattr(ap, 'stable_steps_required', 6)) if ap else 6,
            "min_split_pct": int(getattr(ap, 'min_split_pct', 25)) if ap else 25,
            "stable_steps_current": int((rs.get('consecutive_stable_steps', 0)) if isinstance(rs, dict) else 0),
        }
        # SLO block from metrics gauges if available
        slo_block = {"p95": {"blue": {"burn_rate": 0.0, "budget": 0.0}, "green": {"burn_rate": 0.0, "budget": 0.0}},
                     "p99": {"blue": {"burn_rate": 0.0, "budget": 0.0}, "green": {"burn_rate": 0.0, "budget": 0.0}}}
        
        # Markout block for execution quality assessment
        markout_block = {
            "200": {"blue": {"avg_bps": 0.0, "samples": 0}, "green": {"avg_bps": 0.0, "samples": 0}},
            "500": {"blue": {"avg_bps": 0.0, "samples": 0}, "green": {"avg_bps": 0.0, "samples": 0}}
        }
        
        try:
            if m and hasattr(m, '_get_markout_snapshot_for_tests'):
                markout_snap = m._get_markout_snapshot_for_tests()
                for horizon_ms in ["200", "500"]:
                    for color in ["blue", "green"]:
                        if horizon_ms in markout_snap and color in markout_snap[horizon_ms]:
                            # Get average markout for this horizon/color
                            symbol_data = markout_snap[horizon_ms][color]
                            if symbol_data:
                                # Calculate weighted average across symbols
                                total_bps = 0.0
                                total_count = 0
                                for symbol, data in symbol_data.items():
                                    if isinstance(data, dict) and 'avg_bps' in data and 'count' in data:
                                        total_bps += data['avg_bps'] * data['count']
                                        total_count += data['count']
                                
                                if total_count > 0:
                                    avg_bps = total_bps / total_count
                                    markout_block[horizon_ms][color]["avg_bps"] = round(avg_bps, 6)
                                
                                # Add samples count for gate evaluation
                                if "samples" in symbol_data:
                                    markout_block[horizon_ms][color]["samples"] = int(symbol_data["samples"])
        except Exception:
            pass
        
        # Calculate markout deltas and add triage hints
        try:
            markout_200_b = float(markout_block["200"]["blue"]["avg_bps"])
            markout_200_g = float(markout_block["200"]["green"]["avg_bps"])
            markout_500_b = float(markout_block["500"]["blue"]["avg_bps"])
            markout_500_g = float(markout_block["500"]["green"]["avg_bps"])
            
            markout_block["200"]["delta_bps"] = round(markout_200_g - markout_200_b, 6)
            markout_block["500"]["delta_bps"] = round(markout_500_g - markout_500_b, 6)
            
            # Add triage hints for markout
            import os as _os
            markout_cap_bps = float(_os.getenv('MARKOUT_CAP_BPS', '0.5'))
            
            if markout_200_g - markout_200_b < -markout_cap_bps:
                hints.append("markout_green_worse_200ms")
            if markout_500_g - markout_500_b < -markout_cap_bps:
                hints.append("markout_green_worse_500ms")
                
        except Exception:
            markout_block["200"]["delta_bps"] = 0.0
            markout_block["500"]["delta_bps"] = 0.0
        try:
            if m and getattr(m, 'latency_slo_burn_rate', None) and getattr(m, 'latency_slo_budget_remaining', None):
                def _gv(g, color, percentile):
                    try:
                        return float(g.labels(color=color, percentile=percentile)._value.get())
                    except Exception:
                        return 0.0
                for pct in ('p95','p99'):
                    for col in ('blue','green'):
                        br = _gv(m.latency_slo_burn_rate, col, pct)
                        bg = _gv(m.latency_slo_budget_remaining, col, pct)
                        slo_block[pct][col] = {"burn_rate": br, "budget": bg}
        except Exception:
            pass
        # Add markout samples fields for gate evaluation
        markout_samples = {}
        try:
            if m and hasattr(m, '_get_markout_snapshot_for_tests'):
                markout_snap = m._get_markout_snapshot_for_tests()
                for horizon_ms in ["200", "500"]:
                    for color in ["blue", "green"]:
                        if horizon_ms in markout_snap and color in markout_snap[horizon_ms]:
                            samples = markout_snap[horizon_ms][color].get("samples", 0)
                            markout_samples[f"markout_samples_{horizon_ms}_{color}"] = int(samples)
        except Exception:
            pass
        
        payload = {"meta": meta, "rollout": rollout, "drift": drift, "hints": hints, "killswitch": {"enabled": ks_enabled, "dry_run": ks_dry, "action": ks_act, "fired": bool(ks_fired), "reason": ks_reason}, "autopromote": ap_block, "slo": slo_block, "markout": markout_block, **markout_samples}
        # append alerts if triggered
        try:
            ts = payload["meta"].get("generated_at") or datetime.now(timezone.utc).isoformat()
            if ks_fired:
                self._append_json_line(self._alerts_log_file(), {"ts": ts, "kind": "killswitch_fired", "payload": payload["killswitch"]})
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_alert_event('killswitch_fired')
                    except Exception:
                        pass
            if bool(drift.get('alert', False)):
                self._append_json_line(self._alerts_log_file(), {"ts": ts, "kind": "split_drift_alert", "payload": drift})
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_alert_event('split_drift_alert')
                    except Exception:
                        pass
            # Check for markout regression alerts
            try:
                import os as _os
                markout_cap_bps = float(_os.getenv('MARKOUT_CAP_BPS', '0.5'))
                markout_200_b = float(markout_block["200"]["blue"]["avg_bps"])
                markout_200_g = float(markout_block["200"]["green"]["avg_bps"])
                markout_500_b = float(markout_block["500"]["blue"]["avg_bps"])
                markout_500_g = float(markout_block["500"]["green"]["avg_bps"])
                
                if markout_200_g - markout_200_b < -markout_cap_bps:
                    self._append_json_line(self._alerts_log_file(), {"ts": ts, "kind": "markout_regression", "horizon_ms": 200, "delta_bps": round(markout_200_g - markout_200_b, 6)})
                if markout_500_g - markout_500_b < -markout_cap_bps:
                    self._append_json_line(self._alerts_log_file(), {"ts": ts, "kind": "markout_regression", "horizon_ms": 500, "delta_bps": round(markout_500_g - markout_500_b, 6)})
            except Exception:
                pass
            
            if hints:
                self._append_json_line(self._alerts_log_file(), {"ts": ts, "kind": "triage_hints", "payload": {"hints": hints}})
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_alert_event('triage_hints')
                    except Exception:
                        pass
        except Exception:
            pass
        return payload

    async def _admin_report_canary(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/report/canary')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/report/canary'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/report/canary')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/report/canary')
                except Exception:
                    pass
            payload = self._build_canary_payload()
            self._admin_audit_record('/admin/report/canary', request, payload.get('meta', {}))
            return self._json_response(payload)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_report_canary_replay(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/report/canary/replay')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/report/canary/replay'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/report/canary/replay')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            canary_path = (body or {}).get('canary_path')
            thr_path = (body or {}).get('thresholds_path')
            if not isinstance(canary_path, str) or not isinstance(thr_path, str) or not canary_path or not thr_path:
                return self._json_response({"error": "invalid_input"}, status=400)
            # Load inputs with size guards
            try:
                canary = self._safe_load_json_file(canary_path, limit_bytes=1<<20)
            except ValueError as ve:
                if str(ve) == 'file_too_large':
                    return self._json_response({"error": "file_too_large"}, status=400)
                return self._json_response({"error": "invalid_canary_json"}, status=400)
            try:
                thr_txt = self._safe_read_text_file(thr_path, limit_bytes=1<<20)
                if not str(thr_txt).strip():
                    return self._json_response({"error": "invalid_thresholds_text"}, status=400)
            except ValueError as ve:
                if str(ve) == 'file_too_large':
                    return self._json_response({"error": "file_too_large"}, status=400)
                return self._json_response({"error": "invalid_thresholds_text"}, status=400)
            # Snapshot current thresholds
            from src.deploy.thresholds import current_thresholds_snapshot, refresh_thresholds, get_thresholds_version, GateThresholds
            snap_before = current_thresholds_snapshot()
            ver_before = int(snap_before.get('version', 0))
            ver_after = ver_before
            try:
                # Apply provided thresholds
                try:
                    summary = refresh_thresholds(thr_path)
                    ver_after = int(summary.get('version', get_thresholds_version()))
                except Exception as e:
                    return self._json_response({"error": str(e)}, status=400)
                # Build wf_report
                def _pick(d, path, default):
                    try:
                        c = d
                        for k in path:
                            c = c[k]
                        return c
                    except Exception:
                        return default
                symbol = str(_pick(canary, ['symbol'], canary.get('rollout', {}).get('symbol', 'UNKNOWN')) or 'UNKNOWN')
                ro = canary.get('rollout', {}) if isinstance(canary, dict) else {}
                can = {
                    'killswitch_fired': bool(_pick(canary, ['killswitch','fired'], False)),
                    'drift_alert': bool(_pick(canary, ['drift','alert'], False)),
                    'fills_blue': int(ro.get('fills_blue', 0)),
                    'fills_green': int(ro.get('fills_green', 0)),
                    'rejects_blue': int(ro.get('rejects_blue', 0)),
                    'rejects_green': int(ro.get('rejects_green', 0)),
                    'latency_ms_avg_blue': float(ro.get('latency_ms_avg_blue', 0.0)),
                    'latency_ms_avg_green': float(ro.get('latency_ms_avg_green', 0.0)),
                    'latency_ms_p95_blue': float(ro.get('latency_ms_p95_blue', 0.0)),
                    'latency_ms_p95_green': float(ro.get('latency_ms_p95_green', 0.0)),
                    'latency_ms_p99_blue': float(ro.get('latency_ms_p99_blue', 0.0)),
                    'latency_ms_p99_green': float(ro.get('latency_ms_p99_green', 0.0)),
                    'latency_samples_blue': int(ro.get('latency_samples_blue', 0.0)),
                    'latency_samples_green': int(ro.get('latency_samples_green', 0.0)),
                }
                wf_report = {'symbol': symbol, 'canary': can}
                from src.deploy.gate import evaluate as gate_evaluate
                ok, reasons, metrics = gate_evaluate(wf_report, thresholds=GateThresholds())
                used = metrics.get('canary_gate_thresholds_used', {})
                decision = 'PASS' if ok else 'FAIL'
                resp = {
                    'decision': decision,
                    'reasons': reasons,
                    'used_thresholds': used,
                    'thresholds_version_before': int(ver_before),
                    'thresholds_version_after': int(ver_after),
                }
                self._admin_audit_record('/admin/report/canary/replay', request, {'symbol': symbol})
                return self._json_response(resp)
            finally:
                # Restore previous thresholds
                try:
                    from src.deploy import thresholds as TH
                    snap = snap_before
                    with TH._thr_lock:
                        TH.THROTTLE_GLOBAL.clear()
                        TH.THROTTLE_GLOBAL.update(snap.get('global', {}))
                        TH.THROTTLE_PER_SYMBOL.clear()
                        TH.THROTTLE_PER_SYMBOL.update(snap.get('per_symbol', {}))
                        cg = snap.get('canary_gate', {}) or {}
                        for k in list(TH.CANARY_GATE.keys()):
                            if k in cg:
                                TH.CANARY_GATE[k] = cg[k]
                        TH.CANARY_GATE_PER_SYMBOL.clear()
                        TH.CANARY_GATE_PER_SYMBOL.update(snap.get('canary_gate_per_symbol', {}))
                        TH._THRESHOLDS_VERSION = int(ver_before)
                except Exception:
                    pass
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_latency_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/latency_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/rollout/latency_snapshot'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/rollout/latency_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            snap = {}
            try:
                if getattr(self, 'metrics', None) and hasattr(self.metrics, '_get_latency_snapshot_for_tests'):
                    snap = self.metrics._get_latency_snapshot_for_tests()
            except Exception:
                snap = {}
            self._admin_audit_record('/admin/rollout/latency_snapshot', request, {})
            return self._json_response(snap)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_report_canary_generate(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/report/canary/generate')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/report/canary/generate'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/report/canary/generate')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/report/canary/generate')
                except Exception:
                    pass
            payload = self._build_canary_payload()
            # Write artifacts atomically
            self._atomic_json_write(os.path.join(self._get_artifacts_dir(), 'canary.json'), payload)
            # Build REPORT_CANARY.md
            r = payload
            lines = []
            lines.append("E2 Canary Report")
            lines.append("")
            lines.append(f"commit: {r['meta']['commit']}")
            lines.append(f"generated_at: {r['meta']['generated_at']}")
            lines.append("")
            lines.append("Rollout:")
            lines.append(f" split_expected_pct: {r['rollout']['split_expected_pct']}")
            lines.append(f" split_observed_pct: {r['rollout']['split_observed_pct']}")
            lines.append(f" orders_blue: {r['rollout']['orders_blue']} orders_green: {r['rollout']['orders_green']}")
            lines.append(f" fills_blue: {r['rollout']['fills_blue']} fills_green: {r['rollout']['fills_green']}")
            lines.append(f" rejects_blue: {r['rollout']['rejects_blue']} rejects_green: {r['rollout']['rejects_green']}")
            lines.append(f" latency_ms_avg_blue: {r['rollout']['latency_ms_avg_blue']} latency_ms_avg_green: {r['rollout']['latency_ms_avg_green']}")
            lines.append(f" salt_hash: {r['rollout']['salt_hash']}")
            lines.append(f" overlay_diff_keys: {','.join(r['rollout']['overlay_diff_keys'])}")
            lines.append(" ramp:")
            lines.append(f"  enabled: {r['rollout']['ramp']['enabled']} step_idx: {r['rollout']['ramp']['step_idx']} frozen: {r['rollout']['ramp']['frozen']}")
            lines.append(f"  holds_sample: {r['rollout']['ramp']['holds_sample']} holds_cooldown: {r['rollout']['ramp']['holds_cooldown']} cooldown_seconds: {r['rollout']['ramp']['cooldown_seconds']}")
            lines.append("")
            lines.append("Drift:")
            lines.append(f" cap_pct: {r['drift']['cap_pct']} min_sample_orders: {r['drift']['min_sample_orders']}")
            lines.append(f" alert: {r['drift']['alert']} reason: {r['drift']['reason']}")
            md = "\n".join(lines)
            # Atomic write for MD as well
            self._atomic_json_write(os.path.join(self._get_artifacts_dir(), 'REPORT_CANARY.md'), {"_": md})
            # Replace JSON wrapper by writing plain md (atomic):
            try:
                # write plain md via temp file path
                from pathlib import Path as _P
                p = _P(os.path.join(self._get_artifacts_dir(), 'REPORT_CANARY.md'))
                tmp = str(p) + '.tmp'
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(md)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                try:
                    os.replace(tmp, str(p))
                except Exception:
                    os.rename(tmp, str(p))
            except Exception:
                pass
            self._admin_audit_record('/admin/report/canary/generate', request, payload.get('meta', {}))
            return self._json_response({"status": "ok"})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _canary_export_loop(self):
        import time as _t, os as _os
        while getattr(self, 'running', False):
            try:
                t0 = _t.perf_counter()
                r = self._build_canary_payload()
                ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                json_path = _os.path.join(self._get_artifacts_dir(), f"canary_{ts}.json")
                md_path = _os.path.join(self._get_artifacts_dir(), f"REPORT_CANARY_{ts}.md")
                self._atomic_json_write(json_path, r)
                dt_ms = (_t.perf_counter() - t0) * 1000.0
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.record_loop_tick('export', dt_ms)
                        self.metrics.record_loop_heartbeat('export')
                    except Exception:
                        pass
                # Build MD
                lines = []
                lines.append("E2 Canary Report")
                lines.append("")
                lines.append(f"commit: {r['meta']['commit']}")
                lines.append(f"generated_at: {r['meta']['generated_at']}")
                lines.append("")
                lines.append("Rollout:")
                lines.append(f" split_expected_pct: {r['rollout']['split_expected_pct']}")
                lines.append(f" split_observed_pct: {r['rollout']['split_observed_pct']}")
                lines.append(f" orders_blue: {r['rollout']['orders_blue']} orders_green: {r['rollout']['orders_green']}")
                lines.append(f" fills_blue: {r['rollout']['fills_blue']} fills_green: {r['rollout']['fills_green']}")
                lines.append(f" rejects_blue: {r['rollout']['rejects_blue']} rejects_green: {r['rollout']['rejects_green']}")
                lines.append(f" latency_ms_avg_blue: {r['rollout']['latency_ms_avg_blue']} latency_ms_avg_green: {r['rollout']['latency_ms_avg_green']}")
                lines.append(f" salt_hash: {r['rollout']['salt_hash']}")
                lines.append(f" overlay_diff_keys: {','.join(r['rollout']['overlay_diff_keys'])}")
                lines.append(" hints:")
                lines.append(f"  {','.join(r.get('hints', []))}")
                md = "\n".join(lines)
                # Atomic MD write
                try:
                    from pathlib import Path as _P
                    p = _P(md_path)
                    tmp = str(p) + '.tmp'
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(md)
                        f.flush()
                        try:
                            _os.fsync(f.fileno())
                        except Exception:
                            pass
                    try:
                        _os.replace(tmp, str(p))
                    except Exception:
                        _os.rename(tmp, str(p))
                    # fsync dir
                    try:
                        dirfd = _os.open(str(p.parent), _os.O_DIRECTORY)
                        try:
                            _os.fsync(dirfd)
                        finally:
                            _os.close(dirfd)
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
            # sleep in small slices respecting running
            remaining = float(getattr(self, '_canary_export_interval', 300))
            while getattr(self, 'running', False) and remaining > 0.0:
                step = 0.05 if remaining > 0.05 else remaining
                await asyncio.sleep(step)
                remaining -= step

    async def _prune_artifacts_loop(self):
        import os as _os, time as _t
        from pathlib import Path as _P
        import time as _t
        def _env_float(name: str, default: float) -> float:
            try:
                return float(_os.getenv(name, str(default)))
            except Exception:
                return float(default)
        def _env_int(name: str, default: int) -> int:
            try:
                return int(_os.getenv(name, str(default)))
            except Exception:
                return int(default)
        while getattr(self, 'running', False):
            try:
                t0 = _t.perf_counter()
                base = _P(self._get_artifacts_dir())
                base.mkdir(parents=True, exist_ok=True)
                max_keep = _env_int('CANARY_MAX_SNAPSHOTS', 200)
                max_days = _env_int('CANARY_MAX_DAYS', 7)
                alerts_tail = _env_int('ALERTS_MAX_LINES', 5000)
                now = _t.time()
                # prune canary_*.json and REPORT_CANARY_*.md
                canary_json = sorted(base.glob('canary_*.json'), key=lambda p: p.stat().st_mtime)
                canary_md = sorted(base.glob('REPORT_CANARY_*.md'), key=lambda p: p.stat().st_mtime)
                def _apply_age_and_count(files):
                    # age-based
                    kept = []
                    for p in files:
                        try:
                            age_days = (now - p.stat().st_mtime) / 86400.0
                            if age_days > float(max_days):
                                p.unlink(missing_ok=True)  # py>=3.8 has missing_ok
                            else:
                                kept.append(p)
                        except Exception:
                            pass
                    # count-based
                    if len(kept) > max_keep:
                        to_delete = kept[0:len(kept)-max_keep]
                        for p in to_delete:
                            try:
                                p.unlink(missing_ok=True)
                            except Exception:
                                pass
                _apply_age_and_count(canary_json)
                _apply_age_and_count(canary_md)
                # alerts log tail keep
                try:
                    ap = base / 'alerts.log'
                    if ap.exists():
                        with open(ap, 'r', encoding='utf-8') as f:
                            lines = f.read().splitlines()
                        if len(lines) > alerts_tail:
                            tail = lines[-alerts_tail:]
                            tmp = str(ap) + '.tmp'
                            with open(tmp, 'w', encoding='utf-8') as f:
                                f.write("\n".join(tail) + "\n")
                                f.flush()
                                try:
                                    _os.fsync(f.fileno())
                                except Exception:
                                    pass
                            try:
                                _os.replace(tmp, str(ap))
                            except Exception:
                                _os.rename(tmp, str(ap))
                            # fsync dir best-effort
                            try:
                                dirfd = _os.open(str(base), _os.O_DIRECTORY)
                                try:
                                    _os.fsync(dirfd)
                                finally:
                                    _os.close(dirfd)
                            except Exception:
                                pass
                except Exception:
                    pass
            except Exception:
                pass
            # sleep in small slices
            remaining = float(getattr(self, '_prune_interval', 3600.0))
            while getattr(self, 'running', False) and remaining > 0.0:
                step = 0.05 if remaining > 0.05 else remaining
                t1 = _t.perf_counter()
                await asyncio.sleep(step)
                drift = (_t.perf_counter() - t1) * 1000.0 - (step * 1000.0)
                if drift > 100.0 and getattr(self, 'metrics', None):
                    try:
                        self.metrics.set_event_loop_drift(drift)
                    except Exception:
                        pass
                remaining -= step
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.record_loop_heartbeat('prune')
                except Exception:
                    pass
    async def _scheduler_recompute_loop(self):
        import os as _os
        try:
            interval = float(_os.getenv('SCHEDULER_RECOMPUTE_SEC', '0'))
        except Exception:
            interval = 0.0
        if interval <= 0:
            return
        while getattr(self, 'running', False):
            try:
                # call our suggest endpoint logic internally
                stats = {}
                for h in range(0, 24, 2):
                    key = f"{h:02d}:00-{(h+2)%24:02d}:00"
                    stats[key] = {"median_spread_bps": float((h % 10) + 1), "vola_ewma": float(5 + (h % 6)), "volume_norm": float((h % 4) / 3.0), "sample": int(500)}
                cfg = {"top_k": 6, "min_sample": 200, "mode": "neutral"}
                from src.scheduler.tod import suggest_windows
                wins = suggest_windows(stats, cfg)
                # hot-apply
                try:
                    sw = [{"name": f"win{i}", "days": [1,2,3,4,5,6,7], "start": w.get('start'), "end": w.get('end')} for i, w in enumerate(wins)]
                    if getattr(self.ctx, 'scheduler', None):
                        self.ctx.scheduler.set_windows(sw)
                except Exception:
                    pass
            except Exception:
                pass
            # sleep slices
            remaining = float(interval)
            while getattr(self, 'running', False) and remaining > 0.0:
                step = 0.05 if remaining > 0.05 else remaining
                await asyncio.sleep(step)
                remaining -= step
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.record_loop_heartbeat('scheduler')
                except Exception:
                    pass

    async def _latency_slo_loop(self):
        try:
            import time as _t
            window_started = _t.time()
            while getattr(self, 'running', False):
                t0 = _t.perf_counter()
                await asyncio.sleep(0.05)
                drift = (_t.perf_counter() - t0) * 1000.0 - 50.0
                if drift > 100.0 and getattr(self, 'metrics', None):
                    try:
                        self.metrics.set_event_loop_drift(drift)
                    except Exception:
                        pass
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.record_loop_heartbeat('slo')
                    except Exception:
                        pass
                slo = getattr(self.config, 'latency_slo', None)
                if not slo or not getattr(slo, 'enabled', False):
                    continue
                now = _t.time()
                if now - window_started < max(1, int(getattr(slo, 'window_sec', 60))):
                    continue
                window_started = now
                m = getattr(self, 'metrics', None)
                if not m:
                    continue
                t_calc0 = _t.perf_counter()
                snap = m._get_latency_snapshot_for_tests()
                def _calc(pval: float, target: float) -> tuple[float, float]:
                    try:
                        br = 0.0 if target <= 0 else max(0.0, float(pval) / float(target))
                        bg = 0.0 if br <= 0 else max(0.0, 1.0 / br)
                        return br, bg
                    except Exception:
                        return 0.0, 0.0
                p95b = float(snap.get('p95', {}).get('blue', 0.0))
                p95g = float(snap.get('p95', {}).get('green', 0.0))
                p99b = float(snap.get('p99', {}).get('blue', 0.0))
                p99g = float(snap.get('p99', {}).get('green', 0.0))
                br_b_p95, bg_b_p95 = _calc(p95b, float(slo.p95_target_ms))
                br_g_p95, bg_g_p95 = _calc(p95g, float(slo.p95_target_ms))
                br_b_p99, bg_b_p99 = _calc(p99b, float(slo.p99_target_ms))
                br_g_p99, bg_g_p99 = _calc(p99g, float(slo.p99_target_ms))
                m.set_latency_slo('blue', 'p95', br_b_p95, bg_b_p95)
                m.set_latency_slo('green', 'p95', br_g_p95, bg_g_p95)
                m.set_latency_slo('blue', 'p99', br_b_p99, bg_b_p99)
                m.set_latency_slo('green', 'p99', br_g_p99, bg_g_p99)
                thr = float(getattr(slo, 'burn_alert_threshold', 1.0))
                def _check_and_alert(pct: str, br_b: float, br_g: float):
                    try:
                        if br_b > thr or br_g > thr:
                            self._append_json_line(self._alerts_log_path or os.path.join(self._get_artifacts_dir(), 'alerts.log'), {
                                "ts": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                "kind": "latency_slo_breach",
                                "payload": {"percentile": pct, "burn_rate_blue": round(br_b, 6), "burn_rate_green": round(br_g, 6)}
                            })
                            if getattr(self, 'metrics', None):
                                try:
                                    self.metrics.inc_latency_slo_alert(pct)
                                    self.metrics.inc_admin_alert_event('latency_slo_breach')
                                except Exception:
                                    pass
                    except Exception:
                        pass
                _check_and_alert('p95', br_b_p95, br_g_p95)
                _check_and_alert('p99', br_b_p99, br_g_p99)
                dt_ms = (_t.perf_counter() - t_calc0) * 1000.0
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.record_loop_tick('slo', dt_ms)
                    except Exception:
                        pass
        except Exception:
            # swallow
            await asyncio.sleep(0.05)

    async def _admin_report_canary_baseline(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/report/canary/baseline')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/report/canary/baseline'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/report/canary/baseline')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            path = body.get('path') if isinstance(body, dict) else None
            if not path or not isinstance(path, str):
                return self._json_response({"error": "invalid_path"}, status=400)
            snap = self._safe_load_json_file(path)
            if not isinstance(snap, dict):
                return self._json_response({"error": "invalid_snapshot"}, status=400)
            self._atomic_json_write(os.path.join(self._get_artifacts_dir(), 'canary_baseline.json'), snap)
            self._admin_audit_record('/admin/report/canary/baseline', request, {"path": path})
            return self._json_response({"status": "ok"})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_report_canary_diff(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/report/canary/diff')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/report/canary/diff'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/report/canary/diff')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            cur = self._build_canary_payload()
            import json as _json
            try:
                with open(os.path.join(self._get_artifacts_dir(), 'canary_baseline.json'), 'r', encoding='utf-8') as f:
                    base = _json.loads(f.read() or '{}')
            except Exception:
                base = {}
            # compute deltas
            def _get(d, path, default):
                try:
                    c = d
                    for k in path:
                        c = c[k]
                    return c
                except Exception:
                    return default
            def _rr(x):
                try:
                    return float(x)
                except Exception:
                    return 0.0
            # reject rate diff
            b_rej_b = _rr(_get(cur, ['rollout','rejects_blue'], 0))
            b_rej_g = _rr(_get(cur, ['rollout','rejects_green'], 0))
            b_fill_b = _rr(_get(cur, ['rollout','fills_blue'], 0))
            b_fill_g = _rr(_get(cur, ['rollout','fills_green'], 0))
            rr_b = b_rej_b / max(1.0, (b_rej_b + b_fill_b))
            rr_g = b_rej_g / max(1.0, (b_rej_g + b_fill_g))
            reject_delta = rr_g - rr_b
            lat_delta = _rr(_get(cur,['rollout','latency_ms_avg_green'],0.0)) - _rr(_get(cur,['rollout','latency_ms_avg_blue'],0.0))
            delta = {
                'split_observed_pct': float(_get(cur, ['rollout','split_observed_pct'], 0.0)) - float(_get(base,['rollout','split_observed_pct'], 0.0)),
                'reject_rate_green_minus_blue': float(reject_delta),
                'latency_ms_delta': float(lat_delta),
            }
            # thresholds
            import os as _os
            rej_thresh = 0.02
            lat_thresh = 50.0
            try:
                rej_thresh = float(_os.getenv('CANARY_DIFF_REJECT_DELTA', '0.02'))
            except Exception:
                pass
            try:
                lat_thresh = float(_os.getenv('CANARY_DIFF_LAT_MS', '50'))
            except Exception:
                pass
            regressions = []
            if delta['reject_rate_green_minus_blue'] > rej_thresh:
                regressions.append('reject_rate_regression')
            if delta['latency_ms_delta'] > lat_thresh:
                regressions.append('latency_regression')
            if delta['split_observed_pct'] > 5.0:
                regressions.append('split_drift_regression')
            regressions = sorted(regressions)
            out = {'delta': delta, 'regressions': regressions}
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/report/canary/diff')
                except Exception:
                    pass
            return self._json_response(out)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_killswitch(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/killswitch')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/rollout/killswitch'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/rollout/killswitch')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            ks = getattr(self.config, 'killswitch', None)
            from src.common.config import CanaryKillSwitchConfig
            if ks is None:
                ks = CanaryKillSwitchConfig()
                self.config.killswitch = ks  # type: ignore[attr-defined]
            if request.method == 'GET':
                data = {
                    "enabled": bool(getattr(ks, 'enabled', False)),
                    "dry_run": bool(getattr(ks, 'dry_run', True)),
                    "max_reject_delta": float(getattr(ks, 'max_reject_delta', 0.02)),
                    "max_latency_delta_ms": int(getattr(ks, 'max_latency_delta_ms', 50)),
                    "min_fills": int(getattr(ks, 'min_fills', 500)),
                    "action": str(getattr(ks, 'action', 'rollback')),
                }
                self._admin_audit_record('/admin/rollout/killswitch', request, {"method": "GET"})
                return self._json_response(data)
            # POST
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            if not isinstance(body, dict):
                return self._json_response({"error": "invalid_payload"}, status=400)
            if 'enabled' in body:
                ks.enabled = bool(body['enabled'])
            if 'dry_run' in body:
                ks.dry_run = bool(body['dry_run'])
            if 'max_reject_delta' in body:
                try:
                    v = float(body['max_reject_delta'])
                except Exception:
                    return self._json_response({"error": "invalid_max_reject_delta"}, status=400)
                if v < 0.0:
                    return self._json_response({"error": "invalid_max_reject_delta"}, status=400)
                ks.max_reject_delta = v
            if 'max_latency_delta_ms' in body:
                try:
                    v = int(body['max_latency_delta_ms'])
                except Exception:
                    return self._json_response({"error": "invalid_max_latency_delta_ms"}, status=400)
                if v < 0 or v > 10000:
                    return self._json_response({"error": "invalid_max_latency_delta_ms"}, status=400)
                ks.max_latency_delta_ms = v
            if 'min_fills' in body:
                try:
                    v = int(body['min_fills'])
                except Exception:
                    return self._json_response({"error": "invalid_min_fills"}, status=400)
                if v < 0:
                    return self._json_response({"error": "invalid_min_fills"}, status=400)
                ks.min_fills = v
            if 'action' in body:
                a = str(body['action']).lower()
                if a not in ('rollback','freeze'):
                    return self._json_response({"error": "invalid_action"}, status=400)
                ks.action = a
            self._admin_audit_record('/admin/rollout/killswitch', request, body)
            data = {
                "enabled": bool(getattr(ks, 'enabled', False)),
                "dry_run": bool(getattr(ks, 'dry_run', True)),
                "max_reject_delta": float(getattr(ks, 'max_reject_delta', 0.02)),
                "max_latency_delta_ms": int(getattr(ks, 'max_latency_delta_ms', 50)),
                "min_fills": int(getattr(ks, 'min_fills', 500)),
                "action": str(getattr(ks, 'action', 'rollback')),
            }
            return self._json_response(data)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_promote(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/promote')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/rollout/promote'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/rollout/promote')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            # preview
            ro = getattr(self.config, 'rollout', None)
            rr = getattr(self.config, 'rollout_ramp', None)
            preview = {
                "active_new": "green",
                "ramp_enabled_new": False,
                "ramp_step_idx_new": 0,
                "traffic_split_pct_new": 0,
            }
            if request.method == 'GET':
                return self._json_response({"preview": preview})
            # POST: apply
            try:
                _ = await request.json()
            except Exception:
                _ = {}
            try:
                ro.active = 'green'
            except Exception:
                pass
            try:
                rr.enabled = False
            except Exception:
                pass
            self._ramp_state['frozen'] = False
            self._ramp_step_idx = 0
            try:
                self.config.rollout.traffic_split_pct = 0
            except Exception:
                pass
            self._rollout_state_dirty = True
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.set_ramp_enabled(False)
                    self.metrics.set_ramp_step_idx(0)
                    self.metrics.set_rollout_split_pct(0)
                    self.metrics.inc_autopromote_attempt()
                    self.metrics.inc_autopromote_flip()
                except Exception:
                    pass
            self._admin_audit_record('/admin/rollout/promote', request, {"manual": True})
            try:
                ts_iso = datetime.now(timezone.utc).isoformat()
                self._append_json_line(self._alerts_log_file(), {"ts": ts_iso, "kind": "autopromote_flip", "payload": {"auto": False}})
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_alert_event('autopromote_flip')
                    except Exception:
                        pass
            except Exception:
                pass
            return self._json_response({"status": "ok", "applied": preview})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_rollout_markout_snapshot(self, request):
        """Get markout snapshot for rollout quality assessment."""
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/rollout/markout_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/rollout/markout_snapshot'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/rollout/markout_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            
            # Get markout snapshot from metrics
            if hasattr(self, 'metrics') and hasattr(self.metrics, '_get_markout_snapshot_for_tests'):
                markout_data = self.metrics._get_markout_snapshot_for_tests()
                self._admin_audit_record('/admin/rollout/markout_snapshot', request, {})
                return self._json_response(markout_data)
            else:
                return self._json_response({"error": "markout metrics not available"}, status=503)
                
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_alerts_log(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/alerts/log')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/alerts/log'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/alerts/log')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            tail = 100
            try:
                q = request.rel_url.query
                if 'tail' in q:
                    tail = max(1, min(10000, int(q.get('tail'))))
            except Exception:
                tail = 100
            lines = []
            p = getattr(self, '_alerts_log_path', None) or self._alerts_log_file()
            try:
                from pathlib import Path as _P
                if _P(p).exists():
                    with open(p, 'r', encoding='utf-8') as f:
                        lines = f.read().splitlines()[-tail:]
            except Exception:
                lines = []
            # return parsed JSON lines deterministically
            out = []
            for ln in lines:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
            self._admin_audit_record('/admin/alerts/log', request, {"tail": tail})
            return self._json_response({"items": out})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_alerts_clear(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/alerts/clear')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/alerts/clear'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/alerts/clear')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            # atomic clear: replace file with empty
            self._admin_audit_record('/admin/alerts/clear', request, {"method": "POST"})
            try:
                self._atomic_json_write(self._alerts_log_file(), {})
                # Overwrite with empty content after atomic write created file
                with open(self._alerts_log_file(), 'w', encoding='utf-8') as f:
                    f.write("")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception:
                pass
            return self._json_response({"ok": True})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_anti_stale_guard(self, request):
        """Manage anti-stale order guard."""
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/anti-stale-guard')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/anti-stale-guard'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/anti-stale-guard')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/anti-stale-guard')
                except Exception:
                    pass
            
            method = request.method
            if method == "GET":
                # Get current status and configuration
                order_manager = getattr(self, 'order_manager', None)
                if not order_manager:
                    return self._json_response({"error": "order_manager_not_available"}, status=503)
                
                status = {
                    "enabled": order_manager.enable_anti_stale_guard,
                    "order_ttl_ms": order_manager.order_ttl_ms,
                    "price_drift_bps": order_manager.price_drift_bps,
                    "active_orders_count": len(order_manager.active_orders)
                }
                
                self._admin_audit_record('/admin/anti-stale-guard', request, status)
                return self._json_response(status)
                
            elif method == "POST":
                # Trigger manual check and refresh
                try:
                    body = await request.json()
                except Exception:
                    return self._json_response({"error": "invalid_json"}, status=400)
                
                symbol = body.get('symbol')  # Optional: check specific symbol
                
                order_manager = getattr(self, 'order_manager', None)
                if not order_manager:
                    return self._json_response({"error": "order_manager_not_available"}, status=503)
                
                # Perform manual check and refresh
                result = await order_manager.check_and_refresh_stale_orders(symbol)
                
                self._admin_audit_record('/admin/anti-stale-guard', request, result)
                return self._json_response(result)
                
            else:
                return self._json_response({"error": "method_not_allowed"}, status=405)
                
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_scheduler_suggest(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/scheduler/suggest')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/scheduler/suggest'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/scheduler/suggest')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            # collect synthetic stats from metrics (placeholders)
            stats = {}
            # simple deterministic demo over hour slots
            for h in range(0, 24, 2):
                key = f"{h:02d}:00-{(h+2)%24:02d}:00"
                stats[key] = {
                    "median_spread_bps": float((h % 10) + 1),
                    "vola_ewma": float(5 + (h % 6)),
                    "volume_norm": float((h % 4) / 3.0),
                    "sample": int(500),
                }
            cfg = {
                "top_k": 6,
                "min_sample": 200,
                "mode": "neutral",
            }
            try:
                q = request.rel_url.query
                if 'mode' in q:
                    cfg['mode'] = str(q.get('mode'))
                if 'top_k' in q:
                    cfg['top_k'] = int(q.get('top_k'))
                if 'min_sample' in q:
                    cfg['min_sample'] = int(q.get('min_sample'))
            except Exception:
                pass
            from src.scheduler.tod import suggest_windows
            wins = suggest_windows(stats, cfg)
            self._admin_audit_record('/admin/scheduler/suggest', request, cfg)
            return self._json_response({"windows": wins})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_scheduler_apply(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/scheduler/apply')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            actor = self._admin_actor_hash(request)
            if not self._admin_rate_limit_check(actor, '/admin/scheduler/apply'):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_rate_limited('/admin/scheduler/apply')
                    except Exception:
                        pass
                return self._json_response({"error": "rate_limited"}, status=429)
            try:
                body = await request.json()
            except Exception:
                return self._json_response({"error": "invalid_json"}, status=400)
            wins = body.get('windows') if isinstance(body, dict) else None
            if not isinstance(wins, list):
                return self._json_response({"error": "invalid_windows"}, status=400)
            # hot-apply to main scheduler
            try:
                sw = [{"name": f"win{i}", "days": [1,2,3,4,5,6,7], "start": w.get('start'), "end": w.get('end')} for i, w in enumerate(wins)]
                if getattr(self.ctx, 'scheduler', None):
                    self.ctx.scheduler.set_windows(sw)
            except Exception:
                pass
            # metric: applied counter
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.scheduler_reload_total.inc()
                except Exception:
                    pass
            self._admin_audit_record('/admin/scheduler/apply', request, {"count": len(wins)})
            return self._json_response({"status": "ok", "applied": len(wins)})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)
    # Event handlers
    async def _on_orderbook_update(self, orderbook):
        """Handle orderbook updates."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_orderbook(orderbook))
        
        # Update EWMA volatility for allocator
        try:
            if self.ctx and getattr(self.ctx, 'vola_manager', None):
                symbol = getattr(orderbook, 'symbol', None)
                mid = getattr(orderbook, 'mid_price', None)
                if symbol is None and isinstance(orderbook, dict):
                    symbol = orderbook.get('symbol')
                if mid is None and isinstance(orderbook, dict):
                    mid = orderbook.get('mid_price')
                if symbol and mid:
                    self.ctx.vola_manager.update(symbol=str(symbol), mid_price=float(mid))
            # WS lag if event_ts present
            try:
                evt_ts = None
                if isinstance(orderbook, dict):
                    evt_ts = orderbook.get('timestamp')
                else:
                    evt_ts = getattr(orderbook, 'timestamp', None)
                if evt_ts:
                    import time as _time
                    now_ts = _time.time()
                    now_ms = now_ts * 1000.0
                    event_ms = (evt_ts.timestamp() * 1000.0) if hasattr(evt_ts, 'timestamp') else float(evt_ts)
                    lag_ms = max(0.0, now_ms - event_ms)
                    if getattr(self.ctx, 'guard', None):
                        self.ctx.guard.set_ws_lag_ms(lag_ms, now_ts)
                    if getattr(self, 'metrics', None):
                        try:
                            self.metrics.ws_lag_ms.set(lag_ms)
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            pass
        
        if self.strategy:
            await self.strategy.on_orderbook_update(orderbook)
    
    async def _on_trade_update(self, trade):
        """Handle trade updates."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_trade(trade))
    
    async def _on_order_update(self, order):
        """Handle order updates."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_order(order))
    
    async def _on_execution_update(self, execution):
        """Handle execution updates."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_fill(execution))
    
    async def _on_orderbook_delta(self, delta):
        """Handle orderbook deltas."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_orderbook_delta(delta))
    
    async def _on_order_placed(self, order: Order):
        """Handle order placement."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_order(order))
    
    async def _on_quote_generated(self, quote: QuoteRequest):
        """Handle quote generation."""
        if self.data_recorder:
            asyncio.create_task(self.data_recorder.record_quote(quote))
    
    async def _rebalance_loop(self):
        """Periodic portfolio rebalance using EWMA volatilities with hot-reload detection."""
        try:
            interval_sec = max(1, int(getattr(self.config.portfolio, 'rebalance_minutes', 5) * 60))
        except Exception:
            interval_sec = 300
        
        while self.running:
            try:
                # Detect portfolio hot-reload changes; force immediate run if changed
                force_rebalance = False
                import hashlib
                _p = getattr(self.config, 'portfolio', None)
                _pd = _p.__dict__ if hasattr(_p, '__dict__') else {}
                _b = json.dumps(_pd, sort_keys=True, separators=(",", ":")).encode("utf-8")
                current_hash = hashlib.sha1(_b).hexdigest()
                if current_hash != self._last_portfolio_hash:
                    force_rebalance = True
                    self._last_portfolio_hash = current_hash
                
                stats = {}
                symbols = []
                try:
                    symbols = list(self.config.trading.symbols)
                except Exception:
                    symbols = []
                
                if self.ctx and getattr(self.ctx, 'vola_manager', None):
                    for sym in symbols:
                        vol = float(self.ctx.vola_manager.get_volatility(sym) or 0.0)
                        stats[sym] = {"vol": vol}
                
                if self.ctx and getattr(self.ctx, 'allocator', None):
                    if stats or force_rebalance:
                        targets = self.ctx.allocator.update(self.ctx, stats or {})
                        # Atomic replace
                        self.ctx.portfolio_targets = dict(targets)

                # Scheduler hot-reload and metrics
                try:
                    import hashlib
                    sc = getattr(self.config, 'scheduler', None)
                    if sc is not None:
                        sw = list(getattr(sc, 'windows', []) or [])
                        sws = getattr(sc, 'windows_by_symbol', {}) or {}
                        hol = []
                        try:
                            for h in getattr(sc, 'holidays', []) or []:
                                hol.append({'dates': list(getattr(h, 'dates', []) or []), 'symbols': list(getattr(h, 'symbols', []) or [])})
                        except Exception:
                            hol = []
                        stz = getattr(sc, 'tz', 'UTC') or 'UTC'
                        co = float(getattr(sc, 'cooldown_open_minutes', 0.0) or 0.0)
                        cc = float(getattr(sc, 'cooldown_close_minutes', 0.0) or 0.0)
                        bi = bool(getattr(sc, 'block_in_cooldown', True))
                        _b = json.dumps({'windows': sw, 'windows_by_symbol': sws, 'holidays': hol, 'tz': stz, 'co': co, 'cc': cc, 'bi': bi}, sort_keys=True, separators=(",", ":")).encode('utf-8')
                        h = hashlib.sha1(_b).hexdigest()
                        if h != getattr(self, '_last_scheduler_hash', None):
                            # Always recreate with all params
                            if sws:
                                self.ctx.schedulers = {}
                                for sym, wins in sws.items():
                                    self.ctx.schedulers[str(sym)] = TimeOfDayScheduler(list(wins or []), tz=stz, cooldown_open_minutes=co, cooldown_close_minutes=cc, block_in_cooldown=bi)
                                # apply holidays
                                try:
                                    for hobj in getattr(sc, 'holidays', []) or []:
                                        dates = list(getattr(hobj, 'dates', []) or [])
                                        targets = list(getattr(hobj, 'symbols', []) or [])
                                        target_syms = targets or list(self.ctx.schedulers.keys())
                                        for s in target_syms:
                                            if s in self.ctx.schedulers:
                                                self.ctx.schedulers[s].set_holidays(dates)
                                except Exception:
                                    pass
                                # clear global scheduler if map used
                                if hasattr(self.ctx, 'scheduler'):
                                    try:
                                        self.ctx.scheduler = None
                                    except Exception:
                                        pass
                            else:
                                self.ctx.scheduler = TimeOfDayScheduler(sw, tz=stz, cooldown_open_minutes=co, cooldown_close_minutes=cc, block_in_cooldown=bi)
                                try:
                                    for hobj in getattr(sc, 'holidays', []) or []:
                                        dates = list(getattr(hobj, 'dates', []) or [])
                                        if getattr(self.ctx, 'scheduler', None):
                                            self.ctx.scheduler.set_holidays(dates)
                                except Exception:
                                    pass
                            self._last_scheduler_hash = h
                            if getattr(self, 'metrics', None):
                                try:
                                    self.metrics.scheduler_reload_total.inc()
                                except Exception:
                                    pass
                    # Metrics export
                    if getattr(self, 'metrics', None):
                        # Global scheduler metrics (if present)
                        if getattr(self.ctx, 'scheduler', None):
                            curr_open = 1 if self.ctx.scheduler.is_open() else 0
                            self.metrics.scheduler_open.set(curr_open)
                            if self._prev_scheduler_open is None:
                                self._prev_scheduler_open = curr_open
                            elif curr_open != self._prev_scheduler_open:
                                state = "open" if curr_open == 1 else "closed"
                                try:
                                    self.metrics.scheduler_transitions_total.labels(state=state).inc()
                                except Exception:
                                    pass
                                self._prev_scheduler_open = curr_open
                            # Collect all names from config
                            names = []
                            try:
                                names = [w.get('name','') for w in (getattr(self.config.scheduler,'windows',[]) or [])]
                            except Exception:
                                names = []
                            active = self.ctx.scheduler.current_window()
                            for nm in names:
                                try:
                                    self.metrics.scheduler_window.labels(name=str(nm)).set(1 if active == nm else 0)
                                except Exception:
                                    pass
                            # cooldown, next-change metrics
                            cd = 0
                            try:
                                if self.ctx.scheduler.in_cooldown_open() or self.ctx.scheduler.in_cooldown_close():
                                    cd = 1
                            except Exception:
                                cd = 0
                            self.metrics.scheduler_cooldown_active.set(cd)
                            nxt = self.ctx.scheduler.next_change()
                            if nxt is not None:
                                import time as _time
                                self.metrics.scheduler_next_change_ts.set(nxt.timestamp())
                                self.metrics.scheduler_seconds_to_change.set(max(0.0, nxt.timestamp() - _time.time()))
                            else:
                                self.metrics.scheduler_next_change_ts.set(0)
                                self.metrics.scheduler_seconds_to_change.set(0)

                        # Per-symbol scheduler metrics (if map present)
                        sched_map = getattr(self.ctx, 'schedulers', None)
                        if isinstance(sched_map, dict) and sched_map:
                            for sym, sch in sched_map.items():
                                try:
                                    self.metrics.scheduler_open_by_symbol.labels(symbol=str(sym)).set(1 if sch.is_open() else 0)
                                except Exception:
                                    pass
                                try:
                                    in_cd = 0
                                    if getattr(sch, 'in_cooldown_open', None) and sch.in_cooldown_open():
                                        in_cd = 1
                                    if getattr(sch, 'in_cooldown_close', None) and sch.in_cooldown_close():
                                        in_cd = 1
                                    self.metrics.scheduler_cooldown_by_symbol.labels(symbol=str(sym)).set(in_cd)
                                except Exception:
                                    pass
                except Exception:
                    pass

                # Guard hot-reload and metrics
                try:
                    import hashlib, time as _time
                    rg = getattr(self.config, 'runtime_guard', None) or RuntimeGuardConfig()
                    _gd = rg.__dict__ if hasattr(rg, '__dict__') else {}
                    _b = json.dumps(_gd, sort_keys=True, separators=(",", ":")).encode('utf-8')
                    gh = hashlib.sha1(_b).hexdigest()
                    if gh != getattr(self, '_last_guard_hash', None):
                        self.ctx.guard = RuntimeGuard(rg)
                        self._last_guard_hash = gh
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.guard_reload_total.inc()
                            except Exception:
                                pass
                    
                    # Throttle hot-reload
                    th = getattr(self.config, 'throttle', None) or ThrottleConfig()
                    _td = th.__dict__ if hasattr(th, '__dict__') else {}
                    _bt = json.dumps(_td, sort_keys=True, separators=(",", ":")).encode('utf-8')
                    th_hash = hashlib.sha1(_bt).hexdigest()
                    if th_hash != getattr(self, '_last_throttle_hash', None):
                        self.ctx.throttle = ThrottleGuard(th)
                        self._last_throttle_hash = th_hash
                    # Circuit hot-reload
                    try:
                        cc = getattr(self.config, 'circuit', None)
                        _cd = cc.__dict__ if hasattr(cc, '__dict__') else {}
                        _bc = json.dumps(_cd, sort_keys=True, separators=(",", ":")).encode('utf-8')
                        ch = hashlib.sha1(_bc).hexdigest()
                        if ch != getattr(self, '_last_circuit_hash', None):
                            self.ctx.circuit = CircuitBreaker(cc)
                            self._last_circuit_hash = ch
                    except Exception:
                        pass
                    # Build snapshot and update guard
                    snap = {
                        'cancel_rate_per_sec': getattr(self.ctx, 'om_cancel_rate_per_sec', 0.0) if hasattr(self.ctx, 'om_cancel_rate_per_sec') else 0.0,
                        'cfg_max_cancel_per_sec': getattr(self.ctx, 'om_max_cancel_per_sec', 100.0),
                        'rest_error_rate': getattr(self.ctx, 'rest_error_rate', 0.0),
                        'pnl_slope_per_min': getattr(self.ctx, 'pnl_slope_per_min', 0.0),
                    }
                    if getattr(self.ctx, 'guard', None):
                        now_ts = _time.time()
                        self.ctx.guard.update(snap, now_ts)
                        if getattr(self, 'metrics', None):
                            try:
                                self.metrics.guard_paused.set(1 if self.ctx.guard.paused else 0)
                                self.metrics.guard_breach_streak.set(float(self.ctx.guard.breach_streak))
                                if getattr(self, '_last_guard_pauses_total', None) != self.ctx.guard.pauses_total:
                                    self.metrics.guard_pauses_total.inc()
                                    self._last_guard_pauses_total = self.ctx.guard.pauses_total
                                # effective pause: manual OR paused without dry_run
                                manual = bool(getattr(self.config.runtime_guard, 'manual_override_pause', False))
                                dry_run = bool(getattr(self.config.runtime_guard, 'dry_run', False))
                                effective = 1 if (manual or (self.ctx.guard.paused and not dry_run)) else 0
                                self.metrics.guard_paused_effective.set(effective)
                                
                                # Export throttle metrics
                                if getattr(self.ctx, 'throttle', None) and hasattr(self, 'metrics'):
                                    symbols = list(getattr(self.config.trading, 'symbols', []) or [])
                                    for sym in symbols:
                                        try:
                                            counts = self.ctx.throttle.get_window_counts(sym, now_ts)
                                            self.metrics.throttle_creates_in_window.labels(symbol=sym).set(counts.get('create', 0))
                                            self.metrics.throttle_amends_in_window.labels(symbol=sym).set(counts.get('amend', 0))
                                            self.metrics.throttle_cancels_in_window.labels(symbol=sym).set(counts.get('cancel', 0))
                                            backoff_ms = self.ctx.throttle.get_current_backoff_ms(sym)
                                            self.metrics.throttle_backoff_ms.labels(symbol=sym).set(backoff_ms)
                                            try:
                                                self.metrics.throttle_backoff_ms_max.set(self.ctx.throttle.get_backoff_ms_max())
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass
                                
                                # --- AutoPolicy evaluate/apply/metrics ---
                                ap = getattr(self.ctx, 'autopolicy', None)
                                th_state = getattr(self.ctx, 'throttle', None)
                                if ap and th_state and getattr(self, 'metrics', None):
                                    try:
                                        backoff_ms_max = float(getattr(th_state, 'get_backoff_ms_max', lambda: 0.0)() or 0.0)
                                        # Суммарные события окна: берём по всем символам
                                        total_events = 0
                                        try:
                                            syms = list(getattr(self.config.trading, 'symbols', []) or [])
                                        except Exception:
                                            syms = []
                                        for s in syms:
                                            try:
                                                c = th_state.get_window_counts(s, now_ts)
                                                total_events += int(c.get('create', 0) + c.get('amend', 0) + c.get('cancel', 0))
                                            except Exception:
                                                pass
                                        ap.evaluate(now_ts, backoff_ms_max, total_events)
                                        overrides = ap.apply()
                                        self.ctx.autopolicy_overrides = dict(overrides)
                                        m = ap.metrics()
                                        self.metrics.autopolicy_active.set(m["autopolicy_active"])
                                        self.metrics.autopolicy_level.set(m["autopolicy_level"])
                                        if m["autopolicy_steps_total"] > 0:
                                            self.metrics.autopolicy_steps_total.inc()
                                        self.metrics.autopolicy_last_change_ts.set(m["autopolicy_last_change_ts"])
                                        self.metrics.autopolicy_min_time_in_book_ms_eff.set(overrides.get("min_time_in_book_ms_eff", 0.0))
                                        self.metrics.autopolicy_replace_threshold_bps_eff.set(overrides.get("replace_threshold_bps_eff", 0.0))
                                        self.metrics.autopolicy_levels_per_side_max_eff.set(overrides.get("levels_per_side_max_eff", 0.0))
                                        # snapshot save (atomically)
                                        try:
                                            sp = self.config.autopolicy.snapshot_path
                                            if sp and int(now_ts) % max(1, int(self.config.autopolicy.snapshot_period_sec)) == 0:
                                                tmp = sp + ".tmp"
                                                with open(tmp, 'w', encoding='utf-8') as f:
                                                    import json
                                                    json.dump(ap.to_snapshot(), f, sort_keys=True, ensure_ascii=False, indent=2)
                                                os.replace(tmp, sp)
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass

                                # Circuit breaker tick and metrics
                                try:
                                    if getattr(self.ctx, 'circuit', None):
                                        self.ctx.circuit.tick(_time.time())
                                        st = self.ctx.circuit.state()
                                        for s in ('closed','open','half_open'):
                                            self.metrics.circuit_state.labels(state=s).set(1 if s==st else 0)
                                except Exception:
                                    pass

                                # throttle cancel-all per symbol while paused
                                if effective == 1:
                                    if getattr(self, '_last_guard_cancel_ts', 0) + 2.0 < now_ts:
                                        try:
                                            symbols = list(getattr(self.config.trading, 'symbols', []) or [])
                                        except Exception:
                                            symbols = []
                                        om = getattr(self.ctx, 'order_manager', None)
                                        if om:
                                            for sym in symbols:
                                                try:
                                                    await om.cancel_all_for_symbol(sym)
                                                except Exception:
                                                    pass
                                        self._last_guard_cancel_ts = now_ts
                                # export last reason and change ts
                                try:
                                    self.metrics.guard_last_reason.set(float(getattr(self.ctx.guard, 'last_reason_mask', 0)))
                                    self.metrics.guard_last_change_ts.set(float(getattr(self.ctx.guard, 'last_change_ts', 0.0)))
                                    # dry-run / manual override
                                    self.metrics.guard_dry_run.set(1 if getattr(self.config.runtime_guard, 'dry_run', False) else 0)
                                    self.metrics.guard_manual_override.set(1 if getattr(self.config.runtime_guard, 'manual_override_pause', False) else 0)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        # Periodic snapshot save
                        try:
                            last_ss = getattr(self, '_last_guard_snapshot_ts', 0.0)
                            period = float(getattr(self.config.runtime_guard, 'snapshot_period_sec', 60))
                            if now_ts - last_ss >= max(1.0, period):
                                spath = getattr(self.config.runtime_guard, 'snapshot_path', 'artifacts/runtime_guard.json')
                                import json as _json, os as _os
                                snap = self.ctx.guard.to_snapshot()
                                payload = _json.dumps(snap, sort_keys=True, separators=(",", ":"))
                                tmp = spath + ".tmp"
                                # ensure dir exists
                                try:
                                    from pathlib import Path as _P
                                    _P(spath).parent.mkdir(parents=True, exist_ok=True)
                                except Exception:
                                    pass
                                with open(tmp, 'w') as f:
                                    f.write(payload)
                                try:
                                    _os.replace(tmp, spath)
                                except Exception:
                                    # fallback
                                    _os.rename(tmp, spath)
                                self._last_guard_snapshot_ts = now_ts
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass
            
            await asyncio.sleep(interval_sec)
    
    async def _simulate_ticks(self):
        """Simulate market data ticks for dry-run mode."""
        if not self.dry_run:
            return
        
        # Simulate basic orderbook updates
        mock_orderbook = {
            "symbol": "BTCUSDT",
            "timestamp": datetime.now(timezone.utc),
            "bids": [[50000, 1.0], [49999, 2.0]],
            "asks": [[50001, 1.0], [50002, 2.0]]
        }
        
        await self._on_orderbook_update(mock_orderbook)

    async def _admin_perf_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/perf/snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/perf/snapshot')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            snap = {}
            if m and hasattr(m, '_get_perf_snapshot_for_tests'):
                snap = m._get_perf_snapshot_for_tests()
            return self._json_response(snap)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_perf_soak_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/perf/soak_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/perf/soak_snapshot')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            snap = {}
            if m and hasattr(m, '_get_soak_snapshot_for_tests'):
                snap = m._get_soak_snapshot_for_tests()
            return self._json_response(snap)
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)

    async def _admin_allocator_obs_snapshot(self, request):
        try:
            if not self._check_admin_token(request):
                if getattr(self, 'metrics', None):
                    try:
                        self.metrics.inc_admin_unauthorized('/admin/allocator/obs_snapshot')
                    except Exception:
                        pass
                return self._json_response({"error": "unauthorized"}, status=401)
            if getattr(self, 'metrics', None):
                try:
                    self.metrics.inc_admin_request('/admin/allocator/obs_snapshot')
                except Exception:
                    pass
            m = getattr(self, 'metrics', None)
            snap = {}
            if m and hasattr(m, '_get_allocator_obs_snapshot_for_tests'):
                snap = m._get_allocator_obs_snapshot_for_tests()
            return self._json_response({"symbols": snap})
        except Exception as e:
            return self._json_response({"error": str(e)}, status=500)


async def main():
    """Main entry point."""
    bot = None
    recorder: Optional[Recorder] = None
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        """
        Handle shutdown signals (SIGINT, SIGTERM).
        
        Sets shutdown_event to trigger graceful shutdown in async context.
        This is the correct way to handle signals in asyncio - don't use
        asyncio.create_task() in signal handlers as they run synchronously.
        """
        print(f"\n[SHUTDOWN] Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()
    
    def sighup_handler(signum, frame):
        """Handle SIGHUP for config reload."""
        print(f"Received SIGHUP, reloading configuration...")
        if bot and hasattr(bot, '_admin_reload'):
            # Create a mock request object for the reload method
            class MockRequest:
                def __init__(self):
                    pass
            try:
                asyncio.create_task(bot._admin_reload(MockRequest()))
                print("Configuration reloaded successfully")
            except Exception as e:
                print(f"Failed to reload configuration: {e}")
    
    try:
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        # SIGHUP is not available on Windows
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, sighup_handler)
        
        print("Market Maker Bot Starting...")
        print("=" * 50)
        
        # Args
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--config", default="config.yaml")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--profile", choices=["testnet", "mainnet", "paper"], default=None)
        parser.add_argument("--paper", action="store_true", help="Enable paper trading mode")
        # Throttle snapshot flags
        parser.add_argument("--throttle-snapshot-path", default="artifacts/throttle_snapshot.json")
        parser.add_argument("--throttle-snapshot-interval-seconds", type=int, default=30)
        try:
            args, _ = parser.parse_known_args()
        except SystemExit:
            args = argparse.Namespace(config="config.yaml", dry_run=False, profile=None)

        # Load configuration
        config_path = args.config
        if not Path(config_path).exists():
            print(f"Configuration file not found: {config_path}")
            print("Please ensure config.yaml exists in the current directory")
            sys.exit(1)
        
        # Load configuration using new ConfigLoader
        from src.common.config import ConfigLoader
        loader = ConfigLoader(config_path)
        config = loader.load()
        
        print(f"Configuration loaded successfully")
        print(f"Config version: {getattr(config, 'config_version', 'unknown')}")
        print(f"Git SHA: {get_git_sha()}")
        print(f"Config hash: {cfg_hash_sanitized(config)[:8]}...")
        print(f"Trading pairs: {', '.join(config.trading.symbols)}")
        print(f"Environment: {'TESTNET' if config.bybit.use_testnet else 'MAINNET'}")
        print(f"Storage backend: {config.storage.backend}")
        print(f"Risk limits: ${config.risk.max_position_usd} max position, ${config.risk.daily_max_loss_usd} daily loss limit")
        print("=" * 50)
        
        # Create recorder
        recorder = Recorder(config)
        print("Recorder initialized")
        
        # Create and initialize bot
        paper_mode = args.paper or (args.profile == "paper")
        bot = MarketMakerBot(config_path=config_path, recorder=recorder, dry_run=bool(args.dry_run), profile=args.profile)
        # propagate throttle snapshot flags
        try:
            bot._throttle_snapshot_path = getattr(args, 'throttle_snapshot_path', 'artifacts/throttle_snapshot.json')
            bot._throttle_snapshot_interval = int(getattr(args, 'throttle_snapshot_interval_seconds', 30))
        except Exception:
            bot._throttle_snapshot_path = 'artifacts/throttle_snapshot.json'
            bot._throttle_snapshot_interval = 30
        if paper_mode:
            bot.paper_mode = True
        await bot.initialize()
        print("Bot components initialized")
        
        # Start recorder
        print("Starting recorder...")
        await recorder.start()
        print("Recorder started")
        
        # Start bot
        print("Starting bot...")
        bot_task = asyncio.create_task(bot.start())
        
        # Wait for either bot to finish or shutdown signal
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [bot_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # If shutdown was requested, cancel bot task
        if shutdown_task in done:
            print("[SHUTDOWN] Shutdown signal received, stopping bot...")
            if not bot_task.done():
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
        
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Keyboard interrupt received")
    except Exception as e:
        print(f"[ERROR] Bot error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\n" + "=" * 60)
        print("[SHUTDOWN] Initiating graceful shutdown sequence...")
        print("=" * 60)
        
        # Step 1: Stop bot (includes order cancellation)
        if bot:
            try:
                print("[SHUTDOWN] Step 1/2: Stopping bot (cancelling orders, closing connections)...")
                await asyncio.wait_for(bot.stop(), timeout=30.0)
                print("[SHUTDOWN] ✓ Bot stopped successfully")
            except asyncio.TimeoutError:
                print("[SHUTDOWN] ⚠ Bot stop timeout (30s exceeded), forcing shutdown...")
            except Exception as e:
                print(f"[SHUTDOWN] ✗ Error stopping bot: {e}")
        
        # Step 2: Stop recorder
        if recorder:
            try:
                print("[SHUTDOWN] Step 2/2: Stopping recorder (flushing data)...")
                await asyncio.wait_for(recorder.stop(), timeout=10.0)
                print("[SHUTDOWN] ✓ Recorder stopped successfully")
            except asyncio.TimeoutError:
                print("[SHUTDOWN] ⚠ Recorder stop timeout (10s exceeded), data may be lost...")
            except Exception as e:
                print(f"[SHUTDOWN] ✗ Error stopping recorder: {e}")
        
        print("=" * 60)
        print("[SHUTDOWN] Shutdown complete")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
