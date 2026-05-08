"""
docker_hardened_driver.py — Tier 3 DockerHardened IsolationDriver
Task 7 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: stdlib + core.isolation_abstraction.isolation_driver only.
docker SDK imported lazily inside methods.
"""
from __future__ import annotations

import platform
import subprocess
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
    from core.security.permission_manager import get_permission_manager
except Exception:
    get_permission_manager = None  # type: ignore[assignment]

# Hardened container run config — applied to every container
_HARDENED_RUN_KWARGS = dict(
    network_mode="none",
    mem_swappiness=0,
    pids_limit=64,
    security_opt=["no-new-privileges:true"],
    cap_drop=["ALL"],
    tmpfs={"/tmp": "size=64m,noexec,nosuid,nodev"},
    init=False,
    detach=True,
    remove=False,  # explicit lifecycle management
)


class DockerHardenedDriver(IsolationDriver):

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self._daemon_info: Optional[dict] = None

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.DOCKER_HARDENED

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.DOCKER_HARDENED]

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._check_docker_available()
        return self._available

    def _check_docker_available(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _verify_daemon(self) -> dict:
        """Verify daemon health and return info dict. Triggers degradation on failure."""
        try:
            client = self._get_client()
            info = client.info()
            security_opts = info.get("SecurityOptions", [])
            return {
                "healthy": True,
                "runtime": info.get("DefaultRuntime", "runc"),
                "cgroup_driver": info.get("CgroupDriver"),
                "security_options": security_opts,
                "seccomp_enabled": any("seccomp" in o for o in security_opts),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def _get_client(self):
        import docker
        sys = platform.system().lower()
        if sys == "windows":
            return docker.DockerClient(base_url="npipe:////./pipe/docker_engine")
        return docker.from_env()

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        # Verify daemon health — degrade if unhealthy
        health = self._verify_daemon()
        if not health.get("healthy", False):
            raise RuntimeError(
                f"Docker daemon unhealthy: {health.get('error', 'unknown')}"
            )

        client = self._get_client()
        kwargs = dict(_HARDENED_RUN_KWARGS)
        kwargs["mem_limit"] = f"{config.max_ram_mb}m"
        # cpu_quota: percentage * cpu_period (100_000 microseconds)
        kwargs["cpu_period"] = 100_000
        kwargs["cpu_quota"] = int(config.max_cpu_percent * 1_000)

        container = client.containers.run(
            "python:3.11-slim",
            command="sleep infinity",
            **kwargs,
        )

        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        _set_handle_state(handle.runtime_id, "container_id", container.id)
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
        client = self._get_client()
        ctr_id = _get_handle_state(handle.runtime_id, "container_id")

        try:
            container = client.containers.get(ctr_id)
            cmd = payload.command or (
                f"python -c {repr(payload.code)}" if payload.code else "echo ''"
            )
            exit_code, output_bytes = container.exec_run(
                cmd,
                demux=False,
                timeout=payload.timeout_seconds,
            )
            output = output_bytes.decode(errors="replace") if output_bytes else ""
            error = output if (exit_code or 0) != 0 else None
            code = exit_code or 0
        except Exception as e:
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                exit_code=1,
                runtime_id=handle.runtime_id,
                tier_used=IsolationTier.DOCKER_HARDENED,
                duration_ms=int((time.monotonic() - start) * 1000),
                execution_id=ctx.execution_id,
                correlation_id=ctx.correlation_id,
                trace_id=ctx.trace_id,
                runtime_state=RuntimeLifecycleState.FAILED,
            )

        return ExecutionResult(
            success=code == 0,
            output=output,
            error=error,
            exit_code=code,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.DOCKER_HARDENED,
            duration_ms=int((time.monotonic() - start) * 1000),
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.DESTROYED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        ctr_id = _get_handle_state(handle.runtime_id, "container_id")
        if ctr_id:
            try:
                client = self._get_client()
                container = client.containers.get(ctr_id)
                container.remove(force=True)
            except Exception:
                pass
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        ctr_id = _get_handle_state(handle.runtime_id, "container_id")
        try:
            client = self._get_client()
            container = client.containers.get(ctr_id)
            snap_tag = f"nexus-snap-{uuid.uuid4().hex[:8]}"
            image = container.commit(repository=snap_tag)
            return SnapshotRef(
                available=True,
                snapshot_id=image.id,
                snapshot_reason="MANUAL",
                integrity_hash=image.id,  # Docker image ID is a content hash
            )
        except Exception as e:
            return SnapshotRef(available=False, reason=str(e), snapshot_reason="MANUAL")

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        """Pause container (freeze without destroying — preserve for forensics)."""
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
        ctr_id = _get_handle_state(handle.runtime_id, "container_id")
        if ctr_id:
            try:
                client = self._get_client()
                container = client.containers.get(ctr_id)
                container.pause()  # freeze, NOT remove — forensic preservation
            except Exception:
                pass
        agent_id = _get_handle_state(handle.runtime_id, "agent_id", "unknown")
        try:
            get_permission_manager().isolate_agent(agent_id, reason)
        except Exception:
            pass
