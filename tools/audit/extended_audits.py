#!/usr/bin/env python3
"""
Extended Audit Modules for MM-Bot System Audit v2

Блоки 5-14: Reliability, Tests, Observability, Strategy, Exchange,
Security, CI/CD, Docs, Backlog, Auto-patches
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime, timezone


class ExtendedAudits:
    """Расширенные аудиты (блоки 5-14)."""
    
    def __init__(self, project_root: Path, audit_dir: Path, issues: Dict):
        self.project_root = project_root
        self.audit_dir = audit_dir
        self.issues = issues
        self.results = {}
    
    def log(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def add_issue(self, severity: str, category: str, title: str, desc: str, fix: str = ""):
        issue = {
            "severity": severity,
            "category": category,
            "title": title,
            "description": desc,
            "fix": fix,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.issues[severity].append(issue)
    
    def audit_5_reliability(self):
        """Блок 5: Надёжность и отказоустойчивость."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 5: НАДЁЖНОСТЬ И ОТКАЗОУСТОЙЧИВОСТЬ")
        self.log("=" * 60)
        
        reliability = {
            "error_taxonomy": [],
            "circuit_breakers": [],
            "retry_policies": [],
            "chaos_scenarios": []
        }
        
        # Check for error handling patterns
        src_dir = self.project_root / "src"
        
        # Find error definitions
        common_errors = src_dir / "common/errors.py"
        if common_errors.exists():
            with open(common_errors, 'r', encoding='utf-8') as f:
                content = f.read()
                error_classes = re.findall(r'class\s+(\w+Error)', content)
                reliability["error_taxonomy"] = error_classes
                self.log(f"[OK] Найдено error типов: {len(error_classes)}")
        
        # Check for circuit breaker patterns
        for py_file in src_dir.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "circuit" in content.lower() or "breaker" in content.lower():
                    reliability["circuit_breakers"].append(
                        str(py_file.relative_to(self.project_root))
                    )
                
                if "retry" in content.lower() or "backoff" in content.lower():
                    reliability["retry_policies"].append(
                        str(py_file.relative_to(self.project_root))
                    )
            except:
                pass
        
        # Check for chaos testing
        tests_dir = self.project_root / "tests"
        if tests_dir.exists():
            chaos_tests = list(tests_dir.rglob("*chaos*.py"))
            reliability["chaos_scenarios"] = [
                str(f.relative_to(self.project_root)) for f in chaos_tests
            ]
        
        self.log(f"[OK] Circuit breakers: {len(reliability['circuit_breakers'])}")
        self.log(f"[OK] Retry policies: {len(reliability['retry_policies'])}")
        self.log(f"[OK] Chaos tests: {len(reliability['chaos_scenarios'])}")
        
        if not reliability["circuit_breakers"]:
            self.add_issue(
                "medium",
                "reliability",
                "Circuit breakers отсутствуют",
                "Не найдены реализации circuit breaker pattern",
                "Добавить CB для критических внешних зависимостей (exchange API)"
            )
        
        self.results["reliability"] = reliability
        return reliability
    
    def audit_6_tests(self):
        """Блок 6: Тесты и стабильность."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 6: ТЕСТЫ И СТАБИЛЬНОСТЬ")
        self.log("=" * 60)
        
        tests = {
            "unit_tests": [],
            "integration_tests": [],
            "e2e_tests": [],
            "property_tests": [],
            "chaos_tests": [],
            "golden_tests": [],
            "coverage": "N/A",
            "flaky_tests": []
        }
        
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            self.log("[WARN] tests/ директория не найдена")
            return tests
        
        # Categorize tests
        for test_file in tests_dir.rglob("test_*.py"):
            rel_path = str(test_file.relative_to(self.project_root))
            
            if "unit" in rel_path:
                tests["unit_tests"].append(rel_path)
            elif "integration" in rel_path:
                tests["integration_tests"].append(rel_path)
            elif "e2e" in rel_path:
                tests["e2e_tests"].append(rel_path)
            elif "property" in rel_path:
                tests["property_tests"].append(rel_path)
            elif "chaos" in rel_path:
                tests["chaos_tests"].append(rel_path)
            else:
                # Default to unit
                tests["unit_tests"].append(rel_path)
        
        # Check for golden tests
        golden_dir = tests_dir / "golden"
        if golden_dir.exists():
            golden_files = list(golden_dir.glob("*.json")) + list(golden_dir.glob("*.md"))
            tests["golden_tests"] = [str(f.relative_to(self.project_root)) for f in golden_files]
        
        self.log(f"[OK] Unit tests: {len(tests['unit_tests'])}")
        self.log(f"[OK] Integration tests: {len(tests['integration_tests'])}")
        self.log(f"[OK] E2E tests: {len(tests['e2e_tests'])}")
        self.log(f"[OK] Property tests: {len(tests['property_tests'])}")
        self.log(f"[OK] Golden tests: {len(tests['golden_tests'])}")
        
        if not tests["property_tests"]:
            self.add_issue(
                "medium",
                "tests",
                "Property tests отсутствуют",
                "Не найдены property-based тесты для инвариантов",
                "Добавить hypothesis tests для spread/guards/queue-ETA инвариантов"
            )
        
        self.results["tests"] = tests
        return tests
    
    def audit_7_observability(self):
        """Блок 7: Наблюдаемость."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 7: НАБЛЮДАЕМОСТЬ")
        self.log("=" * 60)
        
        obs = {
            "metrics_count": 0,
            "trace_events": [],
            "dashboards": [],
            "alerts": []
        }
        
        # Check for Prometheus metrics
        monitoring_dir = self.project_root / "src/monitoring"
        if monitoring_dir.exists():
            for py_file in monitoring_dir.rglob("*.py"):
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Count metrics
                    metrics = re.findall(r'(Counter|Histogram|Gauge|Summary)\(', content)
                    obs["metrics_count"] += len(metrics)
                except:
                    pass
        
        # Check for trace events
        src_dir = self.project_root / "src"
        for py_file in src_dir.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "trace_event" in content or "span" in content:
                    obs["trace_events"].append(
                        str(py_file.relative_to(self.project_root))
                    )
            except:
                pass
        
        # Check for dashboards
        grafana_files = list(self.project_root.glob("*grafana*.json"))
        obs["dashboards"] = [str(f.relative_to(self.project_root)) for f in grafana_files]
        
        self.log(f"[OK] Metrics: {obs['metrics_count']}")
        self.log(f"[OK] Trace events: {len(obs['trace_events'])} files")
        self.log(f"[OK] Dashboards: {len(obs['dashboards'])}")
        
        if not obs["dashboards"]:
            self.add_issue(
                "low",
                "observability",
                "Grafana dashboards отсутствуют",
                "Не найдены JSON файлы дашбордов",
                "Создать базовый dashboard с ключевыми метриками"
            )
        
        self.results["observability"] = obs
        return obs
    
    def audit_8_strategy(self):
        """Блок 8: Стратегия/финмодель."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 8: СТРАТЕГИЯ/ФИНМОДЕЛЬ")
        self.log("=" * 60)
        
        strategy = {
            "edge_components": [],
            "invariants": [],
            "k_factors": {}
        }
        
        # Check for edge calculation
        tools_edge = self.project_root / "tools/edge_audit.py"
        if tools_edge.exists():
            strategy["edge_components"].append("edge_audit")
            
            with open(tools_edge, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for net_bps decomposition
            if "net_bps" in content:
                strategy["invariants"].append("net_bps = gross + fees + slippage + inventory")
        
        # Check for taker cap
        config_file = self.project_root / "config.yaml"
        if config_file.exists():
            import yaml
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            if "taker_cap" in config:
                strategy["k_factors"]["taker_cap"] = config["taker_cap"]
            
            if "spread" in config:
                strategy["k_factors"]["spread"] = config.get("spread", {})
        
        self.log(f"[OK] Edge components: {len(strategy['edge_components'])}")
        self.log(f"[OK] K-factors: {len(strategy['k_factors'])}")
        
        self.results["strategy"] = strategy
        return strategy
    
    def audit_9_exchange(self):
        """Блок 9: Биржи и интеграции."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 9: БИРЖИ И ИНТЕГРАЦИИ")
        self.log("=" * 60)
        
        exchange = {
            "connectors": [],
            "rate_limits": {},
            "batch_operations": [],
            "idempotency": []
        }
        
        # Find exchange connectors
        execution_dir = self.project_root / "src/execution"
        if execution_dir.exists():
            for py_file in execution_dir.rglob("*connector*.py"):
                exchange["connectors"].append(
                    str(py_file.relative_to(self.project_root))
                )
        
        # Check for batch operations
        for py_file in self.project_root.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "batch_cancel" in content or "batch_place" in content:
                    exchange["batch_operations"].append(
                        str(py_file.relative_to(self.project_root))
                    )
            except:
                pass
        
        self.log(f"[OK] Connectors: {len(exchange['connectors'])}")
        self.log(f"[OK] Batch operations: {len(exchange['batch_operations'])} files")
        
        if not exchange["batch_operations"]:
            self.add_issue(
                "medium",
                "exchange",
                "Batch operations не найдены",
                "Отсутствует batch_cancel/batch_place реализация",
                "Реализовать batch API для снижения rate-limit нагрузки"
            )
        
        self.results["exchange"] = exchange
        return exchange
    
    def audit_10_security(self):
        """Блок 10: Безопасность/секреты/конфиги."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 10: БЕЗОПАСНОСТЬ/СЕКРЕТЫ/КОНФИГИ")
        self.log("=" * 60)
        
        security = {
            "secrets_scanner": False,
            "hardcoded_secrets": [],
            "config_validators": [],
            "rbac": False
        }
        
        # Check for secrets scanner
        scanner = self.project_root / "tools/ci/scan_secrets.py"
        if scanner.exists():
            security["secrets_scanner"] = True
            self.log("[OK] Secrets scanner найден")
        else:
            self.add_issue(
                "high",
                "security",
                "Secrets scanner отсутствует",
                "Не найден tools/ci/scan_secrets.py",
                "Создать scanner для проверки утечек секретов в коде"
            )
        
        # Scan for potential hardcoded secrets (basic check)
        src_dir = self.project_root / "src"
        secret_patterns = [
            r'api[_-]?key\s*=\s*["\'][^"\']+["\']',
            r'password\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']'
        ]
        
        for py_file in src_dir.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for pattern in secret_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        # Check if it's a test value
                        if "test" not in str(py_file).lower() and "example" not in content.lower():
                            security["hardcoded_secrets"].append({
                                "file": str(py_file.relative_to(self.project_root)),
                                "matches": len(matches)
                            })
            except:
                pass
        
        # Check for config validators
        config_py = self.project_root / "src/common/config.py"
        if config_py.exists():
            with open(config_py, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if "pydantic" in content or "BaseModel" in content:
                security["config_validators"].append("pydantic")
                self.log("[OK] Config validation через Pydantic")
        
        if security["hardcoded_secrets"]:
            self.log(f"[WARN] Потенциальные hardcoded secrets: {len(security['hardcoded_secrets'])}")
        
        self.results["security"] = security
        return security
    
    def audit_11_cicd(self):
        """Блок 11: CI/CD & Release."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 11: CI/CD & RELEASE")
        self.log("=" * 60)
        
        cicd = {
            "workflows": [],
            "perf_gates": False,
            "baseline_lock": False,
            "release_artifacts": []
        }
        
        # Check GitHub workflows
        workflows_dir = self.project_root / ".github/workflows"
        if workflows_dir.exists():
            workflow_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
            cicd["workflows"] = [f.name for f in workflow_files]
            self.log(f"[OK] CI workflows: {len(cicd['workflows'])}")
        
        # Check for perf gates
        ci_tools = self.project_root / "tools/ci"
        if ci_tools.exists():
            if (ci_tools / "stage_perf_gate.py").exists():
                cicd["perf_gates"] = True
                self.log("[OK] Performance gates найдены")
        
        # Check for baseline lock
        if (ci_tools / "baseline_lock.py").exists():
            cicd["baseline_lock"] = True
            self.log("[OK] Baseline lock найден")
        
        if not cicd["perf_gates"]:
            self.add_issue(
                "medium",
                "cicd",
                "Performance gates отсутствуют",
                "Нет автоматической проверки регрессий производительности в CI",
                "Создать stage_perf_gate.py для проверки +3% регрессий"
            )
        
        self.results["cicd"] = cicd
        return cicd
    
    def audit_12_docs(self):
        """Блок 12: Документация и runbooks."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 12: ДОКУМЕНТАЦИЯ И RUNBOOKS")
        self.log("=" * 60)
        
        docs = {
            "readme": False,
            "architecture_docs": [],
            "runbooks": [],
            "quickstarts": [],
            "adrs": []
        }
        
        # Check README
        if (self.project_root / "README.md").exists():
            docs["readme"] = True
        
        # Check docs directory
        docs_dir = self.project_root / "docs"
        if docs_dir.exists():
            for md_file in docs_dir.glob("*.md"):
                if "architecture" in md_file.name.lower() or "arch" in md_file.name.lower():
                    docs["architecture_docs"].append(md_file.name)
                elif "runbook" in md_file.name.lower():
                    docs["runbooks"].append(md_file.name)
                elif "quickstart" in md_file.name.lower():
                    docs["quickstarts"].append(md_file.name)
                elif "adr" in md_file.name.lower():
                    docs["adrs"].append(md_file.name)
        
        # Check root MD files
        for md_file in self.project_root.glob("*.md"):
            name_lower = md_file.name.lower()
            if "runbook" in name_lower:
                docs["runbooks"].append(md_file.name)
            elif "quickstart" in name_lower:
                docs["quickstarts"].append(md_file.name)
        
        self.log(f"[OK] README: {docs['readme']}")
        self.log(f"[OK] Architecture docs: {len(docs['architecture_docs'])}")
        self.log(f"[OK] Runbooks: {len(docs['runbooks'])}")
        self.log(f"[OK] Quickstarts: {len(docs['quickstarts'])}")
        
        self.results["docs"] = docs
        return docs
    
    def generate_backlog(self):
        """Блок 13: Приоритизированный бэклог."""
        self.log("\n" + "=" * 60)
        self.log("БЛОК 13: ПРИОРИТИЗИРОВАННЫЙ БЭКЛОГ")
        self.log("=" * 60)
        
        # Собираем все issues и приоритизируем
        all_issues = []
        for severity in ["critical", "high", "medium", "low"]:
            for issue in self.issues[severity]:
                priority_score = {
                    "critical": 100,
                    "high": 75,
                    "medium": 50,
                    "low": 25
                }[severity]
                
                all_issues.append({
                    "title": issue["title"],
                    "category": issue["category"],
                    "severity": severity,
                    "priority_score": priority_score,
                    "fix": issue["fix"]
                })
        
        # Sort by priority
        all_issues.sort(key=lambda x: x["priority_score"], reverse=True)
        
        self.log(f"[OK] Сформирован бэклог: {len(all_issues)} items")
        
        return all_issues[:10]  # Top 10
    
    def save_extended_reports(self):
        """Сохранение расширенных отчётов."""
        self.log("\n" + "=" * 60)
        self.log("СОХРАНЕНИЕ РАСШИРЕННЫХ ОТЧЁТОВ")
        self.log("=" * 60)
        
        # RELIABILITY_AUDIT.md
        rel_md = self.audit_dir / "RELIABILITY_AUDIT.md"
        rel = self.results.get("reliability", {})
        with open(rel_md, 'w', encoding='utf-8') as f:
            f.write("# Аудит Надёжности\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write(f"## Error Taxonomy\n\n")
            f.write(f"Найдено error типов: {len(rel.get('error_taxonomy', []))}\n\n")
            for err in rel.get('error_taxonomy', []):
                f.write(f"- {err}\n")
            f.write(f"\n## Circuit Breakers\n\n")
            f.write(f"Файлов с CB: {len(rel.get('circuit_breakers', []))}\n\n")
        self.log(f"[OK] {rel_md}")
        
        # TEST_AUDIT.md
        test_md = self.audit_dir / "TEST_AUDIT.md"
        tests = self.results.get("tests", {})
        with open(test_md, 'w', encoding='utf-8') as f:
            f.write("# Аудит Тестов\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write("## Test Coverage\n\n")
            f.write(f"- **Unit tests:** {len(tests.get('unit_tests', []))}\n")
            f.write(f"- **Integration tests:** {len(tests.get('integration_tests', []))}\n")
            f.write(f"- **E2E tests:** {len(tests.get('e2e_tests', []))}\n")
            f.write(f"- **Property tests:** {len(tests.get('property_tests', []))}\n")
            f.write(f"- **Golden tests:** {len(tests.get('golden_tests', []))}\n")
        self.log(f"[OK] {test_md}")
        
        # OBSERVABILITY_AUDIT.md
        obs_md = self.audit_dir / "OBSERVABILITY_AUDIT.md"
        obs = self.results.get("observability", {})
        with open(obs_md, 'w', encoding='utf-8') as f:
            f.write("# Аудит Наблюдаемости\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write(f"## Метрики\n\n")
            f.write(f"Всего метрик: {obs.get('metrics_count', 0)}\n\n")
            f.write(f"## Dashboards\n\n")
            for dash in obs.get('dashboards', []):
                f.write(f"- {dash}\n")
        self.log(f"[OK] {obs_md}")
        
        # IMPROVEMENTS_BACKLOG.md
        backlog_md = self.audit_dir / "IMPROVEMENTS_BACKLOG.md"
        backlog = self.generate_backlog()
        with open(backlog_md, 'w', encoding='utf-8') as f:
            f.write("# Приоритизированный Бэклог Улучшений\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write("| # | Severity | Category | Title | Fix |\n")
            f.write("|---|----------|----------|-------|-----|\n")
            for i, item in enumerate(backlog, 1):
                f.write(f"| {i} | {item['severity'].upper()} | {item['category']} | {item['title']} | {item['fix'][:50]}... |\n")
        self.log(f"[OK] {backlog_md}")
    
    def run_all(self):
        """Запуск всех расширенных аудитов."""
        self.audit_5_reliability()
        self.audit_6_tests()
        self.audit_7_observability()
        self.audit_8_strategy()
        self.audit_9_exchange()
        self.audit_10_security()
        self.audit_11_cicd()
        self.audit_12_docs()
        self.save_extended_reports()


def main():
    """Main entry point."""
    project_root = Path.cwd()
    audit_dir = project_root / "artifacts/audit_v2"
    
    # Load existing issues
    issues_file = audit_dir / "ISSUES.json"
    if issues_file.exists():
        with open(issues_file, 'r') as f:
            issues = json.load(f)
    else:
        issues = {"critical": [], "high": [], "medium": [], "low": []}
    
    auditor = ExtendedAudits(project_root, audit_dir, issues)
    auditor.run_all()
    
    # Save updated issues
    with open(issues_file, 'w') as f:
        json.dump(issues, f, indent=2)
    
    print("\n[COMPLETE] Расширенные аудиты завершены")
    return 0


if __name__ == "__main__":
    sys.exit(main())

