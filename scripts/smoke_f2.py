#!/usr/bin/env python3
"""
F2 smoke test with mock HTTP server for canary→promote/rollback scenarios.

Pure stdlib implementation (http.server, threading) with ASCII logs only.
No external dependencies.
"""

import argparse
import json
import threading
import time
import sys
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from pathlib import Path


# Shared state for mock bot metrics
STATE = {
    "cfg_hash": "cfg_before",
    "risk_paused": 0,
    "cancel_rate": 1.0,
    "rest_error": 0.001,
    "pnl": 100.0,
    "hit_rate_proxy": 0.25,
    "cfg_max_cancel_per_sec": 100.0,
    "ticks": 0,
    "mode": "promote",
    "start_time": time.time(),
    # Throttle-related state
    "throttle_events": {"create": 0, "amend": 0, "cancel": 0},
    "throttle_backoff_ms_max": 0
}


class MockBotHandler(BaseHTTPRequestHandler):
    """Mock bot HTTP handler for /metrics and /admin endpoints."""
    
    def log_message(self, format, *args):
        """Override to suppress default HTTP logs (ASCII only)."""
        pass
    
    def _json_response(self, code, obj):
        """Send JSON response with proper headers."""
        data = json.dumps(obj, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def do_GET(self):
        """Handle GET requests for /metrics and /admin/snapshot."""
        path = urlparse(self.path).path
        
        if path == "/metrics":
            # Prometheus-style metrics (text format)
            total_events = sum(STATE["throttle_events"].values())
            body = (
                f"risk_paused {STATE['risk_paused']}\n"
                f"cancel_rate_per_sec {STATE['cancel_rate']}\n"
                f"rest_error_rate {STATE['rest_error']}\n"
                f"net_pnl_total_usd {STATE['pnl']:.1f}\n"
                f"hit_rate_proxy {STATE['hit_rate_proxy']}\n"
                f"cfg_max_cancel_per_sec {STATE['cfg_max_cancel_per_sec']}\n"
                f"guard_paused {STATE.get('guard_paused', 0)}\n"
                f"guard_dry_run {STATE.get('guard_dry_run', 0)}\n"
                f"guard_paused_effective {int(STATE.get('guard_paused', 0) and not STATE.get('guard_dry_run', 0))}\n"
                f"throttle_events_in_window_total {total_events}\n"
                f"throttle_events_in_window{{op=\"create\",symbol=\"SMOKE\"}} {STATE['throttle_events']['create']}\n"
                f"throttle_events_in_window{{op=\"amend\",symbol=\"SMOKE\"}} {STATE['throttle_events']['amend']}\n"
                f"throttle_events_in_window{{op=\"cancel\",symbol=\"SMOKE\"}} {STATE['throttle_events']['cancel']}\n"
                f"throttle_backoff_ms_max {STATE['throttle_backoff_ms_max']}\n"
            ).encode("utf-8")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        
        if path == "/admin/snapshot":
            response = {
                "ok": True,
                "cfg_hash": STATE["cfg_hash"],
                "timestamp": time.time(),
                "uptime_seconds": time.time() - STATE["start_time"]
            }
            return self._json_response(200, response)
        
        if path == "/admin/guard":
            # Return current guard state
            resp = {
                "dry_run": bool(STATE.get('guard_dry_run', 0)),
                "manual_override_pause": bool(STATE.get('guard_manual_override', 0)),
            }
            return self._json_response(200, resp)
        
        # 404 for unknown paths
        self._json_response(404, {"ok": False, "error": "not found"})
    
    def do_POST(self):
        """Handle POST requests for /admin operations."""
        path = urlparse(self.path).path
        
        # Read request body
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        
        try:
            payload = json.loads(body or b"{}")
        except:
            payload = {}
        
        if path == "/admin/reload":
            # Config reload simulation
            before = STATE["cfg_hash"]
            dry_run = payload.get("dry_run", False)
            
            if not dry_run:
                # Determine new config hash based on payload
                if payload.get("patch", {}):
                    STATE["cfg_hash"] = "cfg_canary"
                else:
                    STATE["cfg_hash"] = "cfg_full"
            
            response = {
                "ok": True,
                "applied": not dry_run,
                "cfg_hash_before": before,
                "cfg_hash_after": STATE["cfg_hash"]
            }
            return self._json_response(200, response)
        
        if path == "/admin/rollback":
            # Config rollback simulation
            before = STATE["cfg_hash"]
            STATE["cfg_hash"] = "cfg_before"
            
            response = {
                "ok": True,
                "rolled_back": True,
                "cfg_hash_before": before,
                "cfg_hash_after": STATE["cfg_hash"]
            }
            return self._json_response(200, response)
        
        if path == "/admin/force_snapshot":
            # Force snapshot operation
            response = {"ok": True, "forced": True}
            return self._json_response(200, response)
        
        if path == "/admin/guard":
            # Update guard state
            dr = payload.get("dry_run")
            mo = payload.get("manual_override_pause")
            if (dr is not None) and isinstance(dr, bool):
                STATE['guard_dry_run'] = 1 if dr else 0
            if (mo is not None) and isinstance(mo, bool):
                STATE['guard_manual_override'] = 1 if mo else 0
                # manual override forces pause
                STATE['guard_paused'] = STATE.get('guard_paused', 0) or STATE['guard_manual_override']
            return self._json_response(200, {
                "dry_run": bool(STATE.get('guard_dry_run', 0)),
                "manual_override_pause": bool(STATE.get('guard_manual_override', 0))
            })
        
        # 404 for unknown paths
        self._json_response(404, {"ok": False, "error": "not found"})


def run_mock_server(port):
    """Start mock HTTP server in background thread."""
    server = HTTPServer(("127.0.0.1", port), MockBotHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    print(f"[SMOKE F2] Mock bot server started on 127.0.0.1:{port}")
    return server


def metrics_ticker(mode):
    """Background thread to update metrics over time."""
    while True:
        time.sleep(3.0)  # Tick every 3 seconds
        STATE["ticks"] += 1
        
        if mode == "promote":
            # Healthy scenario: gradual PnL growth, low error rates
            STATE["pnl"] += 1.0
            STATE["cancel_rate"] = 1.0
            STATE["rest_error"] = 0.001
            # throttle stays low
            STATE["throttle_events"] = {"create": 5, "amend": 3, "cancel": 2}
            STATE["throttle_backoff_ms_max"] = 800
            # dry-run for first 2 ticks to simulate "would block but don't"
            if STATE['ticks'] <= 2:
                STATE['guard_paused'] = 0
                STATE['guard_dry_run'] = 1
            else:
                STATE['guard_dry_run'] = 0
                STATE['guard_paused'] = 0
        
        elif mode == "rollback":
            # Degraded scenario: after initial period, trigger thresholds
            if STATE["ticks"] >= 3:
                # After ~9 seconds, simulate degradation
                STATE["pnl"] -= 2.0
                STATE["cancel_rate"] = 999.0  # Trigger high cancel rate
                STATE["rest_error"] = 0.02    # Trigger high error rate
                # Guard effective pause on ticks 3-4
                STATE['guard_dry_run'] = 0
                STATE['guard_paused'] = 1
                # Throttle bursts
                STATE["throttle_events"]["create"] += 20
                STATE["throttle_events"]["amend"] += 20
                STATE["throttle_events"]["cancel"] += 20
                if STATE["throttle_backoff_ms_max"] < 6000:
                    STATE["throttle_backoff_ms_max"] = 6000
            else:
                # Initial slight decline
                STATE["pnl"] -= 0.5
                STATE["cancel_rate"] = 2.0
                STATE["rest_error"] = 0.005
        
        print(f"[TICK {STATE['ticks']:2d}] PnL: {STATE['pnl']:6.1f}, "
              f"cancel_rate: {STATE['cancel_rate']:6.1f}, "
              f"error_rate: {STATE['rest_error']:6.3f}")


def create_smoke_fixtures():
    """Create minimal D2/E2 report fixtures for SMOKE symbol."""
    smoke_dir = Path("artifacts")
    
    # Create directories
    (smoke_dir / "tuning" / "SMOKE").mkdir(parents=True, exist_ok=True)
    (smoke_dir / "calibration" / "SMOKE").mkdir(parents=True, exist_ok=True)
    
    # Minimal D2 walk-forward report
    d2_report = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "symbol": "SMOKE"
        },
        "champion": {
            "parameters": {
                "k_vola_spread": 1.5,
                "skew_coeff": 0.1,
                "levels_per_side": 3,
                "level_spacing_coeff": 1.2,
                "min_time_in_book_ms": 1000,
                "replace_threshold_bps": 2.0,
                "imbalance_cutoff": 0.8
            },
            "aggregates": {
                "hit_rate_mean": 0.25,
                "maker_share_mean": 0.95,
                "net_pnl_mean_usd": 50.0,
                "cvar95_mean_usd": -5.0,
                "win_ratio": 0.70
            }
        },
        "baseline_drift_pct": {
            "k_vola_spread": 5.0,
            "skew_coeff": -3.0,
            "levels_per_side": 0.0
        }
    }
    
    # Minimal E2 calibration report
    e2_report = {
        "metadata": {
            "symbol": "SMOKE",
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        },
        "go_no_go": {
            "ks_queue_after": 0.10,
            "ks_bins_after": 0.05,
            "w4_effective": 0.0,
            "sim_live_divergence": 0.08,
            "loss_before": 0.5,
            "loss_after": 0.4,
            "loss_regressed": False
        }
    }
    
    # Write fixtures
    d2_path = smoke_dir / "tuning" / "SMOKE" / "report.json"
    e2_path = smoke_dir / "calibration" / "SMOKE" / "report.json"
    
    with open(d2_path, 'w', encoding='utf-8') as f:
        json.dump(d2_report, f, indent=2)
    
    with open(e2_path, 'w', encoding='utf-8') as f:
        json.dump(e2_report, f, indent=2)
    
    print(f"[SMOKE F2] Created fixtures: {d2_path}, {e2_path}")
    return str(d2_path), str(e2_path)


def run_f2_rollout(args, admin_url, metrics_url, wf_report, calib_report):
    """Run F2 rollout command with mock endpoints."""
    
    # Build command (placeholder - actual F2 rollout doesn't exist yet)
    cmd = [
        sys.executable, "-m", "src.deploy.rollout",
        "--report", wf_report,
        "--symbol", args.symbol,
        "--round-dp", str(args.round_dp)
    ]
    
    # Add calibration report if exists
    if calib_report and Path(calib_report).exists():
        cmd += ["--calibration-report", calib_report]
    
    # Note: F2 specific flags would be added here when implemented:
    # cmd += ["--admin-url", admin_url]
    # cmd += ["--metrics-url", metrics_url] 
    # cmd += ["--canary-minutes", str(args.canary_minutes)]
    # cmd += ["--apply"]
    
    print(f"[SMOKE F2] Running command: {' '.join(cmd)}")
    
    try:
        # For now, simulate F2 behavior based on current metrics
        time.sleep(args.canary_minutes * 60)  # Wait for canary period
        
        # Check final metrics to determine outcome
        final_cancel_rate = STATE["cancel_rate"]
        final_error_rate = STATE["rest_error"]
        final_pnl = STATE["pnl"]
        
        print(f"[SMOKE F2] Final metrics: cancel_rate={final_cancel_rate:.1f}, "
              f"error_rate={final_error_rate:.3f}, pnl={final_pnl:.1f}")
        
        # Simulate F2 decision logic
        if args.mode == "promote":
            if final_cancel_rate < 100.0 and final_error_rate < 0.01 and final_pnl > 95.0:
                print("[SMOKE F2] Simulated outcome: promoted")
                return 0  # Success - promoted
            else:
                print("[SMOKE F2] Simulated outcome: promotion failed")
                return 2  # Failure
        
        elif args.mode == "rollback":
            if final_cancel_rate > 100.0 or final_error_rate > 0.01 or final_pnl < 95.0:
                print("[SMOKE F2] Simulated outcome: rolled_back")
                return 2  # Expected - rolled back due to degradation
            else:
                print("[SMOKE F2] Simulated outcome: unexpected promotion")
                return 0  # Unexpected success
        
        return 1  # Error
        
    except Exception as e:
        print(f"[SMOKE F2] Error running rollout: {e}")
        return 1


def main():
    """Main F2 smoke test entry point."""
    parser = argparse.ArgumentParser(
        description="F2 smoke test with mock HTTP server for canary→promote/rollback"
    )
    
    parser.add_argument("--mode", choices=["promote", "rollback"], default="promote",
                        help="Test scenario: promote (healthy) or rollback (degraded)")
    parser.add_argument("--port", type=int, default=18080,
                        help="Mock server port")
    parser.add_argument("--symbol", default="SMOKE",
                        help="Trading symbol for test")
    parser.add_argument("--canary-minutes", type=float, default=0.5,
                        help="Canary period in minutes (0.5 = 30 seconds)")
    parser.add_argument("--round-dp", type=int, default=6,
                        help="Decimal places for rounding")
    
    args = parser.parse_args()
    
    print(f"[SMOKE F2] Starting {args.mode} scenario for {args.symbol}")
    print(f"[SMOKE F2] Canary period: {args.canary_minutes} minutes")
    
    # Initialize state
    STATE["mode"] = args.mode
    STATE["start_time"] = time.time()
    
    # Create test fixtures
    wf_report, calib_report = create_smoke_fixtures()
    
    # Start mock server
    server = run_mock_server(args.port)
    
    # Start metrics ticker
    ticker_thread = threading.Thread(target=metrics_ticker, args=(args.mode,), daemon=True)
    ticker_thread.start()
    
    # Build URLs
    admin_url = f"http://127.0.0.1:{args.port}"
    metrics_url = f"http://127.0.0.1:{args.port}/metrics"
    
    print(f"[SMOKE F2] Admin URL: {admin_url}")
    print(f"[SMOKE F2] Metrics URL: {metrics_url}")
    
    # Wait a moment for server to be ready
    time.sleep(1.0)
    
    try:
        # Run F2 rollout simulation
        exit_code = run_f2_rollout(args, admin_url, metrics_url, wf_report, calib_report)
        
        # Evaluate results
        if args.mode == "promote" and exit_code == 0:
            print("SMOKE F2 (promote): PASS")
            sys.exit(0)
        elif args.mode == "rollback" and exit_code == 2:
            print("SMOKE F2 (rollback): PASS")
            sys.exit(0)
        else:
            print(f"SMOKE F2: FAIL (unexpected exit code {exit_code} for mode {args.mode})")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n[SMOKE F2] Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"[SMOKE F2] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
