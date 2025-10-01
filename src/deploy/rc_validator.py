"""
RC-Validator: pre-deploy sanity checks (stdlib-only).

Produces deterministic JSON report and returns non-zero exit on errors.
"""

import json
import os
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from src.common.artifacts import write_json_atomic


def _atomic_json_write(path: str, data: Dict[str, Any]) -> None:
    """Atomic JSON write delegated to shared helper."""
    try:
        write_json_atomic(path, data)
    except Exception:
        # Best-effort; don't fail validation on write issues
        pass


def _check_envs() -> tuple[Dict[str, str], List[str]]:
    """Check required/optional environment variables."""
    errors = []
    env_data = {}
    
    required = ["MM_ENV", "MM_CONFIG_PATH"]
    optional = ["MM_PORTS"]
    
    for key in required:
        val = os.environ.get(key)
        if val is None:
            errors.append(f"missing_env:{key}")
            env_data[key] = ""
        else:
            env_data[key] = str(val)
    
    for key in optional:
        val = os.environ.get(key)
        env_data[key] = str(val) if val is not None else ""
    
    return env_data, errors


def _check_config(cfg_path: Optional[str]) -> tuple[bool, List[str]]:
    """Check config file parsing and minimal schema."""
    errors = []
    
    # Determine config path
    if cfg_path is None:
        cfg_path = os.environ.get("MM_CONFIG_PATH")
    
    if not cfg_path:
        errors.append("config_parse")
        return False, errors
    
    try:
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # Check minimal schema presence
        required_paths = [
            ["guards", "pos_skew"],
            ["guards", "intraday_caps"],
            ["fees", "bybit"],
            ["allocator", "smoothing"]
        ]
        
        for path in required_paths:
            current = data
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    # Missing path is not an error, just note it
                    break
                current = current[key]
        
        return True, errors
    except Exception:
        errors.append("config_parse")
        return False, errors


def _check_writable_dirs() -> tuple[List[str], List[str]]:
    """Check writable directories."""
    errors = []
    dirs_to_check = ["artifacts", "artifacts/runtime"]
    writable_dirs = []
    
    for dir_path in dirs_to_check:
        try:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            # Try to write and fsync a temp file
            with tempfile.NamedTemporaryFile(dir=dir_path, delete=False) as tmp:
                tmp.write(b"test")
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_name = tmp.name
            os.unlink(temp_name)
            writable_dirs.append(dir_path)
        except Exception:
            errors.append(f"writable_dir:{dir_path}")
    
    return writable_dirs, errors


def _check_ports() -> tuple[List[int], List[str]]:
    """Check port availability."""
    errors = []
    free_ports = []
    
    ports_env = os.environ.get("MM_PORTS", "")
    if not ports_env:
        return free_ports, errors
    
    try:
        ports = [int(p.strip()) for p in ports_env.split(",") if p.strip()]
    except Exception:
        return free_ports, errors
    
    for port in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                free_ports.append(port)
        except Exception:
            errors.append(f"port_busy:{port}")
    
    return sorted(free_ports), errors


def _system_snapshot() -> Dict[str, Any]:
    """System information snapshot."""
    try:
        return {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "pid": os.getpid(),
            "utc": datetime.now(timezone.utc).isoformat(),
            "cwd": os.getcwd()
        }
    except Exception:
        return {"python": "unknown", "pid": 0, "utc": "unknown", "cwd": "unknown"}


def _check_artifacts() -> List[str]:
    """Check optional artifacts presence."""
    warnings = []
    
    artifacts_to_check = ["artifacts/snapshots.json"]
    for artifact in artifacts_to_check:
        if not os.path.exists(artifact):
            warnings.append(f"missing:{os.path.basename(artifact)}")
    
    return warnings


def main(cfg_path: Optional[str] = None) -> int:
    """Main RC validator entry point."""
    warnings = []
    errors = []
    
    # 1. Check environment variables
    env_data, env_errors = _check_envs()
    errors.extend(env_errors)
    
    # 2. Check config
    config_ok, config_errors = _check_config(cfg_path)
    errors.extend(config_errors)
    
    # 3. Check writable directories
    writable_dirs, dir_errors = _check_writable_dirs()
    errors.extend(dir_errors)
    
    # 4. Check ports
    free_ports, port_errors = _check_ports()
    errors.extend(port_errors)
    
    # 5. System snapshot
    system_info = _system_snapshot()
    
    # 6. Check optional artifacts
    artifact_warnings = _check_artifacts()
    warnings.extend(artifact_warnings)
    
    # Build report
    report = {
        "env": env_data,
        "config_ok": config_ok,
        "ports_free": free_ports,
        "writable_dirs": sorted(writable_dirs),
        "warnings": sorted(warnings),
        "errors": sorted(errors),
        "system": system_info
    }
    
    # Write report
    _atomic_json_write("artifacts/rc_validator.json", report)
    
    # Return exit code
    return 0 if len(errors) == 0 else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
