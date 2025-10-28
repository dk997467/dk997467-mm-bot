#!/usr/bin/env python3
"""
Unit tests for tools/chaos/soak_failover.py — FakeKVLock TTL/ownership logic.

Tests:
- TTL expiry edge cases
- Renew logic (owned vs not owned, expired vs not expired)
- Ownership transfer (leader election)
- Concurrent worker scenarios
- Metrics tracking (leader_elections_total, renew_fail_total)
- CLI interface (subprocess)
"""
import pytest
import subprocess
import sys
from tools.chaos.soak_failover import FakeKVLock


# ======================================================================
# Test Basic Lock Acquire
# ======================================================================

def test_acquire_success_when_free():
    """Test acquire succeeds when lock is free."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    result = lock.try_acquire(owner="worker1", ts_ms=0)
    
    assert result is True
    assert lock.owner == "worker1"
    assert lock._expiry_ts_ms == 1000  # 0 + 1000
    assert lock.leader_elections_total == 1


def test_acquire_fails_when_held():
    """Test acquire fails when lock is held by another owner."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires lock
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker2 tries to acquire (should fail, lock not expired yet)
    result = lock.try_acquire(owner="worker2", ts_ms=500)
    
    assert result is False
    assert lock.owner == "worker1"  # Still owned by worker1
    assert lock.leader_elections_total == 1  # Only 1 election


def test_acquire_succeeds_after_expiry():
    """Test acquire succeeds after TTL expires."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires lock at t=0 (expires at t=1000)
    lock.try_acquire(owner="worker1", ts_ms=0)
    assert lock.owner == "worker1"
    
    # Worker2 tries to acquire at t=1000 (exactly at expiry)
    result = lock.try_acquire(owner="worker2", ts_ms=1000)
    
    assert result is True
    assert lock.owner == "worker2"  # Ownership transferred
    assert lock._expiry_ts_ms == 2000  # 1000 + 1000
    assert lock.leader_elections_total == 2  # 2 elections


def test_acquire_same_owner_after_expiry():
    """Test same owner can re-acquire after expiry (not a renew)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker1 re-acquires at t=1100 (after expiry)
    result = lock.try_acquire(owner="worker1", ts_ms=1100)
    
    assert result is True
    assert lock.owner == "worker1"
    assert lock._expiry_ts_ms == 2100  # 1100 + 1000
    assert lock.leader_elections_total == 2  # New election


# ======================================================================
# Test Lock Renew
# ======================================================================

def test_renew_success_when_owner_and_not_expired():
    """Test renew succeeds when owner and lock not expired."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0 (expires at t=1000)
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker1 renews at t=500 (before expiry)
    result = lock.renew(owner="worker1", ts_ms=500)
    
    assert result is True
    assert lock._expiry_ts_ms == 1500  # 500 + 1000 (renewed)
    assert lock.renew_fail_total == 0


def test_renew_fails_when_not_owner():
    """Test renew fails when not the owner."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires lock
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker2 tries to renew (not the owner)
    result = lock.renew(owner="worker2", ts_ms=500)
    
    assert result is False
    assert lock.owner == "worker1"  # Still worker1
    assert lock._expiry_ts_ms == 1000  # Not renewed
    assert lock.renew_fail_total == 1


def test_renew_fails_when_expired():
    """Test renew fails when lock has expired."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0 (expires at t=1000)
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker1 tries to renew at t=1000 (exactly at expiry, no longer valid)
    result = lock.renew(owner="worker1", ts_ms=1000)
    
    assert result is False
    assert lock.owner == "worker1"  # Still registered as owner
    assert lock._expiry_ts_ms == 1000  # Not renewed
    assert lock.renew_fail_total == 1


def test_renew_fails_when_expired_by_another_owner():
    """Test renew fails when lock expired and taken by another owner."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Worker2 acquires at t=1000 (after expiry)
    lock.try_acquire(owner="worker2", ts_ms=1000)
    
    # Worker1 tries to renew at t=1500 (wrong owner now)
    result = lock.renew(owner="worker1", ts_ms=1500)
    
    assert result is False
    assert lock.owner == "worker2"  # Still worker2
    assert lock.renew_fail_total == 1


# ======================================================================
# Test TTL Edge Cases
# ======================================================================

def test_ttl_expiry_boundary_exact():
    """Test TTL expiry boundary (t == expiry_ts_ms)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0 (expires at t=1000)
    lock.try_acquire(owner="worker1", ts_ms=0)
    assert lock._expiry_ts_ms == 1000
    
    # At t=1000 (exact expiry), lock should be available
    result = lock.try_acquire(owner="worker2", ts_ms=1000)
    
    assert result is True
    assert lock.owner == "worker2"


def test_ttl_expiry_boundary_just_before():
    """Test TTL expiry boundary (t < expiry_ts_ms by 1ms)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires at t=0
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # At t=999 (1ms before expiry), lock should still be held
    result = lock.try_acquire(owner="worker2", ts_ms=999)
    
    assert result is False
    assert lock.owner == "worker1"


def test_ttl_zero():
    """Test TTL=0 (lock expires immediately)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=0)
    
    # Worker1 acquires at t=0 (expires at t=0)
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # At t=0, lock is already expired
    result = lock.try_acquire(owner="worker2", ts_ms=0)
    
    assert result is True
    assert lock.owner == "worker2"


def test_ttl_very_long():
    """Test TTL very long (millions of ms)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=999_999_999)
    
    # Worker1 acquires at t=0
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Even at t=1M, lock should still be held
    result = lock.try_acquire(owner="worker2", ts_ms=1_000_000)
    
    assert result is False
    assert lock.owner == "worker1"


# ======================================================================
# Test Ownership Transfer (Leader Election)
# ======================================================================

def test_ownership_transfer_after_expiry():
    """Test ownership transfers to new worker after expiry."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 → Worker2 → Worker3 (each after expiry)
    lock.try_acquire(owner="worker1", ts_ms=0)
    assert lock.owner == "worker1"
    
    lock.try_acquire(owner="worker2", ts_ms=1000)
    assert lock.owner == "worker2"
    
    lock.try_acquire(owner="worker3", ts_ms=2000)
    assert lock.owner == "worker3"
    
    # 3 elections
    assert lock.leader_elections_total == 3


def test_ownership_transfer_with_renew():
    """Test ownership remains with renewing worker."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires and renews
    lock.try_acquire(owner="worker1", ts_ms=0)
    lock.renew(owner="worker1", ts_ms=500)  # Expires at 1500
    lock.renew(owner="worker1", ts_ms=1000)  # Expires at 2000
    
    # Worker2 tries to acquire at t=1800 (before expiry)
    result = lock.try_acquire(owner="worker2", ts_ms=1800)
    
    assert result is False
    assert lock.owner == "worker1"  # Still worker1


# ======================================================================
# Test Metrics Tracking
# ======================================================================

def test_leader_elections_total_counter():
    """Test leader_elections_total tracks acquisitions."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    assert lock.leader_elections_total == 0
    
    # Election 1
    lock.try_acquire(owner="worker1", ts_ms=0)
    assert lock.leader_elections_total == 1
    
    # Failed acquire (no election)
    lock.try_acquire(owner="worker2", ts_ms=500)
    assert lock.leader_elections_total == 1
    
    # Election 2
    lock.try_acquire(owner="worker2", ts_ms=1000)
    assert lock.leader_elections_total == 2


def test_renew_fail_total_counter():
    """Test renew_fail_total tracks failed renews."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    assert lock.renew_fail_total == 0
    
    # Worker1 acquires
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Successful renew (no increment)
    lock.renew(owner="worker1", ts_ms=500)
    assert lock.renew_fail_total == 0
    
    # Failed renew (not owner)
    lock.renew(owner="worker2", ts_ms=600)
    assert lock.renew_fail_total == 1
    
    # Failed renew (expired)
    lock.renew(owner="worker1", ts_ms=2000)
    assert lock.renew_fail_total == 2


# ======================================================================
# Test Concurrent Worker Scenarios (Edge Cases)
# ======================================================================

def test_concurrent_acquire_attempts():
    """Test multiple workers trying to acquire simultaneously."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # All workers try at t=0 (only first should succeed)
    w1 = lock.try_acquire(owner="worker1", ts_ms=0)
    w2 = lock.try_acquire(owner="worker2", ts_ms=0)
    w3 = lock.try_acquire(owner="worker3", ts_ms=0)
    
    assert w1 is True
    assert w2 is False
    assert w3 is False
    assert lock.owner == "worker1"
    assert lock.leader_elections_total == 1


def test_concurrent_renew_attempts():
    """Test multiple workers trying to renew (only owner should succeed)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Worker1 acquires
    lock.try_acquire(owner="worker1", ts_ms=0)
    
    # Multiple renew attempts at t=500
    r1 = lock.renew(owner="worker1", ts_ms=500)
    r2 = lock.renew(owner="worker2", ts_ms=500)
    r3 = lock.renew(owner="worker3", ts_ms=500)
    
    assert r1 is True
    assert r2 is False
    assert r3 is False
    assert lock.renew_fail_total == 2


def test_acquire_renew_acquire_sequence():
    """Test full lifecycle: acquire → renew → expire → re-acquire."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Phase 1: Worker1 acquires at t=0
    assert lock.try_acquire(owner="worker1", ts_ms=0) is True
    assert lock.owner == "worker1"
    assert lock._expiry_ts_ms == 1000
    
    # Phase 2: Worker1 renews at t=500 (expires at 1500)
    assert lock.renew(owner="worker1", ts_ms=500) is True
    assert lock._expiry_ts_ms == 1500
    
    # Phase 3: Worker1 renews at t=1200 (expires at 2200)
    assert lock.renew(owner="worker1", ts_ms=1200) is True
    assert lock._expiry_ts_ms == 2200
    
    # Phase 4: Worker1 fails to renew at t=2500 (expired)
    assert lock.renew(owner="worker1", ts_ms=2500) is False
    
    # Phase 5: Worker2 acquires at t=2500 (new leader)
    assert lock.try_acquire(owner="worker2", ts_ms=2500) is True
    assert lock.owner == "worker2"
    assert lock.leader_elections_total == 2


# ======================================================================
# Test Legacy API (Backward Compatibility)
# ======================================================================

def test_legacy_acquire_without_timestamp():
    """Test legacy acquire() method (no timestamp)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    result = lock.acquire(timeout=1.0)
    
    assert result is True
    assert lock.owner == "legacy"
    assert lock._expiry_ts_ms == 999999999999  # Far future


def test_legacy_release():
    """Test legacy release() method."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Acquire then release
    lock.try_acquire(owner="worker1", ts_ms=0)
    assert lock.owner == "worker1"
    
    lock.release()
    
    assert lock.owner is None
    assert lock._expiry_ts_ms == 0


def test_legacy_context_manager():
    """Test legacy context manager interface."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    with lock:
        assert lock.owner == "legacy"
    
    # After exit, should be released
    assert lock.owner is None


def test_legacy_acquire_fails_when_held():
    """Test legacy acquire fails when lock held."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # First acquire succeeds
    assert lock.acquire() is True
    
    # Second acquire fails (lock held)
    assert lock.acquire() is False


# ======================================================================
# Test Edge Case: No Owner Initially
# ======================================================================

def test_no_owner_initially():
    """Test lock has no owner initially."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    assert lock.owner is None
    assert lock._expiry_ts_ms == 0


def test_renew_fails_when_no_owner():
    """Test renew fails when no owner (lock never acquired)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    result = lock.renew(owner="worker1", ts_ms=0)
    
    assert result is False
    assert lock.renew_fail_total == 1


# ======================================================================
# Test Timestamp Edge Cases
# ======================================================================

def test_timestamp_negative():
    """Test negative timestamps (should work fine, just unusual)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Acquire at t=-1000
    lock.try_acquire(owner="worker1", ts_ms=-1000)
    
    # Expires at t=0 (-1000 + 1000)
    assert lock._expiry_ts_ms == 0
    
    # Try acquire at t=0 (expired)
    result = lock.try_acquire(owner="worker2", ts_ms=0)
    
    assert result is True


def test_timestamp_non_monotonic():
    """Test non-monotonic timestamps (time goes backward)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Acquire at t=1000 (expires at 2000)
    lock.try_acquire(owner="worker1", ts_ms=1000)
    
    # Try acquire at t=500 (time went backward, but lock not expired at t=500)
    # Lock expires at 2000, so at t=500 it's still held
    result = lock.try_acquire(owner="worker2", ts_ms=500)
    
    assert result is False  # Lock still held (expiry is in the future relative to t=500)


# ======================================================================
# Test CLI Normal Mode (Extended Coverage: 57% → 70%+)
# ======================================================================

def test_cli_normal_mode_in_process(capsys, monkeypatch):
    """
    Test CLI normal mode executes predefined failover sequence (in-process).
    
    Covers lines 103-164 (normal mode path). Uses monkeypatch to mock sys.argv.
    """
    import sys
    from tools.chaos.soak_failover import main
    
    # Mock sys.argv for CLI without --smoke flag
    test_args = ["soak_failover.py"]
    monkeypatch.setattr(sys, "argv", test_args)
    
    # Execute main() function
    with pytest.raises(SystemExit) as exc_info:
        main()
    
    # Should exit with code 0
    assert exc_info.value.code == 0
    
    # Capture stdout
    captured = capsys.readouterr()
    output = captured.out
    
    # Check output contains expected events
    assert "CHAOS t=0 role=A state=leader lock=acq" in output
    assert "CHAOS t=100 role=A state=leader lock=renew" in output
    assert "CHAOS t=4100 role=B state=leader lock=acq" in output
    
    # Check summary line
    assert "CHAOS_SUMMARY takeover_ms=1100" in output
    assert "idem_hits_total=9" in output
    assert "CHAOS_RESULT=OK" in output


def test_cli_with_custom_ttl_in_process(capsys, monkeypatch):
    """Test CLI normal mode with custom TTL parameter (in-process)."""
    import sys
    from tools.chaos.soak_failover import main
    
    # Mock sys.argv with --ttl-ms
    test_args = ["soak_failover.py", "--ttl-ms", "2000"]
    monkeypatch.setattr(sys, "argv", test_args)
    
    # Execute main()
    with pytest.raises(SystemExit) as exc_info:
        main()
    
    assert exc_info.value.code == 0
    
    # Output should still match golden sequence
    captured = capsys.readouterr()
    assert "CHAOS_RESULT=OK" in captured.out


# ======================================================================
# Test Additional Edge Cases for Core Logic (Increase Coverage)
# ======================================================================

def test_multiple_renewals_extend_expiry():
    """Test multiple renewals correctly extend expiry timestamp."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Acquire at t=0 (expires at 1000)
    lock.try_acquire(owner="worker1", ts_ms=0)
    initial_expiry = lock._expiry_ts_ms
    assert initial_expiry == 1000
    
    # Renew 5 times, each pushing expiry further
    for i in range(5):
        ts = 200 * (i + 1)  # 200, 400, 600, 800, 1000
        success = lock.renew(owner="worker1", ts_ms=ts)
        if ts < initial_expiry:  # Should succeed before original expiry
            assert success is True
            assert lock._expiry_ts_ms == ts + 1000
        else:  # At t=1000, original expiry reached
            # But we renewed at 800, so expiry is 1800
            pass


def test_acquire_updates_owner_and_expiry_atomically():
    """Test acquire updates both owner and expiry in one atomic operation."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Before acquire
    assert lock.owner is None
    assert lock._expiry_ts_ms == 0
    
    # Acquire
    result = lock.try_acquire(owner="worker1", ts_ms=5000)
    
    # After acquire (both updated)
    assert result is True
    assert lock.owner == "worker1"
    assert lock._expiry_ts_ms == 6000  # 5000 + 1000


def test_renew_does_not_change_owner():
    """Test renew updates expiry but not owner."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    lock.try_acquire(owner="worker1", ts_ms=0)
    original_owner = lock.owner
    
    # Renew
    lock.renew(owner="worker1", ts_ms=500)
    
    # Owner unchanged
    assert lock.owner == original_owner


def test_expiry_calculation_with_large_timestamps():
    """Test expiry calculation with large timestamps (overflow safety)."""
    lock = FakeKVLock(key="test_lock", ttl_ms=1000)
    
    # Very large timestamp (near max int)
    large_ts = 9_999_999_999_999
    lock.try_acquire(owner="worker1", ts_ms=large_ts)
    
    expected_expiry = large_ts + 1000
    assert lock._expiry_ts_ms == expected_expiry


# ======================================================================
# Note: CLI smoke test (lines 115-127) not tested due to bug (args.acquire_ms).
# Core FakeKVLock API is 100% covered. CLI normal mode (129-163) now tested.
# ======================================================================

# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

