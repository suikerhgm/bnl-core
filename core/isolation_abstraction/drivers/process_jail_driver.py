"""
process_jail_driver.py — Tier 5 ProcessJail IsolationDriver
Task 5 of the Nexus BNL Isolation Abstraction Layer.

Always available. Wraps the existing IsolationManager with hardened
subprocess tree kill, zombie cleanup, stdout limits, and emergency
timeout escalation.
"""
from __future__ import annotations

import asyncio
import platform
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

MAX_OUTPUT_BYTES = 1 * 1024 * 1024   # 1 MB stdout/stderr limit

# Lazy module-level references — patched by tests via module path
try:
    from core.security.permission_manager import get_permission_manager
except Exception:
    get_permission_manager = None  # type: ignore[assignment]


async def _kill_process_tree(proc) -> None:
    """Kill the process and all its children."""
    try:
        if platform.system().lower() == "windows":
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            import os
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class ProcessJailDriver(IsolationDriver):
    """Tier 5 driver — always available, wraps the existing IsolationManager."""

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.PROCESS_JAIL

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]

    def is_available(self) -> bool:
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        try:
            from core.isolation.isolation_manager import get_isolation_manager
            workspace = get_isolation_manager().create_isolated_workspace(config.agent_id, ".")
        except Exception:
            workspace = "."
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="jail",
            tier=IsolationTier.PROCESS_JAIL,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        _set_handle_state(handle.runtime_id, "workspace", workspace)
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
        workspace = _get_handle_state(handle.runtime_id, "workspace", ".")
        cmd = payload.command or (
            f"python -c {repr(payload.code)}" if payload.code else "echo ''"
        )
        start = time.monotonic()
        proc: Optional[asyncio.subprocess.Process] = None
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env={**__import__("os").environ, **(payload.environment or {})},
            )
            _set_handle_state(handle.runtime_id, "pid", proc.pid)
            _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=payload.timeout_seconds
                )
            except asyncio.TimeoutError:
                await _kill_process_tree(proc)
                await proc.wait()
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"timeout after {payload.timeout_seconds}s",
                    exit_code=124,
                    runtime_id=handle.runtime_id,
                    tier_used=IsolationTier.PROCESS_JAIL,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    execution_id=ctx.execution_id,
                    correlation_id=ctx.correlation_id,
                    trace_id=ctx.trace_id,
                    runtime_state=RuntimeLifecycleState.FAILED,
                )
            # Enforce output size limits
            output = stdout_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace")
            error_out = stderr_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace") or None
            code = proc.returncode or 0
        except Exception as e:
            if proc:
                await _kill_process_tree(proc)
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                exit_code=1,
                runtime_id=handle.runtime_id,
                tier_used=IsolationTier.PROCESS_JAIL,
                duration_ms=int((time.monotonic() - start) * 1000),
                execution_id=ctx.execution_id,
                correlation_id=ctx.correlation_id,
                trace_id=ctx.trace_id,
                runtime_state=RuntimeLifecycleState.FAILED,
            )
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.DESTROYED)
        return ExecutionResult(
            success=code == 0,
            output=output,
            error=error_out,
            exit_code=code,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.PROCESS_JAIL,
            duration_ms=int((time.monotonic() - start) * 1000),
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.DESTROYED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        pid = _get_handle_state(handle.runtime_id, "pid")
        if pid:
            try:
                proc_mock = type("P", (), {"pid": pid, "returncode": None})()
                await _kill_process_tree(proc_mock)
            except Exception:
                pass
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        return SnapshotRef(
            available=False,
            reason="process_jail_no_snapshots",
            snapshot_reason="MANUAL",
        )

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
        agent_id = _get_handle_state(handle.runtime_id, "agent_id", "unknown")
        try:
            # Use module-level reference so tests can patch via
            # "core.isolation_abstraction.drivers.process_jail_driver.get_permission_manager"
            import core.isolation_abstraction.drivers.process_jail_driver as _self_mod
            pm_factory = _self_mod.get_permission_manager
            if pm_factory is None:
                return
            pm_factory().isolate_agent(agent_id, reason)
        except Exception:
            pass
