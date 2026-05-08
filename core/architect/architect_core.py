# core/architect/architect_core.py
"""
ArchitectCore — pure façade: validate, sequence (DAG), route, aggregate.
Zero business logic. Zero execution. Zero agent knowledge.
"""
from __future__ import annotations
import asyncio
import threading
import time
from typing import Optional

# Module-level import so tests can patch("core.architect.architect_core.AgentTaskPlanner").
# The actual usage inside receive_request() also references this module-level name.
from core.architect.agent_task_planner import AgentTaskPlanner


class CyclicDependencyError(RuntimeError):
    pass


class ArchitectCore:
    def __init__(self, department_architects=None, dispatcher=None) -> None:
        if department_architects is None:
            from core.architect.department_architect import DepartmentArchitect
            department_architects = {
                dept: DepartmentArchitect(dept)
                for dept in ("engineering", "security", "frontend",
                             "research", "runtime", "repairs")
            }
        if dispatcher is None:
            from core.architect.agent_dispatcher import AgentDispatcher
            dispatcher = AgentDispatcher()
        self._depts = department_architects
        self._dispatcher = dispatcher

    async def orchestrate(self, plan, requestor_id: str):
        from core.architect.models import OrchestrationResult

        # Gate: human approval required
        if plan.requires_human_approval:
            return OrchestrationResult(
                plan_id=plan.plan_id, overall_success=False,
                completed_tasks=[], failed_tasks=[t.task_id for t in plan.subtasks],
                skipped_tasks=[], total_duration_ms=0,
                isolation_summary={}, audit_chain=[],
                human_approval_required=True, human_approval_granted=None,
            )

        # Gate: circular dependencies
        try:
            waves = self._resolve_dag(plan.subtasks)
        except CyclicDependencyError:
            return OrchestrationResult(
                plan_id=plan.plan_id, overall_success=False,
                completed_tasks=[], failed_tasks=[t.task_id for t in plan.subtasks],
                skipped_tasks=[], total_duration_ms=0,
                isolation_summary={}, audit_chain=[],
                human_approval_required=False, human_approval_granted=None,
            )

        start_ms = int(time.monotonic() * 1000)
        completed = []
        failed_ids = []
        skipped_ids = []

        for wave in waves:
            executable = [
                t for t in wave
                if t.task_id not in failed_ids
                and not any(dep in failed_ids for dep in t.depends_on)
            ]
            skipped_ids.extend(t.task_id for t in wave if t not in executable)

            if not executable:
                continue

            results = await asyncio.gather(
                *[self._route_task(task, plan.plan_id) for task in executable],
                return_exceptions=True,
            )

            for task, result in zip(executable, results):
                if isinstance(result, Exception):
                    failed_ids.append(task.task_id)
                elif result.success:
                    completed.append(result)
                else:
                    failed_ids.append(task.task_id)
                    completed.append(result)

            # Fail-fast for critical plans
            if failed_ids and plan.risk_level == "critical":
                remaining = [
                    t.task_id for w in waves for t in w
                    if t.task_id not in {r.task_id for r in completed}
                    and t.task_id not in failed_ids
                ]
                skipped_ids.extend(remaining)
                break

        total_ms = int(time.monotonic() * 1000) - start_ms
        tiers_used = [r.tier_used.name for r in completed if r.tier_used]
        scores = [r.security_score for r in completed]
        avg_score = sum(scores) // len(scores) if scores else 0

        return OrchestrationResult(
            plan_id=plan.plan_id,
            overall_success=len(failed_ids) == 0,
            completed_tasks=completed,
            failed_tasks=failed_ids,
            skipped_tasks=skipped_ids,
            total_duration_ms=total_ms,
            isolation_summary={"tiers_used": tiers_used, "avg_security_score": avg_score},
            audit_chain=[r.execution_id for r in completed],
            human_approval_required=plan.requires_human_approval,
            human_approval_granted=None,
        )

    async def _route_task(self, task, plan_id: str):
        from core.architect.models import DispatchResult
        from core.isolation_abstraction.isolation_driver import IsolationTier
        from core.architect.department_architect import NoEligibleAgentError
        import uuid

        dept = self._depts.get(task.required_department)
        if dept is None:
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id, agent_id="none",
                success=False, output="",
                error=f"no_architect_for_dept:{task.required_department}",
                exit_code=1, tier_used=None,
                security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )

        try:
            assignment = dept.assign(task, plan_id)
            return await self._dispatcher.dispatch_with_retry(assignment, plan_id)
        except NoEligibleAgentError as e:
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id, agent_id="none",
                success=False, output="", error=str(e),
                exit_code=1, tier_used=None,
                security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )

    def _resolve_dag(self, tasks) -> list[list]:
        task_map = {t.task_id: t for t in tasks}
        in_degree = {t.task_id: 0 for t in tasks}
        dependents: dict[str, list] = {t.task_id: [] for t in tasks}

        for task in tasks:
            for dep in task.depends_on:
                if dep in task_map:
                    in_degree[task.task_id] += 1
                    dependents[dep].append(task.task_id)

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        waves = []
        processed = 0

        while queue:
            waves.append([task_map[tid] for tid in queue])
            processed += len(queue)
            next_queue = []
            for tid in queue:
                for dep_tid in dependents[tid]:
                    in_degree[dep_tid] -= 1
                    if in_degree[dep_tid] == 0:
                        next_queue.append(dep_tid)
            queue = next_queue

        if processed < len(tasks):
            raise CyclicDependencyError("Circular dependency detected in task plan")
        return waves

    async def receive_request(
        self,
        user_request: str,
        ctx: "ArchitectExecutionContext | None" = None,
    ) -> "ArchitectExecutionResult":
        """
        Main entry point. Coordinates the full pipeline:
        Planner → DepartmentArchitects → Dispatcher → execute_isolated() → audit → result.
        """
        from core.architect.models import ArchitectExecutionContext, ArchitectExecutionResult

        if ctx is None:
            ctx = ArchitectExecutionContext()

        # Step 1: plan  (AgentTaskPlanner is imported at module level for patchability)
        planner = AgentTaskPlanner()
        plan = planner.plan(user_request, origin="user", parent_request_id=ctx.execution_id)

        # Step 2: enrich context with plan data
        ctx.risk_score = {"low": 10, "medium": 40, "high": 70, "critical": 95}.get(
            plan.risk_level, 10
        )

        # Step 3: orchestrate (uses existing orchestrate() logic)
        orch_result = await self.orchestrate(plan, requestor_id=ctx.user_id)

        # Step 4: log audit event
        self._log_audit_event(ctx, plan, orch_result)

        # Step 5: build rich result
        return self._build_execution_result(ctx, plan, orch_result)

    def _log_audit_event(self, ctx, plan, orch_result) -> None:
        """Write audit event to IsolationAuditLogger. Fail silently."""
        try:
            from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
            logger = IsolationAuditLogger()
            event_id = logger.log_event(
                vm_id=ctx.execution_id,
                event_type="ARCHITECT_ORCHESTRATION",
                severity="INFO" if orch_result.overall_success else "WARNING",
                description=(
                    f"plan={plan.plan_id} tasks={len(plan.subtasks)} "
                    f"success={orch_result.overall_success} risk={plan.risk_level}"
                ),
                metadata={
                    "execution_id": ctx.execution_id,
                    "correlation_id": ctx.correlation_id,
                    "plan_id": plan.plan_id,
                    "task_count": len(plan.subtasks),
                    "failed_count": len(orch_result.failed_tasks),
                    "risk_level": plan.risk_level,
                    "isolation_summary": orch_result.isolation_summary,
                },
                correlation_id=ctx.correlation_id,
                origin_component="architect_core",
            )
            ctx.audit_refs.append(event_id)
        except Exception:
            pass  # audit failure never fails the orchestration

    def _build_execution_result(self, ctx, plan, orch_result) -> "ArchitectExecutionResult":
        """Consolidate OrchestrationResult into ArchitectExecutionResult."""
        from core.architect.models import ArchitectExecutionResult

        outputs = [r.output for r in orch_result.completed_tasks if r.output]
        agents_used = list({r.agent_id for r in orch_result.completed_tasks if r.agent_id != "none"})
        runtimes_used = list({
            r.tier_used.name for r in orch_result.completed_tasks if r.tier_used
        })
        fallback_chain = [
            {
                "task_id": r.task_id,
                "fallback_level": r.fallback_level,
                "security_score": r.security_score,
            }
            for r in orch_result.completed_tasks
            if r.fallback_level > 0
        ]
        security_events = [
            {"task_id": r.task_id, "score": r.security_score, "tier": r.tier_used.name if r.tier_used else "none"}
            for r in orch_result.completed_tasks
        ]
        audit_refs = list(orch_result.audit_chain) + ctx.audit_refs
        scores = [r.security_score for r in orch_result.completed_tasks]
        avg_score = sum(scores) // len(scores) if scores else 0

        error_summary = None
        if not orch_result.overall_success:
            parts = []
            if orch_result.failed_tasks:
                parts.append(f"failed_tasks={orch_result.failed_tasks}")
            if orch_result.human_approval_required:
                parts.append("human_approval_required")
            error_summary = "; ".join(parts) if parts else "unknown_failure"

        return ArchitectExecutionResult(
            execution_id=ctx.execution_id,
            plan_id=plan.plan_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            success=orch_result.overall_success,
            outputs=outputs,
            error_summary=error_summary,
            agents_used=agents_used,
            runtimes_used=runtimes_used,
            fallback_chain=fallback_chain,
            security_events=security_events,
            audit_refs=audit_refs,
            avg_security_score=avg_score,
            execution_time_ms=orch_result.total_duration_ms,
            task_count=len(plan.subtasks),
            failed_task_count=len(orch_result.failed_tasks),
            skipped_task_count=len(orch_result.skipped_tasks),
            repair_attempts=[],
        )

    @staticmethod
    def _build_result(plan, completed, failed_ids, skipped_ids, total_ms, tiers, avg_score):
        from core.architect.models import OrchestrationResult
        return OrchestrationResult(
            plan_id=plan.plan_id, overall_success=len(failed_ids) == 0,
            completed_tasks=completed, failed_tasks=failed_ids, skipped_tasks=skipped_ids,
            total_duration_ms=total_ms,
            isolation_summary={"tiers_used": tiers, "avg_security_score": avg_score},
            audit_chain=[r.execution_id for r in completed],
            human_approval_required=plan.requires_human_approval,
            human_approval_granted=None,
        )


_core_instance: Optional[ArchitectCore] = None
_core_lock = threading.Lock()


def get_architect_core() -> ArchitectCore:
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = ArchitectCore()
    return _core_instance
