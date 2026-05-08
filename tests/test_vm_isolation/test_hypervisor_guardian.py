# tests/test_vm_isolation/test_hypervisor_guardian.py
import time
import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.vm_isolation.vm_escape_detector import (
    EscapeSignal, EscapeSignalType, EscapeSeverity,
)
from core.vm_isolation.vm_policy_engine import VMProfile


@pytest.fixture
def guardian(tmp_path):
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    from core.vm_isolation.vm_escape_detector import VMEscapeDetector
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    logger = IsolationAuditLogger(db_path=tmp_path / "guardian.db")
    tracker = VMLifecycleTracker(audit_logger=logger)
    detector = VMEscapeDetector()
    return HypervisorGuardian(
        audit_logger=logger,
        lifecycle_tracker=tracker,
        escape_detector=detector,
        poll_interval_seconds=0.05,  # very fast for tests
    )


def test_guardian_starts_and_stops(guardian):
    guardian.start()
    assert guardian.is_running() is True
    guardian.stop()
    assert guardian.is_running() is False


def test_guardian_not_running_before_start(guardian):
    assert guardian.is_running() is False


def test_guardian_register_vm(guardian):
    guardian.register_vm("vm-g1", IsolationTier.DOCKER_HARDENED, VMProfile.SAFE_VM)
    assert "vm-g1" in guardian.monitored_vms()


def test_guardian_deregister_vm(guardian):
    guardian.register_vm("vm-g2", IsolationTier.SANDBOX, VMProfile.SAFE_VM)
    guardian.deregister_vm("vm-g2")
    assert "vm-g2" not in guardian.monitored_vms()


def test_guardian_alert_callback_dispatched(guardian):
    alerts = []

    def on_alert(sig: EscapeSignal) -> None:
        alerts.append(sig)

    guardian.register_alert_callback(on_alert)
    sig = EscapeSignal(
        vm_id="vm-g3",
        signal_type=EscapeSignalType.HYPERVISOR_PROBE,
        severity=EscapeSeverity.HIGH,
        evidence={},
        detection_method="test",
    )
    guardian._dispatch_alert(sig)
    assert len(alerts) == 1
    assert alerts[0].vm_id == "vm-g3"


def test_guardian_get_stats(guardian):
    stats = guardian.get_stats()
    assert "monitored_count" in stats
    assert "is_running" in stats
    assert "poll_interval_seconds" in stats
    assert "callback_count" in stats
    assert stats["monitored_count"] == 0
    assert stats["is_running"] is False
