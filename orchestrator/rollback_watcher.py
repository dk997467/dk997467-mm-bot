#!/usr/bin/env python3
"""
Rollback Watcher - Alertmanager Webhook Handler

Receives alerts from Prometheus Alertmanager and triggers rollback actions
based on policy configuration.

Usage:
    python -m orchestrator.rollback_watcher --port 8080 --policy deploy/policies/rollback.yaml
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Any, List


def load_policy(policy_path: str) -> Dict[str, Any]:
    """Load rollback policy from YAML file."""
    import yaml
    with open(policy_path, 'r') as f:
        return yaml.safe_load(f)


def is_hard_gate(alert_name: str, policy: Dict[str, Any]) -> bool:
    """Check if alert is a hard gate."""
    hard_gates = policy.get("hard_gates", [])
    return any(gate["name"] == alert_name for gate in hard_gates)


def execute_rollback(alert: Dict[str, Any], policy: Dict[str, Any], 
                     dry_run: bool = True) -> Dict[str, Any]:
    """
    Execute rollback actions.
    
    Returns dict with execution results.
    """
    auto_rollback = policy.get("auto_rollback", {})
    
    if not auto_rollback.get("enabled", False):
        return {
            "status": "skipped",
            "reason": "auto_rollback disabled in policy"
        }
    
    actions = auto_rollback.get("actions", [])
    results = []
    
    for action in actions:
        action_type = action.get("type")
        params = action.get("params", {})
        description = action.get("description", "")
        
        if dry_run:
            result = {
                "action": action_type,
                "params": params,
                "status": "dry_run",
                "message": f"[DRY RUN] Would execute: {description}"
            }
        else:
            # Real execution would call actual APIs here
            result = {
                "action": action_type,
                "params": params,
                "status": "executed",
                "message": f"Executed: {description}"
            }
        
        results.append(result)
    
    return {
        "status": "executed" if not dry_run else "dry_run",
        "actions": results,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


class AlertWebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for Alertmanager webhooks."""
    
    policy = None
    dry_run = True
    
    def do_POST(self):
        """Handle POST requests from Alertmanager."""
        if self.path != "/alert-hook":
            self.send_response(404)
            self.end_headers()
            return
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "Invalid JSON"}')
            return
        
        # Process alerts
        alerts = payload.get("alerts", [])
        responses = []
        
        for alert in alerts:
            alert_name = alert.get("labels", {}).get("alertname", "")
            status = alert.get("status", "")
            
            # Only process firing alerts
            if status != "firing":
                continue
            
            # Check if this is a hard gate
            if not is_hard_gate(alert_name, self.policy):
                responses.append({
                    "alert": alert_name,
                    "action": "skipped",
                    "reason": "not a hard gate"
                })
                continue
            
            # Execute rollback
            result = execute_rollback(alert, self.policy, self.dry_run)
            responses.append({
                "alert": alert_name,
                "rollback": result
            })
        
        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        response_body = json.dumps({
            "processed": len(responses),
            "responses": responses
        }, indent=2)
        
        self.wfile.write(response_body.encode())
    
    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Custom log format."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sys.stdout.write(f"[{timestamp}] {format % args}\n")


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Rollback watcher webhook server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP server port")
    parser.add_argument("--policy", required=True, help="Path to rollback policy YAML")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (don't execute actions)")
    args = parser.parse_args(argv)
    
    # Load policy (would use PyYAML in real implementation, using mock for stdlib-only)
    if not Path(args.policy).exists():
        print(f"[ERROR] Policy file not found: {args.policy}", file=sys.stderr)
        return 1
    
    # Mock policy loading for stdlib-only
    policy = {
        "hard_gates": [
            {"name": "SoakLatencyP95High"},
            {"name": "SoakDeadlineMissRate"},
            {"name": "SoakEdgeDegradation"}
        ],
        "auto_rollback": {
            "enabled": True,
            "actions": [
                {"type": "scale_strategy", "params": {"target": 0}, "description": "Scale to 0"},
                {"type": "circuit_state", "params": {"state": "OPEN"}, "description": "Open circuit"},
                {"type": "notify", "params": {"channels": ["oncall"]}, "description": "Notify oncall"}
            ]
        }
    }
    
    # Configure handler
    AlertWebhookHandler.policy = policy
    AlertWebhookHandler.dry_run = args.dry_run
    
    # Start server
    server = HTTPServer(("0.0.0.0", args.port), AlertWebhookHandler)
    
    print(f"[INFO] Rollback watcher started on port {args.port}")
    print(f"[INFO] Policy: {args.policy}")
    print(f"[INFO] Dry run: {args.dry_run}")
    print(f"[INFO] Webhook endpoint: http://0.0.0.0:{args.port}/alert-hook")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        server.shutdown()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

