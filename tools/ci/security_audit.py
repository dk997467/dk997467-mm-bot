#!/usr/bin/env python3
"""
Local security audit script for Python and Rust dependencies.

Runs pip-audit and cargo audit locally before committing.

Usage:
    python tools/ci/security_audit.py            # Run both audits
    python tools/ci/security_audit.py --python   # Python only
    python tools/ci/security_audit.py --rust     # Rust only
    python tools/ci/security_audit.py --fix      # Auto-fix (upgrade packages)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str) -> None:
    """Print section header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}\n")


def run_python_audit(fix: bool = False) -> Tuple[bool, Dict]:
    """
    Run pip-audit on Python dependencies.
    
    Args:
        fix: If True, attempt to auto-fix vulnerabilities
    
    Returns:
        (success, results_dict)
    """
    print_header("Python Dependencies Security Audit")
    
    # Check if pip-audit is installed
    try:
        subprocess.run(
            ["pip-audit", "--version"],
            check=True,
            capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{Colors.RED}[X] pip-audit not installed{Colors.END}")
        print(f"Install with: {Colors.CYAN}pip install pip-audit{Colors.END}")
        return False, {}
    
    root_dir = Path(__file__).resolve().parents[2]
    requirements_file = root_dir / "requirements.txt"
    
    if not requirements_file.exists():
        print(f"{Colors.RED}[X] requirements.txt not found{Colors.END}")
        return False, {}
    
    # Run pip-audit
    cmd = [
        "pip-audit",
        "--requirement", str(requirements_file),
        "--format", "json",
        "--vulnerability-service", "osv"
    ]
    
    if fix:
        cmd.append("--fix")
        print(f"{Colors.YELLOW}[*] Running pip-audit with --fix (will upgrade packages)...{Colors.END}")
    else:
        print(f"{Colors.BLUE}[*] Running pip-audit...{Colors.END}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        
        # Parse JSON output
        try:
            audit_data = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            audit_data = {}
        
        # Count vulnerabilities by severity
        vulnerabilities = audit_data.get("vulnerabilities", [])
        
        if not vulnerabilities:
            print(f"{Colors.GREEN}[OK] No vulnerabilities found!{Colors.END}")
            return True, {"vulnerabilities": 0, "by_severity": {}}
        
        # Analyze severity (pip-audit doesn't directly provide severity, check CVE aliases)
        severity_count = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
        
        print(f"\n{Colors.RED}[X] Found {len(vulnerabilities)} vulnerabilities:{Colors.END}\n")
        
        for vuln in vulnerabilities:
            package = vuln.get("name", "unknown")
            version = vuln.get("version", "unknown")
            vuln_id = vuln.get("id", "unknown")
            fix_versions = vuln.get("fix_versions", [])
            
            # Try to infer severity from aliases/description
            aliases = vuln.get("aliases", [])
            description = vuln.get("description", "")
            
            severity = "UNKNOWN"
            for alias in aliases:
                if "CRITICAL" in alias.upper():
                    severity = "CRITICAL"
                    break
                elif "HIGH" in alias.upper():
                    severity = "HIGH"
                    break
                elif "MEDIUM" in alias.upper() or "MODERATE" in alias.upper():
                    severity = "MEDIUM"
                    break
                elif "LOW" in alias.upper():
                    severity = "LOW"
                    break
            
            severity_count[severity] += 1
            
            # Color based on severity
            severity_color = {
                "CRITICAL": Colors.RED,
                "HIGH": Colors.RED,
                "MEDIUM": Colors.YELLOW,
                "LOW": Colors.GREEN,
                "UNKNOWN": Colors.BLUE
            }[severity]
            
            print(f"  {severity_color}[{severity}]{Colors.END} {Colors.BOLD}{package}{Colors.END} {version}")
            print(f"    ID: {vuln_id}")
            if fix_versions:
                print(f"    Fix: Upgrade to {', '.join(fix_versions)}")
            print()
        
        # Print summary
        print(f"{Colors.BOLD}Summary by severity:{Colors.END}")
        for sev, count in severity_count.items():
            if count > 0:
                color = {
                    "CRITICAL": Colors.RED,
                    "HIGH": Colors.RED,
                    "MEDIUM": Colors.YELLOW,
                    "LOW": Colors.GREEN,
                    "UNKNOWN": Colors.BLUE
                }[sev]
                print(f"  {color}{sev}: {count}{Colors.END}")
        
        # Fail if CRITICAL or HIGH
        has_critical_high = severity_count["CRITICAL"] + severity_count["HIGH"] > 0
        
        return not has_critical_high, {
            "vulnerabilities": len(vulnerabilities),
            "by_severity": severity_count
        }
    
    except Exception as e:
        print(f"{Colors.RED}[X] Error running pip-audit: {e}{Colors.END}")
        return False, {}


def run_rust_audit() -> Tuple[bool, Dict]:
    """
    Run cargo audit on Rust dependencies.
    
    Returns:
        (success, results_dict)
    """
    print_header("Rust Dependencies Security Audit")
    
    # Check if cargo-audit is installed
    try:
        subprocess.run(
            ["cargo", "audit", "--version"],
            check=True,
            capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{Colors.RED}[X] cargo-audit not installed{Colors.END}")
        print(f"Install with: {Colors.CYAN}cargo install cargo-audit{Colors.END}")
        return False, {}
    
    root_dir = Path(__file__).resolve().parents[2]
    rust_dir = root_dir / "rust"
    
    if not rust_dir.exists():
        print(f"{Colors.YELLOW}[!] rust/ directory not found, skipping Rust audit{Colors.END}")
        return True, {"vulnerabilities": 0}
    
    print(f"{Colors.BLUE}[*] Running cargo audit...{Colors.END}")
    
    try:
        # Run cargo audit with JSON output
        result = subprocess.run(
            ["cargo", "audit", "--json"],
            cwd=rust_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        # Parse JSON output
        try:
            audit_data = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            audit_data = {}
        
        vuln_count = audit_data.get("vulnerabilities", {}).get("count", 0)
        warnings = audit_data.get("warnings", [])
        
        if vuln_count == 0:
            print(f"{Colors.GREEN}[OK] No Rust vulnerabilities found!{Colors.END}")
            if warnings:
                print(f"{Colors.YELLOW}[!] {len(warnings)} warnings (non-critical){Colors.END}")
            return True, {"vulnerabilities": 0, "warnings": len(warnings)}
        
        # Show vulnerabilities
        print(f"\n{Colors.RED}[X] Found {vuln_count} Rust vulnerabilities:{Colors.END}\n")
        
        vulnerabilities = audit_data.get("vulnerabilities", {}).get("list", [])
        for vuln in vulnerabilities:
            advisory = vuln.get("advisory", {})
            package = advisory.get("package", "unknown")
            vuln_id = advisory.get("id", "unknown")
            title = advisory.get("title", "")
            url = advisory.get("url", "")
            
            print(f"  {Colors.RED}[VULNERABILITY]{Colors.END} {Colors.BOLD}{package}{Colors.END}")
            print(f"    ID: {vuln_id}")
            print(f"    Title: {title}")
            if url:
                print(f"    URL: {url}")
            print()
        
        return False, {
            "vulnerabilities": vuln_count,
            "warnings": len(warnings)
        }
    
    except Exception as e:
        print(f"{Colors.RED}[X] Error running cargo audit: {e}{Colors.END}")
        return False, {}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Security audit for Python and Rust dependencies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--python',
        action='store_true',
        help='Run Python audit only'
    )
    parser.add_argument(
        '--rust',
        action='store_true',
        help='Run Rust audit only'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Auto-fix Python vulnerabilities (upgrade packages)'
    )
    
    args = parser.parse_args()
    
    # If no specific audit selected, run both
    run_python = args.python or not args.rust
    run_rust = args.rust or not args.python
    
    results = []
    
    if run_python:
        python_ok, python_results = run_python_audit(fix=args.fix)
        results.append(("Python", python_ok, python_results))
    
    if run_rust:
        rust_ok, rust_results = run_rust_audit()
        results.append(("Rust", rust_ok, rust_results))
    
    # Print final summary
    print_header("Security Audit Summary")
    
    all_ok = True
    for name, ok, data in results:
        status = f"{Colors.GREEN}[PASS]{Colors.END}" if ok else f"{Colors.RED}[FAIL]{Colors.END}"
        print(f"{name}: {status}")
        
        if not ok:
            all_ok = False
            vuln_count = data.get("vulnerabilities", 0)
            print(f"  Found {vuln_count} vulnerabilities")
    
    print()
    
    if all_ok:
        print(f"{Colors.GREEN}{Colors.BOLD}[OK] All security audits passed!{Colors.END}")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}[FAIL] Security audit failed.{Colors.END}")
        print(f"\nRecommendations:")
        print(f"  1. Review vulnerabilities above")
        print(f"  2. Upgrade affected packages")
        print(f"  3. Run with --fix to auto-upgrade (Python only)")
        print(f"  4. Check for alternative packages if no fix available")
        return 1


if __name__ == "__main__":
    sys.exit(main())

