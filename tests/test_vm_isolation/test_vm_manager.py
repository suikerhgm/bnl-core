# tests/test_vm_isolation/test_vm_manager.py
import platform
import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier


def test_vm_manager_singleton():
    from core.vm_isolation.vm_manager import get_vm_manager
    m1 = get_vm_manager()
    m2 = get_vm_manager()
    assert m1 is m2


def test_vm_manager_firecracker_property():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    mgr = VMManager()
    assert isinstance(mgr.firecracker, FirecrackerRuntime)


def test_vm_manager_qemu_property():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.qemu_runtime import QemuRuntime
    mgr = VMManager()
    assert isinstance(mgr.qemu, QemuRuntime)


def test_vm_manager_guardian_property():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    mgr = VMManager()
    assert isinstance(mgr.guardian, HypervisorGuardian)


def test_vm_manager_lifecycle_property():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    mgr = VMManager()
    assert isinstance(mgr.lifecycle, VMLifecycleTracker)


def test_vm_manager_policy_engine_property():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.vm_policy_engine import VMPolicyEngine
    mgr = VMManager()
    assert isinstance(mgr.policy_engine, VMPolicyEngine)


def test_vm_manager_has_vm_isolation_false_on_windows():
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    if platform.system().lower() == "windows":
        assert mgr.has_vm_isolation() is False


def test_vm_manager_best_tier_none_on_windows():
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    if platform.system().lower() == "windows":
        assert mgr.best_available_vm_tier() is None


def test_vm_manager_get_drivers_empty_on_windows():
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    if platform.system().lower() == "windows":
        assert mgr.get_drivers() == []


def test_vm_manager_get_drivers_returns_list():
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    drivers = mgr.get_drivers()
    assert isinstance(drivers, list)
    # All items must be IsolationDriver instances
    from core.isolation_abstraction.isolation_driver import IsolationDriver
    for d in drivers:
        assert isinstance(d, IsolationDriver)
