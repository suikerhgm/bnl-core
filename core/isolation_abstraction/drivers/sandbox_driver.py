"""
sandbox_driver.py — Tier 4 Sandbox IsolationDriver
Task 6 of the Nexus BNL Isolation Abstraction Layer.

Always available. Wraps the existing SandboxManager with health validation,
stale cleanup, quarantine escalation hooks, and forensic preservation.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.isolation_abstraction.isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities, RuntimeConfig,
    RuntimeHandle, ExecutionPayload, ExecutionResult, SnapshotRef,
    RuntimeLifecycleState, ExecutionContext,
    TIER_CAPABILITIES,
    _set_handle_state, _get_handle_state, _clear_handle_state,
)

# Lazy module-level references — patched by tests via module path
try:
    from core.sandbox.sandbox_manager import get_sandbox_manager
except Exception:
    get_sandbox_manager = None  # type: ignore[assignment]

try:
    from core.security.permission_manager import get_permission_manager
except Exception:
    get_permission_manager = None  # type: ignore[assignment]


class SandboxDriver(IsolationDriver):
    """Tier 4 driver — always available, wraps the existing SandboxManager."""

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.SANDBOX

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.SANDBOX]

    def is_available(self) -> bool:
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        import core.isolation_abstraction.drivers.sandbox_driver as _self_mod
        mgr_factory = _self_mod.get_sandbox_manager
        mgr = mgr_factory()

        # Health validation before creating
        try:
            if hasattr(mgr, "get_health_status"):
                health = mgr.get_health_status()
                if not health.get("healthy", True):
                    raise RuntimeError("SandboxManager health check failed")
        except (AttributeError, TypeError):
            pass  # older SandboxManager without health check — proceed

        result = mgr.create_sandbox(
            agent_id=config.agent_id,
            mode="STRICT_ISOLATION",
        )
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="sandbox",
            tier=IsolationTier.SANDBOX,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        sandbox_id = result.sandbox_id if hasattr(result, "sandbox_id") else result.get("sandbox_id", str(uuid.uuid4()))
        _set_handle_state(handle.runtime_id, "sandbox_id", sandbox_id)
        _set_handle_state(handle.runtime_id, "agent_id", config.agent_id)
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
        return handle

    async def execute(
        self,
        handle: RuntimeHandle,
        payload: ExecutionPayload,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionResult:
        ctx = ctx or ExecutionContext()
        start = time.monotonic()
        import core.isolation_abstraction.drivers.sandbox_driver as _self_mod
        mgr_factory = _self_mod.get_sandbox_manager
        mgr = mgr_factory()

        sandbox_id = _get_handle_state(handle.runtime_id, "sandbox_id")
        agent_id = _get_handle_state(handle.runtime_id, "agent_id", "unknown")
        cmd = payload.command or (
            f"python -c {repr(payload.code)}" if payload.code else "echo ''"
        )

        try:
            result = mgr.execute_in_sandbox(
                command=cmd,
                mode="STRICT_ISOLATION",
                agent_id=agent_id,
            )
            success = result.get("success", False)
            output = result.get("output", "")
            error = result.get("error")
            code = result.get("exit_code", 0)
        except Exception as e:
            success, output, error, code = False, "", str(e), 1

        return ExecutionResult(
            success=success,
            output=output,
            error=error,
            exit_code=code,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.SANDBOX,
            duration_ms=int((time.monotonic() - start) * 1000),
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.DESTROYED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        sandbox_id = _get_handle_state(handle.runtime_id, "sandbox_id")
        if sandbox_id:
            try:
                import core.isolation_abstraction.drivers.sandbox_driver as _self_mod
                mgr_factory = _self_mod.get_sandbox_manager
                mgr_factory().destroy_sandbox(sandbox_id)
            except Exception:
                pass
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        return SnapshotRef(
            available=False,
            reason="sandbox_no_snapshots",
            snapshot_reason="MANUAL",
        )

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
        sandbox_id = _get_handle_state(handle.runtime_id, "sandbox_id")
        agent_id = _get_handle_state(handle.runtime_id, "agent_id", "unknown")

        # Quarantine in SandboxManager (forensic preservation — don't destroy)
        if sandbox_id:
            try:
                import core.isolation_abstraction.drivers.sandbox_driver as _self_mod
                mgr_factory = _self_mod.get_sandbox_manager
                mgr_factory().quarantine_sandbox(sandbox_id, reason)
            except Exception:
                pass

        # Escalate to permission manager
        try:
            import core.isolation_abstraction.drivers.sandbox_driver as _self_mod
            pm_factory = _self_mod.get_permission_manager
            if pm_factory is None:
                return
            pm_factory().isolate_agent(agent_id, reason)
        except Exception:
            pass
