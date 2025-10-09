#!/usr/bin/env python3
"""
Chaos Findings Analyzer - анализ выявленных проблем и приоритизация.

Usage:
    python tools/chaos/findings_analyzer.py --report artifacts/chaos/report.md --output artifacts/chaos/findings.json
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any


class FindingsAnalyzer:
    """
    Анализатор findings из chaos testing.
    
    Output: findings.json с:
    - Список проблем (issue_id, scenario, severity, description)
    - Приоритизация (high/medium/low)
    - Рекомендации по исправлению
    """
    
    SEVERITY_HIGH = "high"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_LOW = "low"
    
    def __init__(self, report_path: Path, output_path: Path):
        """
        Инициализация.
        
        Args:
            report_path: Path to report.md
            output_path: Output findings.json path
        """
        self.report_path = report_path
        self.output_path = output_path
        
        self.findings: List[Dict[str, Any]] = []
    
    def analyze_report(self) -> None:
        """Analyze report and extract findings."""
        if not self.report_path.exists():
            print(f"ERROR: Report not found: {self.report_path}", file=sys.stderr)
            return
        
        with open(self.report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse warnings from report
        lines = content.split("\n")
        
        for line in lines:
            if "⚠️" in line and ":" in line:
                # Extract scenario and issue
                parts = line.split("**")
                if len(parts) >= 2:
                    scenario = parts[1].replace("**", "").strip()
                    description = parts[2].strip() if len(parts) > 2 else "Unknown issue"
                    
                    severity = self._classify_severity(description)
                    
                    finding = {
                        "issue_id": f"CHAOS-{len(self.findings) + 1}",
                        "scenario": scenario,
                        "severity": severity,
                        "description": description,
                        "recommendation": self._generate_recommendation(scenario, description)
                    }
                    
                    self.findings.append(finding)
    
    def _classify_severity(self, description: str) -> str:
        """Classify finding severity."""
        if "deadline_miss" in description.lower() and "exceeds" in description.lower():
            return self.SEVERITY_HIGH
        
        if "p95" in description.lower() and "exceeds" in description.lower():
            return self.SEVERITY_HIGH
        
        if "failure" in description.lower():
            return self.SEVERITY_MEDIUM
        
        if "recovery" in description.lower():
            return self.SEVERITY_MEDIUM
        
        return self.SEVERITY_LOW
    
    def _generate_recommendation(self, scenario: str, description: str) -> str:
        """Generate recommendation for fixing the issue."""
        if "deadline_miss" in description.lower():
            return "Tune backoff parameters or increase tick deadline_ms"
        
        if "p95" in description.lower():
            return "Optimize hot path or increase async_batch.max_parallel_symbols"
        
        if "recovery" in description.lower():
            return "Review recovery logic and ensure cleanup in ≤3 ticks"
        
        if "failure" in description.lower():
            return f"Investigate {scenario} failure mode and add retry logic"
        
        return "Monitor in production and adjust thresholds"
    
    def export_findings(self) -> None:
        """Export findings to JSON."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        output = {
            "total_findings": len(self.findings),
            "by_severity": {
                "high": len([f for f in self.findings if f["severity"] == self.SEVERITY_HIGH]),
                "medium": len([f for f in self.findings if f["severity"] == self.SEVERITY_MEDIUM]),
                "low": len([f for f in self.findings if f["severity"] == self.SEVERITY_LOW])
            },
            "findings": self.findings
        }
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)
        
        print(f"Findings saved to: {self.output_path}")
        print(f"Total findings: {len(self.findings)}")
        print(f"  High: {output['by_severity']['high']}")
        print(f"  Medium: {output['by_severity']['medium']}")
        print(f"  Low: {output['by_severity']['low']}")


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Chaos Findings Analyzer")
    parser.add_argument("--report", required=True, help="Path to report.md")
    parser.add_argument("--output", default="artifacts/chaos/findings.json", help="Output findings.json path")
    
    args = parser.parse_args(argv)
    
    report_path = Path(args.report)
    output_path = Path(args.output)
    
    analyzer = FindingsAnalyzer(report_path, output_path)
    
    print("=" * 60)
    print("CHAOS FINDINGS ANALYZER")
    print("=" * 60)
    print()
    
    analyzer.analyze_report()
    analyzer.export_findings()
    
    print()
    print("✅ Findings analysis complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
