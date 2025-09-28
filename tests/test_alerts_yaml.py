"""
Test alert rules YAML file for syntax and structure.
"""

import yaml
import pytest
from pathlib import Path


class TestAlertRulesYAML:
    """Test alert rules YAML file."""
    
    def test_yaml_syntax_valid(self):
        """Test that alert rules YAML file has valid syntax."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        assert alerts_file.exists(), "Alert rules file should exist"
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse YAML to check syntax
        try:
            rules = yaml.safe_load(content)
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML syntax: {e}")
        
        assert rules is not None, "YAML should not be empty"
    
    def test_yaml_structure_valid(self):
        """Test that alert rules YAML has correct structure."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        # Check top-level structure
        assert "groups" in rules, "Should have 'groups' key"
        assert isinstance(rules["groups"], list), "Groups should be a list"
        assert len(rules["groups"]) > 0, "Should have at least one group"
        
        # Check group structure
        group = rules["groups"][0]
        assert "name" in group, "Group should have a name"
        assert "rules" in group, "Group should have rules"
        assert isinstance(group["rules"], list), "Rules should be a list"
        assert len(group["rules"]) > 0, "Should have at least one rule"
        
        # Check rule structure
        for rule in group["rules"]:
            required_keys = ["alert", "expr", "for", "labels", "annotations"]
            for key in required_keys:
                assert key in rule, f"Rule should have '{key}' key"
            
            # Check severity levels
            if "labels" in rule and "severity" in rule["labels"]:
                severity = rule["labels"]["severity"]
                valid_severities = ["critical", "warning", "info"]
                assert severity in valid_severities, f"Invalid severity: {severity}"
    
    def test_alert_names_unique(self):
        """Test that all alert names are unique."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        alert_names = []
        for group in rules["groups"]:
            for rule in group["rules"]:
                alert_names.append(rule["alert"])
        
        # Check for duplicates
        duplicates = [name for name in set(alert_names) if alert_names.count(name) > 1]
        assert len(duplicates) == 0, f"Duplicate alert names found: {duplicates}"
    
    def test_required_alerts_present(self):
        """Test that all required alerts are present."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        alert_names = []
        for group in rules["groups"]:
            for rule in group["rules"]:
                alert_names.append(rule["alert"])
        
        # Required alerts based on user requirements
        required_alerts = [
            "RejectRateHigh",
            "CancelRateNearLimit", 
            "HighLatencyREST",
            "RiskPaused",
            "CircuitBreakerOpen",
            "AmendFailureRateHigh",
            "QueuePositionDegraded",
            "HighBackoffTime",
            "DrawdownDay",
            "OrderManagerUnhealthy"
        ]
        
        for alert in required_alerts:
            assert alert in alert_names, f"Required alert '{alert}' not found"
    
    def test_alert_expressions_valid(self):
        """Test that alert expressions are syntactically valid PromQL."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        # Basic PromQL syntax checks
        for group in rules["groups"]:
            for rule in group["rules"]:
                expr = rule["expr"]
                
                # Should not be empty
                assert expr.strip(), "Expression should not be empty"
                
                # Should contain basic PromQL operators
                assert any(op in expr for op in [">", "<", "==", "!=", ">=", "<="]), \
                    f"Expression should contain comparison operator: {expr}"
                
                # Should not contain obvious syntax errors
                assert not expr.endswith(">"), f"Expression should not end with '>': {expr}"
                assert not expr.endswith("<"), f"Expression should not end with '<': {expr}"
                assert not expr.endswith("="), f"Expression should not end with '=': {expr}"
    
    def test_alert_durations_valid(self):
        """Test that alert durations are valid time formats."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        valid_suffixes = ["s", "m", "h", "d", "w", "y"]
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                duration = rule["for"]
                
                # Should be a string
                assert isinstance(duration, str), f"Duration should be string: {duration}"
                
                # Should end with valid time suffix
                assert any(duration.endswith(suffix) for suffix in valid_suffixes), \
                    f"Invalid duration format: {duration}"
                
                # Should have numeric prefix
                numeric_part = duration.rstrip(''.join(valid_suffixes))
                try:
                    float(numeric_part)
                except ValueError:
                    pytest.fail(f"Duration should have numeric prefix: {duration}")
    
    def test_alert_labels_consistent(self):
        """Test that alert labels are consistent across rules."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        # Check that all rules have consistent label structure
        for group in rules["groups"]:
            for rule in group["rules"]:
                labels = rule["labels"]
                
                # Should have severity
                assert "severity" in labels, f"Rule '{rule['alert']}' should have severity label"
                
                # Should have service
                assert "service" in labels, f"Rule '{rule['alert']}' should have service label"
                
                # Service should be mm-bot
                assert labels["service"] == "mm-bot", f"Service should be 'mm-bot', got '{labels['service']}'"
    
    def test_alert_annotations_complete(self):
        """Test that alert annotations are complete."""
        alerts_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(alerts_file, 'r', encoding='utf-8') as f:
            rules = yaml.safe_load(f)
        
        required_annotations = ["summary", "description"]
        
        for group in rules["groups"]:
            for rule in group["rules"]:
                annotations = rule["annotations"]
                
                for annotation in required_annotations:
                    assert annotation in annotations, \
                        f"Rule '{rule['alert']}' should have '{annotation}' annotation"
                    
                    # Should not be empty
                    assert annotations[annotation].strip(), \
                        f"Annotation '{annotation}' should not be empty in rule '{rule['alert']}'"

    def test_no_env_substitution_in_rules(self):
        """Test that no ${ENV} shell substitution appears in rules"""
        rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
        
        with open(rules_file, 'r') as f:
            content = f.read()
        
        # Check for shell-style environment variable substitution
        assert "${ENV" not in content, "Rules should not contain ${ENV} shell substitution"
        assert "${ENV:-prod}" not in content, "Rules should not contain ${ENV:-prod} shell substitution"
        
        # Check that env labels are not present (they should come from external_labels)
        assert "env:" not in content, "Rules should not contain env labels (use Prometheus external_labels)"

"""Test that alert rules don't contain shell-style environment variables."""

import re
from pathlib import Path


def test_no_shell_env_vars_in_rules():
    """Ensure mm_bot.rules.yml doesn't contain ${ENV:-prod} patterns."""
    rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
    
    assert rules_file.exists(), f"Rules file not found: {rules_file}"
    
    content = rules_file.read_text()
    
    # Check for shell-style environment variable patterns
    shell_env_patterns = [
        r'\$\{ENV[^}]*\}',  # ${ENV:-prod}, ${ENV}, etc.
        r'\$ENV',            # $ENV
        r'\$\{[^}]*ENV[^}]*\}',  # Any pattern with ENV in braces
    ]
    
    for pattern in shell_env_patterns:
        matches = re.findall(pattern, content)
        assert not matches, (
            f"Found shell environment variables in {rules_file}: {matches}\n"
            "Use Prometheus external_labels instead of shell substitution."
        )


def test_rules_have_stable_service_label():
    """Ensure all alert rules have stable service: 'mm-bot' label."""
    rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
    
    assert rules_file.exists(), f"Rules file not found: {rules_file}"
    
    content = rules_file.read_text()
    
    # Check that all labels sections contain service: "mm-bot"
    # This regex looks for labels: sections and ensures they contain service: "mm-bot"
    labels_sections = re.findall(r'labels:\s*\n(?:[ ]+[^:]+:[^,\n]*\n?)*', content)
    
    for section in labels_sections:
        assert 'service: "mm-bot"' in section, (
            f"Labels section missing service: 'mm-bot':\n{section}"
        )


def test_rules_file_structure():
    """Basic structure validation of the rules file."""
    rules_file = Path("monitoring/alerts/mm_bot.rules.yml")
    
    assert rules_file.exists(), f"Rules file not found: {rules_file}"
    
    content = rules_file.read_text()
    
    # Check for required YAML structure
    assert "groups:" in content, "Missing 'groups:' section"
    assert "rules:" in content, "Missing 'rules:' section"
    assert "alert:" in content, "Missing alert definitions"
    
    # Check for at least one alert rule
    alert_count = content.count("alert:")
    assert alert_count > 0, f"Expected at least one alert rule, found {alert_count}"
