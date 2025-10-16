#!/usr/bin/env python3
"""
Grafana Dashboard Export/Import Tool

Simple GET/POST wrapper for Grafana API to export/import dashboard JSON.

Usage:
    # Export dashboard
    python -m tools.ops.grafana_export export \\
      --url http://grafana:3000 \\
      --token <api-token> \\
      --uid mm-operability \\
      --output deploy/grafana/dashboards/mm_operability.json
    
    # Import dashboard
    python -m tools.ops.grafana_export import \\
      --url http://grafana:3000 \\
      --token <api-token> \\
      --input deploy/grafana/dashboards/mm_operability.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def grafana_request(url: str, token: str, method: str = "GET", 
                   data: bytes = None) -> Dict[str, Any]:
    """Make request to Grafana API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    req = Request(url, data=data, headers=headers, method=method)
    
    try:
        with urlopen(req) as response:
            return json.loads(response.read())
    except HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.reason}", file=sys.stderr)
        if e.code == 401:
            print("[ERROR] Invalid API token", file=sys.stderr)
        elif e.code == 404:
            print("[ERROR] Dashboard not found", file=sys.stderr)
        raise


def export_dashboard(base_url: str, token: str, uid: str, output_path: str) -> int:
    """Export dashboard by UID."""
    url = f"{base_url}/api/dashboards/uid/{uid}"
    
    print(f"[INFO] Exporting dashboard: {uid}")
    print(f"[INFO] URL: {url}")
    
    try:
        data = grafana_request(url, token)
    except Exception as e:
        print(f"[ERROR] Export failed: {e}", file=sys.stderr)
        return 1
    
    # Save to file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    
    print(f"[OK] Dashboard exported: {output_path}")
    return 0


def import_dashboard(base_url: str, token: str, input_path: str) -> int:
    """Import dashboard from JSON file."""
    if not Path(input_path).exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        return 1
    
    # Load dashboard JSON
    with open(input_path, 'r') as f:
        dashboard = json.load(f)
    
    # Prepare payload for Grafana API
    payload = {
        "dashboard": dashboard.get("dashboard", dashboard),
        "overwrite": True
    }
    
    url = f"{base_url}/api/dashboards/db"
    
    print(f"[INFO] Importing dashboard from: {input_path}")
    print(f"[INFO] URL: {url}")
    
    try:
        data = json.dumps(payload).encode()
        result = grafana_request(url, token, method="POST", data=data)
        print(f"[OK] Dashboard imported successfully")
        print(f"[INFO] Dashboard ID: {result.get('id')}")
        print(f"[INFO] Dashboard UID: {result.get('uid')}")
        return 0
    except Exception as e:
        print(f"[ERROR] Import failed: {e}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Grafana dashboard export/import tool")
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export dashboard")
    export_parser.add_argument("--url", required=True, help="Grafana base URL")
    export_parser.add_argument("--token", help="API token (or use GRAFANA_TOKEN env var)")
    export_parser.add_argument("--uid", required=True, help="Dashboard UID")
    export_parser.add_argument("--output", required=True, help="Output JSON file path")
    
    # Import command
    import_parser = subparsers.add_parser("import", help="Import dashboard")
    import_parser.add_argument("--url", required=True, help="Grafana base URL")
    import_parser.add_argument("--token", help="API token (or use GRAFANA_TOKEN env var)")
    import_parser.add_argument("--input", required=True, help="Input JSON file path")
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Get token from args or env
    token = args.token or os.getenv("GRAFANA_TOKEN")
    if not token:
        print("[ERROR] API token required (--token or GRAFANA_TOKEN env var)", file=sys.stderr)
        return 1
    
    # Execute command
    if args.command == "export":
        return export_dashboard(args.url, token, args.uid, args.output)
    elif args.command == "import":
        return import_dashboard(args.url, token, args.input)
    
    return 1


if __name__ == "__main__":
    sys.exit(main())

