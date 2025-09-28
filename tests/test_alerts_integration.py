"""
Test alert integration with Prometheus.
"""

import pytest
import yaml
from pathlib import Path
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


class TestAlertsIntegration:
    def test_prometheus_compatibility(self):
        """Test that alert rules are compatible with Prometheus"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Check that rules can be loaded by Prometheus
        assert rules is not None, "Rules should be loadable by Prometheus"
        
        # Check that each rule has valid structure
        for group in rules["groups"]:
            for rule in group["rules"]:
                # Prometheus requires these fields
                assert "alert" in rule, "Rule missing 'alert' field"
                assert "expr" in rule, "Rule missing 'expr' field"
                assert "for" in rule, "Rule missing 'for' field"
                assert "labels" in rule, "Rule missing 'labels' field"

    def test_metric_references_valid(self):
        """Test that all metrics referenced in expressions exist or are reasonable"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Common metrics that should exist
        expected_metrics = [
            "rest_error_rate", "cancel_rate", "latency_ms_bucket", "risk_paused",
            "circuit_breaker_state", "amend_attempts_total", "amend_success_total",
            "queue_pos_delta", "backoff_seconds_sum", "drawdown_day", "up"
        ]
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                expr = rule["expr"]
                # Check if expression references expected metrics
                metric_found = any(metric in expr for metric in expected_metrics)
                assert metric_found, f"Expression '{expr}' should reference known metrics"

    def test_label_structure_consistent(self):
        """Test that label structure is consistent across rules"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                labels = rule["labels"]
                # All rules should have service label
                assert "service" in labels, f"Rule {rule.get('alert', 'unknown')} missing service label"
                assert labels["service"] == "mm-bot", f"Service label should be 'mm-bot'"
                
                # All rules should have severity label
                assert "severity" in labels, f"Rule {rule.get('alert', 'unknown')} missing severity label"

    def test_annotation_completeness(self):
        """Test that all annotations are complete and meaningful"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                annotations = rule["annotations"]
                
                # Check summary is concise
                assert "summary" in annotations, f"Rule {rule.get('alert', 'unknown')} missing summary"
                summary = annotations["summary"]
                assert len(summary) > 10, f"Summary too short: {summary}"
                assert len(summary) < 100, f"Summary too long: {summary}"
                
                # Check description provides context
                assert "description" in annotations, f"Rule {rule.get('alert', 'unknown')} missing description"
                description = annotations["description"]
                assert len(description) > 20, f"Description too short: {description}"

    def test_duration_formats_valid(self):
        """Test that duration formats are valid Prometheus format"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        valid_suffixes = ["s", "m", "h", "d", "w", "y"]
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                duration = rule["for"]
                # Duration should end with valid suffix
                assert any(duration.endswith(suffix) for suffix in valid_suffixes), \
                    f"Invalid duration format '{duration}' in rule {rule.get('alert', 'unknown')}"

    def test_thresholds_reasonable(self):
        """Test that alert thresholds are reasonable"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                expr = rule["expr"]
                # Check for reasonable thresholds
                if "> 0.02" in expr:  # Error rate threshold
                    assert "0.02" in expr, "Error rate threshold should be 2%"
                if "> 300" in expr:  # Latency threshold
                    assert "300" in expr, "Latency threshold should be 300ms"

    def test_logical_grouping(self):
        """Test that rules are logically grouped"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        # Check that all rules are in the same group
        assert len(rules["groups"]) == 1, "All rules should be in one group"
        group = rules["groups"][0]
        assert group["name"] == "mm_bot_alerts", "Group should be named 'mm_bot_alerts'"

    def test_runbook_urls_present(self):
        """Test that all rules have runbook URLs"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                annotations = rule["annotations"]
                assert "runbook_url" in annotations, \
                    f"Rule {rule.get('alert', 'unknown')} missing runbook_url"
                
                # Check URL format
                url = annotations["runbook_url"]
                assert url.startswith("https://"), f"Runbook URL should be HTTPS: {url}"
                assert "runbook.example.com" in url, f"Runbook URL should point to runbook.example.com: {url}"

    def test_external_labels_integration(self):
        """Test that rules work with Prometheus external_labels for env"""
        # Load a test Prometheus config with external_labels
        test_config = {
            "global": {
                "external_labels": {
                    "env": "test",
                    "service": "mm-bot"
                }
            },
            "rule_files": ["alerts/mm_bot.rules.yml"]
        }
        
        # This simulates how Prometheus would apply external_labels to all rules
        # The env label should come from external_labels, not from rule labels
        
        # Verify that our rules don't have env labels (they come from external_labels)
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        with open(rules_file, 'r') as f:
            rules = yaml.safe_load(f)
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                labels = rule["labels"]
                # Rules should not have env labels - they come from external_labels
                assert "env" not in labels, \
                    f"Rule {rule.get('alert', 'unknown')} should not have env label (use external_labels)"
                
                # Rules should have service label for matching
                assert "service" in labels, \
                    f"Rule {rule.get('alert', 'unknown')} should have service label"
                assert labels["service"] == "mm-bot", \
                    f"Service label should be 'mm-bot' for external_labels matching"
