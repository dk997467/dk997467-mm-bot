"""
Calibration loggers for fills and pipeline ticks.

Logs:
- fills_YYYYMMDD.jsonl: Fill events with full context
- pipeline_ticks_YYYYMMDD.jsonl: Pipeline tick snapshots

Format: One JSON object per line (JSONL), deterministic, no gaps.
"""
import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import orjson
import threading

logger = logging.getLogger(__name__)


class FillLogger:
    """
    Logs fill events to JSONL for calibration.
    
    Format: artifacts/edge/feeds/fills_YYYYMMDD.jsonl
    Fields: ts, symbol, side, price, qty, maker/taker, queue_pos_est,
            mid, spread_at_quote, latency_ms, slip_bps
    """
    
    def __init__(self, artifacts_dir: str = "artifacts/edge/feeds"):
        """
        Initialize fill logger.
        
        Args:
            artifacts_dir: Directory for fill logs
        """
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        self._current_date = None
        self._file_handle = None
        
        logger.info(f"[FILL_LOGGER] Initialized: dir={self.artifacts_dir}")
    
    def log_fill(
        self,
        symbol: str,
        side: str,
        fill_price: float,
        qty: float,
        is_maker: bool,
        quote_price: float,
        mid_at_quote: float,
        mid_now: float,
        spread_at_quote_bps: float,
        latency_ms: float,
        queue_position: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a fill event.
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            fill_price: Actual fill price
            qty: Fill quantity
            is_maker: True if maker fill
            quote_price: Our quoted price
            mid_at_quote: Mid price when we quoted
            mid_now: Current mid price
            spread_at_quote_bps: Spread at quote time (bps)
            latency_ms: Time from quote to fill (ms)
            queue_position: Estimated queue position
            metadata: Additional metadata
        """
        with self._lock:
            # Check if we need to rotate file (new day)
            current_date = datetime.utcnow().strftime("%Y%m%d")
            if current_date != self._current_date:
                self._rotate_file(current_date)
            
            # Calculate slippage
            slip_bps = abs((fill_price - quote_price) / quote_price * 10000)
            
            # Build event
            event = {
                "ts": int(time.time() * 1000),
                "ts_iso": datetime.utcnow().isoformat() + "Z",
                "symbol": symbol,
                "side": side,
                "price": fill_price,
                "qty": qty,
                "maker": is_maker,
                "taker": not is_maker,
                "queue_pos_est": queue_position,
                "quote_price": quote_price,
                "mid_at_quote": mid_at_quote,
                "mid_now": mid_now,
                "spread_at_quote_bps": spread_at_quote_bps,
                "latency_ms": latency_ms,
                "slip_bps": slip_bps
            }
            
            # Add metadata
            if metadata:
                event["metadata"] = metadata
            
            # Write to file (one line, no trailing newline yet)
            if self._file_handle:
                try:
                    line = orjson.dumps(event).decode("utf-8")
                    self._file_handle.write(line + "\n")
                    self._file_handle.flush()
                except Exception as e:
                    logger.error(f"[FILL_LOGGER] Failed to write fill: {e}")
    
    def _rotate_file(self, date_str: str):
        """
        Rotate to new file for new date.
        
        Args:
            date_str: Date string (YYYYMMDD)
        """
        # Close old file
        if self._file_handle:
            self._file_handle.close()
        
        # Open new file
        filename = f"fills_{date_str}.jsonl"
        filepath = self.artifacts_dir / filename
        
        try:
            self._file_handle = open(filepath, "a", encoding="utf-8")
            self._current_date = date_str
            logger.info(f"[FILL_LOGGER] Rotated to {filepath}")
        except Exception as e:
            logger.error(f"[FILL_LOGGER] Failed to open {filepath}: {e}")
            self._file_handle = None
    
    def close(self):
        """Close file handle."""
        with self._lock:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
                logger.info("[FILL_LOGGER] Closed")


class PipelineTickLogger:
    """
    Logs pipeline tick snapshots to JSONL for calibration.
    
    Format: artifacts/edge/feeds/pipeline_ticks_YYYYMMDD.jsonl
    Fields: ts, stages_p95_snapshot, pricing_on_stale, md_cache_age,
            hit/miss, deadline_miss
    """
    
    def __init__(
        self,
        artifacts_dir: str = "artifacts/edge/feeds",
        sample_rate: int = 10
    ):
        """
        Initialize pipeline tick logger.
        
        Args:
            artifacts_dir: Directory for tick logs
            sample_rate: Log every Nth tick (1 = all ticks)
        """
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        
        self._lock = threading.Lock()
        self._current_date = None
        self._file_handle = None
        self._tick_counter = 0
        
        logger.info(
            f"[PIPELINE_TICK_LOGGER] Initialized: dir={self.artifacts_dir}, "
            f"sample_rate={sample_rate}"
        )
    
    def log_tick(
        self,
        symbol: str,
        stage_latencies: Dict[str, float],
        tick_total_ms: float,
        cache_hit: bool,
        cache_age_ms: int,
        used_stale: bool,
        deadline_miss: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a pipeline tick snapshot.
        
        Args:
            symbol: Trading symbol
            stage_latencies: Stage name -> latency (ms)
            tick_total_ms: Total tick time (ms)
            cache_hit: MD cache hit
            cache_age_ms: MD cache age (ms)
            used_stale: Used stale MD
            deadline_miss: Missed deadline
            metadata: Additional metadata
        """
        with self._lock:
            # Sample: log every Nth tick
            self._tick_counter += 1
            if self._tick_counter % self.sample_rate != 0:
                return
            
            # Check if we need to rotate file (new day)
            current_date = datetime.utcnow().strftime("%Y%m%d")
            if current_date != self._current_date:
                self._rotate_file(current_date)
            
            # Calculate stage p95 (simplified: use max as proxy)
            stage_p95 = max(stage_latencies.values()) if stage_latencies else 0.0
            
            # Build event
            event = {
                "ts": int(time.time() * 1000),
                "ts_iso": datetime.utcnow().isoformat() + "Z",
                "symbol": symbol,
                "stage_latencies": stage_latencies,
                "stage_p95_ms": stage_p95,
                "tick_total_ms": tick_total_ms,
                "cache_hit": cache_hit,
                "cache_age_ms": cache_age_ms,
                "used_stale": used_stale,
                "deadline_miss": deadline_miss
            }
            
            # Add metadata
            if metadata:
                event["metadata"] = metadata
            
            # Write to file
            if self._file_handle:
                try:
                    line = orjson.dumps(event).decode("utf-8")
                    self._file_handle.write(line + "\n")
                    self._file_handle.flush()
                except Exception as e:
                    logger.error(f"[PIPELINE_TICK_LOGGER] Failed to write tick: {e}")
    
    def _rotate_file(self, date_str: str):
        """
        Rotate to new file for new date.
        
        Args:
            date_str: Date string (YYYYMMDD)
        """
        # Close old file
        if self._file_handle:
            self._file_handle.close()
        
        # Open new file
        filename = f"pipeline_ticks_{date_str}.jsonl"
        filepath = self.artifacts_dir / filename
        
        try:
            self._file_handle = open(filepath, "a", encoding="utf-8")
            self._current_date = date_str
            logger.info(f"[PIPELINE_TICK_LOGGER] Rotated to {filepath}")
        except Exception as e:
            logger.error(f"[PIPELINE_TICK_LOGGER] Failed to open {filepath}: {e}")
            self._file_handle = None
    
    def close(self):
        """Close file handle."""
        with self._lock:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
                logger.info("[PIPELINE_TICK_LOGGER] Closed")


class CalibrationLoggerManager:
    """
    Manages fill and pipeline tick loggers.
    
    Provides unified interface for calibration logging.
    """
    
    def __init__(
        self,
        artifacts_dir: str = "artifacts/edge/feeds",
        pipeline_sample_rate: int = 10,
        enabled: bool = True
    ):
        """
        Initialize logger manager.
        
        Args:
            artifacts_dir: Directory for logs
            pipeline_sample_rate: Sample rate for pipeline ticks
            enabled: Feature flag to enable logging
        """
        self.enabled = enabled
        
        if enabled:
            self.fill_logger = FillLogger(artifacts_dir)
            self.pipeline_tick_logger = PipelineTickLogger(
                artifacts_dir, pipeline_sample_rate
            )
        else:
            self.fill_logger = None
            self.pipeline_tick_logger = None
        
        logger.info(
            f"[CALIB_LOGGER_MGR] Initialized: enabled={enabled}, "
            f"dir={artifacts_dir}"
        )
    
    def log_fill(self, **kwargs):
        """Log fill event."""
        if self.enabled and self.fill_logger:
            self.fill_logger.log_fill(**kwargs)
    
    def log_pipeline_tick(self, **kwargs):
        """Log pipeline tick."""
        if self.enabled and self.pipeline_tick_logger:
            self.pipeline_tick_logger.log_tick(**kwargs)
    
    def close(self):
        """Close all loggers."""
        if self.fill_logger:
            self.fill_logger.close()
        if self.pipeline_tick_logger:
            self.pipeline_tick_logger.close()

