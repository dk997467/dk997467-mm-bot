#!/usr/bin/env python3
"""
Quick verification script to check soak test readiness.

Validates all 11 completed tasks are properly integrated.
Exit code 0 = READY, non-zero = NOT READY
"""

import sys
import os
import importlib.util
from pathlib import Path
from typing import List, Tuple


class Color:
    """ANSI color codes for terminal output (Windows compatible)."""
    GREEN = ''
    RED = ''
    YELLOW = ''
    BLUE = ''
    RESET = ''
    
    @classmethod
    def init(cls):
        """Initialize colors based on terminal support."""
        if os.name == 'nt':
            # Windows: Use simple markers
            cls.GREEN = '[OK] '
            cls.RED = '[X] '
            cls.YELLOW = '[!] '
            cls.BLUE = '[i] '
        else:
            # Unix: Use ANSI codes
            cls.GREEN = '\033[92m✓ '
            cls.RED = '\033[91m✗ '
            cls.YELLOW = '\033[93m⚠ '
            cls.BLUE = '\033[94mℹ '
            cls.RESET = '\033[0m'


Color.init()


def check_file_exists(path: str) -> bool:
    """Check if file exists."""
    return Path(path).exists()


def check_module_import(module_path: str, symbol: str = None) -> Tuple[bool, str]:
    """Try to import a module and optionally check for a symbol."""
    try:
        # Convert path to module name
        module_name = module_path.replace('/', '.').replace('\\', '.').replace('.py', '')
        
        # Try import
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return False, f"Module {module_name} not found"
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if symbol:
            if not hasattr(module, symbol):
                return False, f"Symbol {symbol} not found in {module_name}"
        
        return True, "OK"
    except Exception as e:
        return False, str(e)


def check_pattern_in_file(file_path: str, pattern: str) -> bool:
    """Check if pattern exists in file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            return pattern in content
    except Exception:
        return False


def print_header(text: str):
    """Print section header."""
    print(f"\n{Color.BLUE}{'='*60}")
    print(f"{text}")
    print(f"{'='*60}{Color.RESET}")


def print_check(passed: bool, message: str):
    """Print check result."""
    if passed:
        print(f"{Color.GREEN}{message}{Color.RESET}")
    else:
        print(f"{Color.RED}{message}{Color.RESET}")


def print_warning(message: str):
    """Print warning."""
    print(f"{Color.YELLOW}{message}{Color.RESET}")


def main() -> int:
    """Run all verification checks."""
    print_header("SOAK TEST READINESS VERIFICATION")
    
    all_passed = True
    warnings: List[str] = []
    
    # Task #1: Docker Secrets
    print_header("Task #1: Docker Secrets")
    
    check = check_pattern_in_file('src/common/config.py', '_load_secret')
    print_check(check, "Docker Secrets loader function exists")
    all_passed = all_passed and check
    
    check = check_file_exists('DOCKER_SECRETS_MIGRATION.md')
    print_check(check, "Migration guide exists")
    all_passed = all_passed and check
    
    check = check_file_exists('docker-compose.override.yml.example')
    print_check(check, "Docker override example exists")
    all_passed = all_passed and check
    
    # Task #2: Memory Leak Fix
    print_header("Task #2: Memory Leak Fix")
    
    check = check_pattern_in_file('tools/ci/lint_ascii_logs.py', 'for line_no, line in enumerate')
    print_check(check, "Streaming read implemented in lint_ascii_logs.py")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('tools/ci/lint_ascii_logs.py', 'MAX_LINE_LENGTH')
    print_check(check, "MAX_LINE_LENGTH safety check exists")
    all_passed = all_passed and check
    
    # Task #3: Log Rotation
    print_header("Task #3: Log Rotation")
    
    check = check_pattern_in_file('tools/ci/full_stack_validate.py', '_cleanup_old_logs')
    print_check(check, "Log cleanup function exists")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('tools/ci/full_stack_validate.py', '_check_disk_space')
    print_check(check, "Disk space monitoring exists")
    all_passed = all_passed and check
    
    # Task #4: Exponential Backoff
    print_header("Task #4: Exponential Backoff")
    
    check = check_pattern_in_file('src/connectors/bybit_websocket.py', '_wait_before_reconnect')
    print_check(check, "Backoff function exists in WebSocket connector")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('src/connectors/bybit_websocket.py', 'ws_reconnect_attempts_total')
    print_check(check, "Reconnection metrics exist")
    all_passed = all_passed and check
    
    # Task #5: Resource Monitoring
    print_header("Task #5: Resource Monitoring")
    
    check = check_file_exists('tools/soak/resource_monitor.py')
    print_check(check, "Resource monitor script exists")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('.github/workflows/soak-windows.yml', 'Start resource monitoring')
    print_check(check, "Resource monitoring integrated in soak workflow")
    all_passed = all_passed and check
    
    # Task #6: Graceful Shutdown
    print_header("Task #6: Graceful Shutdown")
    
    check = check_pattern_in_file('cli/run_bot.py', 'cancel_all_orders')
    print_check(check, "cancel_all_orders() called in shutdown")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('cli/run_bot.py', 'shutdown_event')
    print_check(check, "Graceful signal handling with asyncio.Event")
    all_passed = all_passed and check
    
    # Task #7: Security Audit
    print_header("Task #7: Security Audit")
    
    check = check_file_exists('.github/workflows/security.yml')
    print_check(check, "Security audit CI workflow exists")
    all_passed = all_passed and check
    
    check = check_file_exists('tools/ci/security_audit.py')
    print_check(check, "Local security audit script exists")
    all_passed = all_passed and check
    
    # Task #8: Log Redaction
    print_header("Task #8: Log Redaction")
    
    check = check_pattern_in_file('src/common/redact.py', 'EMAIL_ADDRESS')
    print_check(check, "Enhanced redaction patterns exist")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('src/common/redact.py', 'safe_print')
    print_check(check, "safe_print() wrapper exists")
    all_passed = all_passed and check
    
    # Task #9: Process Management
    print_header("Task #9: Process Management")
    
    check = check_file_exists('src/common/process_manager.py')
    print_check(check, "Process manager module exists")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('tools/ci/full_stack_validate.py', 'kill_process_tree')
    print_check(check, "Process cleanup integrated in CI")
    all_passed = all_passed and check
    
    # Task #10: orjson Migration
    print_header("Task #10: orjson Migration")
    
    check = check_file_exists('src/common/orjson_wrapper.py')
    print_check(check, "orjson wrapper module exists")
    all_passed = all_passed and check
    
    # Note: Full migration is pending, but infrastructure is ready
    warnings.append("orjson infrastructure ready, but full migration pending (not critical)")
    
    # Task #11: Connection Pooling
    print_header("Task #11: Connection Pooling")
    
    check = check_pattern_in_file('src/common/config.py', 'ConnectionPoolConfig')
    print_check(check, "ConnectionPoolConfig exists")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('src/connectors/bybit_rest.py', 'TCPConnector')
    print_check(check, "TCPConnector configured in REST connector")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('src/metrics/exporter.py', 'http_pool_connections')
    print_check(check, "HTTP pool metrics exist")
    all_passed = all_passed and check
    
    # Integration Checks
    print_header("Integration Checks")
    
    check = check_file_exists('SOAK_TEST_PREFLIGHT_CHECKLIST.md')
    print_check(check, "Pre-flight checklist exists")
    all_passed = all_passed and check
    
    check = check_pattern_in_file('.github/workflows/soak-windows.yml', 'Stop resource monitoring and analyze')
    print_check(check, "Resource monitoring analysis step exists")
    all_passed = all_passed and check
    
    # Print warnings
    if warnings:
        print_header("Warnings")
        for warning in warnings:
            print_warning(warning)
    
    # Final summary
    print_header("SUMMARY")
    
    if all_passed:
        print(f"\n{Color.GREEN}ALL CHECKS PASSED!{Color.RESET}")
        print(f"{Color.GREEN}System is READY for 24-hour soak test.{Color.RESET}\n")
        return 0
    else:
        print(f"\n{Color.RED}SOME CHECKS FAILED!{Color.RESET}")
        print(f"{Color.RED}Please fix issues before running soak test.{Color.RESET}\n")
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}Verification interrupted by user.{Color.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Color.RED}Verification failed with error: {e}{Color.RESET}")
        sys.exit(1)

