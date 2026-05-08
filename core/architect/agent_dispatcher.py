# core/architect/agent_dispatcher.py
"""
AgentDispatcher — the ONLY component that touches UnifiedIsolationRuntime.
execute_isolated() is the ONLY execution path. No exceptions.
"""
from __future__ import annotations
import uuid
from typing import Optional

from core.architect.models import (
    AgentAssignment, DispatchResult,
    TASK_TYPE_TO_PERMISSION, RISK_TO_MIN_SECURITY_SCORE,
)
from core.isolation_abstraction.isolation_driver import ExecutionPayload, ExecutionContext

MAX_OUTPUT_BYTES = 512 * 1024   # 512 KB
MAX_ERROR_BYTES  = 64  * 1024   # 64 KB


class AgentDispatcher:
    def __init__(self, runtime=None, permission_manager=None, registry=None) -> None:
        if runtime is None:
            from core.isolation_abstraction.unified_isolation_runtime import get_unified_runtime
            runtime = get_unified_runtime()
        if permission_manager is None:
            from core.security.permission_manager import get_permission_manager
            permission_manager = get_permission_manager()
        if registry is None:
            from core.agents.nexus_registry import get_registry
            registry = get_registry()
        self._runtime = runtime
        self._perm = permission_manager
        self._registry = registry

    def _has_permission(self, agent_id: str, permission_id: str) -> bool:
        """
        Adapter: PermissionManager exposes check_permission(); mocks may expose
        has_permission(). Try has_permission first (for tests), fall back to
        check_permission (production).
        """
        checker = getattr(self._perm, "has_permission", None)
        if checker is not None:
            return checker(agent_id, permission_id)
        return self._perm.check_permission(agent_id, permission_id, log_check=False)

    async def dispatch(self, assignment: AgentAssignment, plan_id: str) -> DispatchResult:
        task = assignment.task
        required_perm = TASK_TYPE_TO_PERMISSION.get(task.task_type, "FS_READ")

        if not self._has_permission(assignment.assigned_agent_id, required_perm):
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id,
                agent_id=assignment.assigned_agent_id,
                success=False, output="", error="permission_denied_at_dispatch",
                exit_code=1, tier_used=None,
                security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )

        ctx = ExecutionContext(
            correlation_id=f"{plan_id}:{task.task_id}",
            trace_id=str(uuid.uuid4()),
            preserve_forensics=(task.risk_level in ("high", "critical")),
        )

        payload = ExecutionPayload(
            command=task.payload.get("command"),
            code=task.payload.get("code"),
            timeout_seconds=task.timeout_seconds,
            environment=task.payload.get("environment", {}),
        )

        result = await self._runtime.execute_isolated(
            payload=payload,
            policy=task.isolation_policy,
            ctx=ctx,
            minimum_security_score=RISK_TO_MIN_SECURITY_SCORE[task.risk_level],
            requires_forensics=(task.risk_level == "critical"),
        )

        output = (result.output or "")[:MAX_OUTPUT_BYTES]
        error  = (result.error  or "")[:MAX_ERROR_BYTES] if result.error else None

        if assignment.hired_temporary:
            try:
                self._registry.terminate_temporary_agent(assignment.assigned_agent_id)
                perms = self._perm.get_agent_permissions(assignment.assigned_agent_id)
                for perm in perms:
                    # perms may be dicts (production) or mock objects (tests)
                    perm_id = perm["permission_id"] if isinstance(perm, dict) else perm.permission_id
                    self._perm.revoke_permission(
                        assignment.assigned_agent_id, perm_id
                    )
            except Exception:
                pass

        return DispatchResult(
            task_id=task.task_id,
            plan_id=plan_id,
            agent_id=assignment.assigned_agent_id,
            success=result.success,
            output=output,
            error=error,
            exit_code=result.exit_code,
            tier_used=result.tier_used,
            security_score=(result.negotiation.security_score if result.negotiation else 0),
            fallback_level=(result.negotiation.fallback_level if result.negotiation else 0),
            duration_ms=result.duration_ms,
            execution_id=result.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            reputation_delta=0.0,
        )

    async def dispatch_with_retry(
        self, assignment: AgentAssignment, plan_id: str
    ) -> DispatchResult:
        policy = assignment.task.retry_policy
        result = None
        for _ in range(policy.max_retries + 1):
            result = await self.dispatch(assignment, plan_id)
            if result.success or not policy.retry_on_failure:
                return result
        return result
