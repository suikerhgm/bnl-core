# core/vm_isolation/vm_manager.py
"""
VMManager — internal orchestrator for VM-tier runtimes.
NOT itself an IsolationDriver. Holds FirecrackerRuntime + QemuRuntime,
coordinates guardian + lifecycle + policy engine.
Call get_drivers() for the list of available IsolationDriver instances.
"""
from __future__ import annotations
import threading
from typing import Optional

from core.isolation_abstraction.isolation_driver import IsolationDriver, IsolationTier
from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
from core.vm_isolation.qemu_runtime import QemuRuntime
from core.vm_isolation.vm_escape_detector import VMEscapeDetector
from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
from core.vm_isolation.vm_policy_engine import VMPolicyEngine


class VMManager:
    """
    Internal orchestrator for VM-tier runtimes.
    Provides access to Tier 1 (Firecracker) and Tier 2 (QEMU) drivers,
    plus HypervisorGuardian, VMLifecycleTracker, VMPolicyEngine.
    """

    def __init__(self) -> None:
        self._firecracker = FirecrackerRuntime()
        self._qemu = QemuRuntime()
        self._policy_engine = VMPolicyEngine()
        self._escape_detector = VMEscapeDetector()
        self._lifecycle = VMLifecycleTracker()
        self._guardian = HypervisorGuardian(
            lifecycle_tracker=self._lifecycle,
            escape_detector=self._escape_detector,
        )

    @property
    def firecracker(self) -> FirecrackerRuntime:
        return self._firecracker

    @property
    def qemu(self) -> QemuRuntime:
        return self._qemu

    @property
    def guardian(self) -> HypervisorGuardian:
        return self._guardian

    @property
    def lifecycle(self) -> VMLifecycleTracker:
        return self._lifecycle

    @property
    def policy_engine(self) -> VMPolicyEngine:
        return self._policy_engine

    def has_vm_isolation(self) -> bool:
        """True if at least one VM-tier driver is available."""
        return self._firecracker.is_available() or self._qemu.is_available()

    def best_available_vm_tier(self) -> Optional[IsolationTier]:
        """Returns best available VM tier, or None if none available."""
        if self._firecracker.is_available():
            return IsolationTier.FIRECRACKER
        if self._qemu.is_available():
            return IsolationTier.QEMU
        return None

    def get_drivers(self) -> list[IsolationDriver]:
        """
        Returns available VM-tier drivers in priority order.
        On Windows: returns [] (both unavailable).
        On Linux+KVM: returns [FirecrackerRuntime] or both.
        """
        drivers: list[IsolationDriver] = []
        if self._firecracker.is_available():
            drivers.append(self._firecracker)
        if self._qemu.is_available():
            drivers.append(self._qemu)
        return drivers


_instance: Optional[VMManager] = None
_lock = threading.Lock()


def get_vm_manager() -> VMManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = VMManager()
    return _instance
