from __future__ import annotations
import platform
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.isolation_abstraction.isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities, RuntimeConfig,
    RuntimeHandle, ExecutionPayload, ExecutionResult, SnapshotRef,
    RuntimeLifecycleState, ExecutionContext,
    TIER_CAPABILITIES,
    _set_handle_state, _get_handle_state, _clear_handle_state,
)

_QEMU_BINARY = "qemu-system-x86_64"
_KVM_DEVICE = Path("/dev/kvm")


class QemuRuntime(IsolationDriver):
    """
    Tier 2 — QEMU/KVM driver.
    Requires: Linux + /dev/kvm + qemu-system-x86_64 binary.
    Higher attack surface than Firecracker (TIER_RISK_ADJUSTMENTS = -5).
    create_runtime/execute are functional stubs — full boot flow in Plan C.
    """

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.QEMU

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.QEMU]

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._detect()
        return self._available

    def _detect(self) -> bool:
        if platform.system().lower() != "linux":
            return False
        if not _KVM_DEVICE.exists():
            return False
        if not shutil.which(_QEMU_BINARY):
            return False
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        if not self.is_available():
            raise RuntimeError(
                "QemuRuntime unavailable: requires Linux + /dev/kvm + qemu-system-x86_64"
            )
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="qemu",
            tier=IsolationTier.QEMU,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        _set_handle_state(handle.runtime_id, "agent_id", config.agent_id)
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
        _set_handle_state(handle.runtime_id, "profile", config.profile)
        return handle

    async def execute(
        self,
        handle: RuntimeHandle,
        payload: ExecutionPayload,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionResult:
        ctx = ctx or ExecutionContext()
        return ExecutionResult(
            success=False,
            output="",
            error="QemuRuntime.execute: full QEMU/KVM execution not yet implemented (Plan C)",
            exit_code=1,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.QEMU,
            duration_ms=0,
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.FAILED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.DESTROYED)
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        state = _get_handle_state(handle.runtime_id, "state")
        if state not in (RuntimeLifecycleState.RUNNING, RuntimeLifecycleState.FROZEN):
            return SnapshotRef(available=False, reason="vm_not_running", snapshot_reason="MANUAL")
        return SnapshotRef(
            available=False,
            reason="qemu_snapshot_stub_plan_c",
            snapshot_reason="MANUAL",
        )

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
