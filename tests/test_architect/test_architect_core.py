# tests/test_architect/test_architect_core.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from core.architect.models import (
    AgentTask, TaskPlan, AgentAssignment, DispatchResult, RetryPolicy,
    RISK_TO_POLICY, RISK_TO_MIN_TRUST,
)
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
import hashlib, json, uuid as _uuid


def make_task(task_id="t-001", depends_on=None, risk_level="low") -> AgentTask:
    payload = {"description": "test"}
    return AgentTask(
        task_id=task_id, task_type="code_generate", description="test",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        priority=2, risk_level=risk_level, depends_on=depends_on or [],
        minimum_trust_level=RISK_TO_MIN_TRUST[risk_level],
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )


def make_plan(tasks=None, risk_level="low", requires_approval=False) -> TaskPlan:
    return TaskPlan(
        plan_id="p-001", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="test request", task_type="code_generate",
        complexity="simple", risk_level=risk_level,
        ai_reasoning="keyword_match",
        subtasks=tasks or [make_task()],
        requires_human_approval=requires_approval,
    )


def make_dispatch_result(task_id="t-001", success=True) -> DispatchResult:
    return DispatchResult(
        task_id=task_id, plan_id="p-001", agent_id="a-001",
        success=success, output="ok", error=None, exit_code=0,
        tier_used=IsolationTier.PROCESS_JAIL,
        security_score=20, fallback_level=0, duration_ms=100,
        execution_id="e-001", correlation_id=f"p-001:{task_id}", trace_id=None,
    )


def make_assignment(task) -> AgentAssignment:
    return AgentAssignment(
        task=task, assigned_agent_id="a-001", agent_name="Agent",
        agent_trust_level=70, department="engineering",
        hired_temporary=False, contract_id=None, assignment_reason="existing_agent",
    )


@pytest.fixture
def core():
    from core.architect.architect_core import ArchitectCore
    mock_dept = MagicMock()
    mock_dept.assign.side_effect = lambda task, plan_id: make_assignment(task)
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch_with_retry = AsyncMock(
        side_effect=lambda assignment, plan_id: make_dispatch_result(assignment.task.task_id)
    )
    return ArchitectCore(
        department_architects={"engineering": mock_dept},
        dispatcher=mock_dispatcher,
    )


@pytest.mark.asyncio
async def test_orchestrate_returns_result(core):
    from core.architect.models import OrchestrationResult
    result = await core.orchestrate(make_plan(), requestor_id="user-1")
    assert isinstance(result, OrchestrationResult)


@pytest.mark.asyncio
async def test_orchestrate_single_task_success(core):
    result = await core.orchestrate(make_plan(), requestor_id="user-1")
    assert result.overall_success is True
    assert len(result.completed_tasks) == 1
    assert result.failed_tasks == []


@pytest.mark.asyncio
async def test_orchestrate_requires_approval_blocks(core):
    result = await core.orchestrate(make_plan(requires_approval=True), requestor_id="u")
    assert result.human_approval_required is True
    assert result.overall_success is False


@pytest.mark.asyncio
async def test_orchestrate_respects_dag_order():
    from core.architect.architect_core import ArchitectCore
    call_order = []

    async def track(assignment, plan_id):
        call_order.append(assignment.task.task_id)
        return make_dispatch_result(assignment.task.task_id)

    task_a = make_task(task_id="t-a", depends_on=[])
    task_b = make_task(task_id="t-b", depends_on=["t-a"])

    mock_dept = MagicMock()
    mock_dept.assign.side_effect = lambda task, plan_id: make_assignment(task)
    mock_disp = MagicMock()
    mock_disp.dispatch_with_retry = track

    arch = ArchitectCore(department_architects={"engineering": mock_dept}, dispatcher=mock_disp)
    await arch.orchestrate(make_plan(tasks=[task_a, task_b]), requestor_id="u")
    assert call_order.index("t-a") < call_order.index("t-b")


@pytest.mark.asyncio
async def test_orchestrate_skips_dependents_on_failure():
    from core.architect.architect_core import ArchitectCore

    async def fail_a(assignment, plan_id):
        if assignment.task.task_id == "t-a":
            return make_dispatch_result("t-a", success=False)
        return make_dispatch_result(assignment.task.task_id)

    task_a = make_task(task_id="t-a")
    task_b = make_task(task_id="t-b", depends_on=["t-a"])

    mock_dept = MagicMock()
    mock_dept.assign.side_effect = lambda task, plan_id: make_assignment(task)
    mock_disp = MagicMock()
    mock_disp.dispatch_with_retry = fail_a

    arch = ArchitectCore(department_architects={"engineering": mock_dept}, dispatcher=mock_disp)
    result = await arch.orchestrate(make_plan(tasks=[task_a, task_b], risk_level="low"), requestor_id="u")
    assert "t-b" in result.skipped_tasks


def test_resolve_dag_linear():
    from core.architect.architect_core import ArchitectCore
    arch = ArchitectCore.__new__(ArchitectCore)
    t1 = make_task(task_id="t1")
    t2 = make_task(task_id="t2", depends_on=["t1"])
    t3 = make_task(task_id="t3", depends_on=["t2"])
    waves = arch._resolve_dag([t1, t2, t3])
    assert len(waves) == 3
    assert waves[0][0].task_id == "t1"
    assert waves[2][0].task_id == "t3"


def test_resolve_dag_raises_on_cycle():
    from core.architect.architect_core import ArchitectCore, CyclicDependencyError
    arch = ArchitectCore.__new__(ArchitectCore)
    t1 = make_task(task_id="t1", depends_on=["t2"])
    t2 = make_task(task_id="t2", depends_on=["t1"])
    with pytest.raises(CyclicDependencyError):
        arch._resolve_dag([t1, t2])


def test_get_architect_core_singleton():
    from core.architect.architect_core import get_architect_core
    c1 = get_architect_core()
    c2 = get_architect_core()
    assert c1 is c2
