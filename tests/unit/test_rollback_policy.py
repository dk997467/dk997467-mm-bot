"""
Unit tests for rollback policy logic.
"""

import sys
sys.path.insert(0, ".")

from orchestrator.rollback_watcher import is_hard_gate, execute_rollback


def test_is_hard_gate():
    """Test hard gate detection."""
    policy = {
        "hard_gates": [
            {"name": "SoakLatencyP95High"},
            {"name": "SoakDeadlineMissRate"}
        ],
        "soft_gates": [
            {"name": "SoakMakerTakerImbalance"}
        ]
    }
    
    # Hard gates
    assert is_hard_gate("SoakLatencyP95High", policy) is True
    assert is_hard_gate("SoakDeadlineMissRate", policy) is True
    
    # Soft gates (not in hard_gates)
    assert is_hard_gate("SoakMakerTakerImbalance", policy) is False
    
    # Unknown alert
    assert is_hard_gate("UnknownAlert", policy) is False
    
    print("✓ Hard gate detection tests passed")


def test_execute_rollback_dry_run():
    """Test rollback execution in dry-run mode."""
    alert = {
        "labels": {"alertname": "SoakLatencyP95High"},
        "status": "firing"
    }
    
    policy = {
        "auto_rollback": {
            "enabled": True,
            "actions": [
                {"type": "scale_strategy", "params": {"target": 0}, "description": "Scale to 0"},
                {"type": "circuit_state", "params": {"state": "OPEN"}, "description": "Open circuit"}
            ]
        }
    }
    
    result = execute_rollback(alert, policy, dry_run=True)
    
    assert result["status"] == "dry_run"
    assert len(result["actions"]) == 2
    assert result["actions"][0]["action"] == "scale_strategy"
    assert result["actions"][0]["status"] == "dry_run"
    assert result["actions"][1]["action"] == "circuit_state"
    
    print("✓ Rollback execution (dry-run) tests passed")


def test_execute_rollback_disabled():
    """Test rollback when disabled in policy."""
    alert = {
        "labels": {"alertname": "SoakLatencyP95High"},
        "status": "firing"
    }
    
    policy = {
        "auto_rollback": {
            "enabled": False
        }
    }
    
    result = execute_rollback(alert, policy, dry_run=False)
    
    assert result["status"] == "skipped"
    assert "disabled" in result["reason"]
    
    print("✓ Rollback disabled tests passed")


if __name__ == "__main__":
    test_is_hard_gate()
    test_execute_rollback_dry_run()
    test_execute_rollback_disabled()
    print("\n✓ All rollback policy tests passed")

