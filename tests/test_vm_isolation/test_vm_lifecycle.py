import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier, RuntimeLifecycleState
from core.vm_isolation.vm_policy_engine import VMProfile


@pytest.fixture
def tracker(tmp_path):
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    logger = IsolationAuditLogger(db_path=tmp_path / "lifecycle.db")
    return VMLifecycleTracker(audit_logger=logger)


def test_tracker_create_session_returns_uuid(tracker):
    session_id = tracker.create_session(
        vm_id="vm-1", tier=IsolationTier.DOCKER_HARDENED,
        profile=VMProfile.SAFE_VM, agent_id="a1",
        security_score=70, risk_adjusted_score=70,
    )
    assert isinstance(session_id, str) and len(session_id) == 36


def test_tracker_state_is_running_after_create(tracker):
    tracker.create_session(
        vm_id="vm-2", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a2",
        security_score=40, risk_adjusted_score=40,
    )
    assert tracker.get_state("vm-2") == RuntimeLifecycleState.RUNNING


def test_tracker_transition_to_quarantined(tracker):
    tracker.create_session(
        vm_id="vm-3", tier=IsolationTier.DOCKER_HARDENED,
        profile=VMProfile.QUARANTINE_VM, agent_id="a3",
        security_score=70, risk_adjusted_score=70,
    )
    tracker.transition("vm-3", RuntimeLifecycleState.QUARANTINED, reason="escape detected")
    assert tracker.get_state("vm-3") == RuntimeLifecycleState.QUARANTINED


def test_tracker_transition_to_destroyed(tracker):
    tracker.create_session(
        vm_id="vm-4", tier=IsolationTier.PROCESS_JAIL,
        profile=VMProfile.SAFE_VM, agent_id="a4",
        security_score=20, risk_adjusted_score=20,
    )
    tracker.transition("vm-4", RuntimeLifecycleState.DESTROYED)
    assert tracker.get_state("vm-4") == RuntimeLifecycleState.DESTROYED


def test_tracker_unknown_vm_returns_none(tracker):
    assert tracker.get_state("nonexistent-vm") is None


def test_tracker_list_active_excludes_destroyed(tracker):
    tracker.create_session(
        vm_id="vm-5", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a5",
        security_score=40, risk_adjusted_score=40,
    )
    tracker.create_session(
        vm_id="vm-6", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a6",
        security_score=40, risk_adjusted_score=40,
    )
    tracker.transition("vm-6", RuntimeLifecycleState.DESTROYED)
    active = tracker.list_active()
    ids = [v["vm_id"] for v in active]
    assert "vm-5" in ids
    assert "vm-6" not in ids


def test_tracker_thread_safe(tracker):
    import threading
    errors = []
    def create():
        try:
            for i in range(5):
                tracker.create_session(
                    vm_id=f"vm-t{threading.get_ident()}-{i}",
                    tier=IsolationTier.SANDBOX,
                    profile=VMProfile.SAFE_VM, agent_id="t",
                    security_score=40, risk_adjusted_score=40,
                )
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=create) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
