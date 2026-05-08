# core/vm_isolation/hypervisor_guardian.py
"""
HypervisorGuardian — base monitoring daemon for active VMs.
Polls registered VMs, runs escape detection, dispatches alerts.
Full kernel-level probes (KVM perf, inotify, memory balloon) in Plan C.
"""
from __future__ import annotations
import threading
import time
from typing import Callable, Optional

from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.vm_isolation.vm_escape_detector import (
    VMEscapeDetector, EscapeSignal, EscapeSeverity,
)
from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
from core.vm_isolation.vm_policy_engine import VMProfile


class HypervisorGuardian:
    """
    Base monitoring daemon. Polls registered VMs, runs escape detection,
    dispatches alerts to registered callbacks. Architecture-complete stub.
    """

    def __init__(
        self,
        audit_logger: Optional[IsolationAuditLogger] = None,
        lifecycle_tracker: Optional[VMLifecycleTracker] = None,
        escape_detector: Optional[VMEscapeDetector] = None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._tracker = lifecycle_tracker or VMLifecycleTracker(audit_logger=self._logger)
        self._detector = escape_detector or VMEscapeDetector()
        self._poll_interval = poll_interval_seconds

        self._vms: dict[str, dict] = {}           # vm_id → {tier, profile}
        self._vms_lock = threading.Lock()
        self._callbacks: list[Callable[[EscapeSignal], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HypervisorGuardian",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._poll_interval * 2 + 1)
            self._thread = None

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def register_vm(self, vm_id: str, tier: IsolationTier, profile: VMProfile) -> None:
        with self._vms_lock:
            self._vms[vm_id] = {"tier": tier, "profile": profile}

    def deregister_vm(self, vm_id: str) -> None:
        with self._vms_lock:
            self._vms.pop(vm_id, None)

    def monitored_vms(self) -> list[str]:
        with self._vms_lock:
            return list(self._vms.keys())

    def register_alert_callback(self, callback: Callable[[EscapeSignal], None]) -> None:
        self._callbacks.append(callback)

    def _dispatch_alert(self, signal: EscapeSignal) -> None:
        severity = "CRITICAL" if signal.severity == EscapeSeverity.CRITICAL else "WARNING"
        self._logger.log_event(
            vm_id=signal.vm_id,
            event_type="ESCAPE_SIGNAL",
            severity=severity,
            description=f"{signal.signal_type.value} via {signal.detection_method}",
            metadata={
                "signal_type": signal.signal_type.value,
                "severity": signal.severity.value,
                "evidence": signal.evidence,
            },
            origin_component="hypervisor_guardian",
        )
        for cb in self._callbacks:
            try:
                cb(signal)
            except Exception:
                pass

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                try:
                    self._logger.log_event(
                        vm_id="system",
                        event_type="GUARDIAN_ERROR",
                        severity="ERROR",
                        description=f"Monitor loop error: {type(e).__name__}: {e}",
                        metadata={"error_type": type(e).__name__},
                        origin_component="hypervisor_guardian",
                    )
                except Exception:
                    pass  # logger itself failed — truly silent fallback
            time.sleep(self._poll_interval)

    def _poll_once(self) -> None:
        with self._vms_lock:
            vm_ids = list(self._vms.keys())
        for vm_id in vm_ids:
            signals = self._detector.scan_all(vm_id, runtime_metadata={})
            for signal in signals:
                self._dispatch_alert(signal)

    def get_stats(self) -> dict:
        return {
            "monitored_count": len(self.monitored_vms()),
            "is_running": self.is_running(),
            "poll_interval_seconds": self._poll_interval,
            "callback_count": len(self._callbacks),
        }
