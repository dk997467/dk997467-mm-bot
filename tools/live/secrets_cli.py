"""
CLI utility for managing secrets.

Commands:
- save: Save API credentials
- fetch: Fetch API credentials (masked)
- rotate: Rotate API credentials
- list: List all stored credentials
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tools.live.secrets import APICredentials, SecretProvider, get_secret_provider


def _format_json(data: dict[str, Any]) -> str:
    """Format data as deterministic JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"


def cmd_save(args: argparse.Namespace) -> int:
    """Save API credentials."""
    provider = get_secret_provider()
    try:
        provider.save_credentials(
            env=args.env,
            exchange=args.exchange,
            api_key=args.api_key,
            api_secret=args.api_secret,
        )
        result = {
            "status": "OK",
            "action": "save",
            "env": args.env,
            "exchange": args.exchange,
        }
        sys.stdout.write(_format_json(result))
        return 0
    except Exception as e:
        result = {
            "status": "ERROR",
            "action": "save",
            "error": str(e),
        }
        sys.stdout.write(_format_json(result))
        return 1


def cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch API credentials (masked)."""
    provider = get_secret_provider()
    try:
        creds = provider.get_api_credentials(env=args.env, exchange=args.exchange)
        result = {
            "status": "OK",
            "action": "fetch",
            "credentials": creds.mask(),
        }
        sys.stdout.write(_format_json(result))
        return 0
    except Exception as e:
        result = {
            "status": "ERROR",
            "action": "fetch",
            "error": str(e),
        }
        sys.stdout.write(_format_json(result))
        return 1


def cmd_rotate(args: argparse.Namespace) -> int:
    """Rotate API credentials."""
    provider = get_secret_provider()
    try:
        provider.rotate_credentials(
            env=args.env,
            exchange=args.exchange,
            new_api_key=args.new_api_key,
            new_api_secret=args.new_api_secret,
        )
        result = {
            "status": "OK",
            "action": "rotate",
            "env": args.env,
            "exchange": args.exchange,
        }
        sys.stdout.write(_format_json(result))
        return 0
    except Exception as e:
        result = {
            "status": "ERROR",
            "action": "rotate",
            "error": str(e),
        }
        sys.stdout.write(_format_json(result))
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List all stored credentials."""
    provider = get_secret_provider()
    try:
        credentials = provider.list_credentials()
        result = {
            "status": "OK",
            "action": "list",
            "count": len(credentials),
            "credentials": [
                {
                    "env": cred.env,
                    "exchange": cred.exchange,
                    "key": cred.key,
                    "rotation_days": cred.rotation_days,
                }
                for cred in credentials
            ],
        }
        sys.stdout.write(_format_json(result))
        return 0
    except Exception as e:
        result = {
            "status": "ERROR",
            "action": "list",
            "error": str(e),
        }
        sys.stdout.write(_format_json(result))
        return 1


def cmd_whoami(args: argparse.Namespace) -> int:
    """Show current backend and environment info."""
    provider = get_secret_provider()
    try:
        backend_info = provider.get_backend_info()
        result = {
            "status": "OK",
            "action": "whoami",
            "backend": backend_info["backend"],
            "exchange_env": backend_info["exchange_env"],
            "secret_env": backend_info["secret_env"],
        }
        sys.stdout.write(_format_json(result))
        return 0
    except Exception as e:
        result = {
            "status": "ERROR",
            "action": "whoami",
            "error": str(e),
        }
        sys.stdout.write(_format_json(result))
        return 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MM Bot Secrets Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Save command
    save_parser = subparsers.add_parser("save", help="Save API credentials")
    save_parser.add_argument("--env", required=True, help="Environment (dev/shadow/soak/prod)")
    save_parser.add_argument("--exchange", required=True, help="Exchange (bybit/binance/kucoin)")
    save_parser.add_argument("--api-key", required=True, help="API key")
    save_parser.add_argument("--api-secret", required=True, help="API secret")
    save_parser.set_defaults(func=cmd_save)

    # Fetch command
    fetch_parser = subparsers.add_parser("fetch", help="Fetch API credentials (masked)")
    fetch_parser.add_argument("--env", required=True, help="Environment")
    fetch_parser.add_argument("--exchange", required=True, help="Exchange")
    fetch_parser.set_defaults(func=cmd_fetch)

    # Rotate command
    rotate_parser = subparsers.add_parser("rotate", help="Rotate API credentials")
    rotate_parser.add_argument("--env", required=True, help="Environment")
    rotate_parser.add_argument("--exchange", required=True, help="Exchange")
    rotate_parser.add_argument("--new-api-key", required=True, help="New API key")
    rotate_parser.add_argument("--new-api-secret", required=True, help="New API secret")
    rotate_parser.set_defaults(func=cmd_rotate)

    # List command
    list_parser = subparsers.add_parser("list", help="List all stored credentials")
    list_parser.set_defaults(func=cmd_list)
    
    # Whoami command
    whoami_parser = subparsers.add_parser("whoami", help="Show current backend and environment")
    whoami_parser.set_defaults(func=cmd_whoami)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

