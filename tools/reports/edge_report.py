#!/usr/bin/env python3
"""
Edge Report Generator - Create extended EDGE_REPORT.json with detailed metrics

Generates comprehensive edge performance report from various artifacts.

Usage:
    python -m tools.reports.edge_report \
        --out-json artifacts/reports/EDGE_REPORT.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Import edge_metrics module
try:
    from tools.reports.edge_metrics import load_edge_inputs, compute_edge_metrics
except ImportError:
    # Fallback for direct script execution
    import sys
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from tools.reports.edge_metrics import load_edge_inputs, compute_edge_metrics


def generate_edge_report(
    edge_report_path: Optional[str] = None,
    audit_path: Optional[str] = None,
    metrics_path: Optional[str] = None,
    output_path: Optional[str] = None
) -> dict:
    """
    Generate extended EDGE_REPORT.json.
    
    Args:
        edge_report_path: Path to existing EDGE_REPORT.json (optional)
        audit_path: Path to audit.jsonl (optional)
        metrics_path: Path to strategy metrics (optional)
        output_path: Path to write output JSON (optional, default: stdout)
        
    Returns:
        Generated metrics dict
    """
    # Load inputs from artifacts
    print("[INFO] Loading edge inputs...", file=sys.stderr)
    inputs = load_edge_inputs(
        edge_report_path=edge_report_path,
        audit_path=audit_path,
        metrics_path=metrics_path
    )
    
    # Compute extended metrics
    print("[INFO] Computing edge metrics...", file=sys.stderr)
    metrics = compute_edge_metrics(inputs)
    
    # Format JSON (deterministic, compact)
    json_output = json.dumps(metrics, sort_keys=True, separators=(',', ':'))
    
    # Write to output
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_output + '\n')
        
        print(f"[INFO] EDGE_REPORT written to {output_file}", file=sys.stderr)
    else:
        print(json_output)
    
    # Print marker for CI/CD
    print("\n| edge_report | OK | FIELDS=extended |", file=sys.stderr)
    
    return metrics


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate extended EDGE_REPORT.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from default artifacts
  python -m tools.reports.edge_report --out-json artifacts/reports/EDGE_REPORT.json
  
  # Generate with custom inputs
  python -m tools.reports.edge_report \
      --inputs artifacts/EDGE_REPORT.json \
      --audit artifacts/audit.jsonl \
      --out-json artifacts/reports/EDGE_REPORT.json
        """
    )
    
    parser.add_argument(
        "--inputs",
        type=str,
        help="Path to existing EDGE_REPORT.json (default: artifacts/EDGE_REPORT.json)"
    )
    
    parser.add_argument(
        "--audit",
        type=str,
        help="Path to audit.jsonl (optional)"
    )
    
    parser.add_argument(
        "--metrics",
        type=str,
        help="Path to strategy metrics JSON (optional)"
    )
    
    parser.add_argument(
        "--out-json",
        type=str,
        default="artifacts/reports/EDGE_REPORT.json",
        help="Output path for EDGE_REPORT.json (default: artifacts/reports/EDGE_REPORT.json)"
    )
    
    args = parser.parse_args(argv)
    
    try:
        generate_edge_report(
            edge_report_path=args.inputs,
            audit_path=args.audit,
            metrics_path=args.metrics,
            output_path=args.out_json
        )
        return 0
    
    except Exception as e:
        print(f"[ERROR] Failed to generate EDGE_REPORT: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

