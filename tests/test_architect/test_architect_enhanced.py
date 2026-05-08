# tests/test_architect/test_architect_enhanced.py
"""
Enhanced ArchitectCore tests: receive_request(), ArchitectExecutionContext,
ArchitectExecutionResult, audit integration, correlation propagation.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from core.architect.models import (
    ArchitectExecutionContext, ArchitectExecutionResult,
    AgentTask, TaskPlan, AgentAssignment, DispatchResult, OrchestrationResult,
    RetryPolicy, RISK_TO_POLICY, RISK_TO_MIN_TRUST,
)
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import NegotiationResult
from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
import hashlib, json, uuid


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_task(task_id="t-001", risk_level="low", depends_on=None) -> AgentTask:
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


def make_dispatch_result(task_id="t-001", success=True) -> DispatchResult:
    return DispatchResult(
        task_id=task_id, plan_id="p-001", agent_id="agent-forge-01",
        success=success, output="generated code" if success else "",
        error=None if success else "exec failed",
        exit_code=0 if success else 1,
        tier_used=IsolationTier.PROCESS_JAIL,
        security_score=20, fallback_level=0, duration_ms=150,
        execution_id=str(uuid.uuid4()),
        correlation_id=f"p-001:{task_id}", trace_id=str(uuid.uuid4()),
    )


def make_orch_result(tasks=None, success=True) -> OrchestrationResult:
    tasks = tasks or [make_task()]
    completed = [make_dispatch_result(t.task_id, success) for t in tasks]
    return OrchestrationResult(
        plan_id="p-001",
        overall_success=success,
        completed_tasks=completed,
        failed_tasks=[] if success else [t.task_id for t in tasks],
        skipped_tasks=[],
        total_duration_ms=200,
        isolation_summary={"tiers_used": ["PROCESS_JAIL"], "avg_security_score": 20},
        audit_chain=[r.execution_id for r in completed],
        human_approval_required=False,
        human_approval_granted=None,
    )


@pytest.fixture
def core_with_mock_planner_and_orchestrate():
    """ArchitectCore with mocked planner + orchestrate()."""
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-test", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="create a simple app",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    core = ArchitectCore.__new__(ArchitectCore)
    core._depts = {}
    core._dispatcher = MagicMock()

    # Patch orchestrate to return mocked OrchestrationResult
    async def mock_orchestrate(plan_arg, requestor_id=None):
        return make_orch_result([make_task()])

    core.orchestrate = mock_orchestrate

    # Patch planner inside receive_request
    mock_planner_instance = MagicMock()
    mock_planner_instance.plan.return_value = plan

    return core, mock_planner_instance, plan


# ── ArchitectExecutionContext tests ──────────────────────────────────────────

def test_exec_ctx_auto_generates_ids():
    ctx = ArchitectExecutionContext()
    assert len(ctx.execution_id) == 36    # UUID
    assert len(ctx.correlation_id) == 36
    assert len(ctx.trace_id) == 36


def test_exec_ctx_ids_are_unique():
    ctx1 = ArchitectExecutionContext()
    ctx2 = ArchitectExecutionContext()
    assert ctx1.execution_id != ctx2.execution_id
    assert ctx1.correlation_id != ctx2.correlation_id


def test_exec_ctx_defaults():
    ctx = ArchitectExecutionContext()
    assert ctx.user_id == "anonymous"
    assert ctx.trust_level == 50
    assert ctx.risk_score == 0
    assert ctx.requested_capabilities == []
    assert ctx.audit_refs == []
    assert ctx.isolation_policy is None
    assert ctx.parent_execution_id is None


def test_exec_ctx_custom_user():
    ctx = ArchitectExecutionContext(user_id="user-123", trust_level=80)
    assert ctx.user_id == "user-123"
    assert ctx.trust_level == 80


def test_exec_ctx_created_at_is_utc():
    ctx = ArchitectExecutionContext()
    assert ctx.created_at.tzinfo is not None


def test_exec_ctx_nested_orchestration():
    parent_ctx = ArchitectExecutionContext()
    child_ctx = ArchitectExecutionContext(parent_execution_id=parent_ctx.execution_id)
    assert child_ctx.parent_execution_id == parent_ctx.execution_id


# ── ArchitectExecutionResult tests ──────────────────────────────────────────

def make_exec_result(**kwargs) -> ArchitectExecutionResult:
    defaults = dict(
        execution_id=str(uuid.uuid4()),
        plan_id="p-001",
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        success=True,
        outputs=["code output"],
        error_summary=None,
        agents_used=["agent-forge-01"],
        runtimes_used=["PROCESS_JAIL"],
        fallback_chain=[],
        security_events=[{"task_id": "t-001", "score": 20, "tier": "PROCESS_JAIL"}],
        audit_refs=["e-001"],
        avg_security_score=20,
        execution_time_ms=200,
        task_count=1,
        failed_task_count=0,
        skipped_task_count=0,
    )
    defaults.update(kwargs)
    return ArchitectExecutionResult(**defaults)


def test_exec_result_success():
    r = make_exec_result(success=True)
    assert r.success is True
    assert r.error_summary is None


def test_exec_result_failure_has_summary():
    r = make_exec_result(success=False, error_summary="failed_tasks=['t-001']")
    assert r.success is False
    assert r.error_summary is not None


def test_exec_result_repair_attempts_empty_by_default():
    r = make_exec_result()
    assert r.repair_attempts == []


def test_exec_result_has_all_forensic_fields():
    r = make_exec_result()
    assert r.execution_id is not None
    assert r.correlation_id is not None
    assert r.trace_id is not None
    assert isinstance(r.audit_refs, list)


def test_exec_result_fallback_chain_structure():
    fallback = [{"task_id": "t-001", "fallback_level": 2, "security_score": 40}]
    r = make_exec_result(fallback_chain=fallback)
    assert r.fallback_chain[0]["fallback_level"] == 2


def test_exec_result_security_events_structure():
    events = [{"task_id": "t-001", "score": 70, "tier": "DOCKER_HARDENED"}]
    r = make_exec_result(security_events=events)
    assert r.security_events[0]["score"] == 70


# ── receive_request() tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_request_returns_exec_result():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-test", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="build a function",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate(plan_arg, requestor_id=None):
        return make_orch_result([make_task()])

    mock_dept = MagicMock()
    mock_dept.assign.return_value = AgentAssignment(
        task=make_task(), assigned_agent_id="a-1", agent_name="A",
        agent_trust_level=70, department="engineering",
        hired_temporary=False, contract_id=None, assignment_reason="existing_agent",
    )
    core = ArchitectCore(
        department_architects={"engineering": mock_dept},
        dispatcher=MagicMock(),
    )
    core.orchestrate = mock_orchestrate

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("build a function")

    assert isinstance(result, ArchitectExecutionResult)
    assert result.success is True


@pytest.mark.asyncio
async def test_receive_request_auto_generates_ctx():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-auto", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="write code",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate(p, requestor_id=None):
        return make_orch_result([make_task()])

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("write code")

    assert result.execution_id is not None
    assert result.correlation_id is not None
    assert result.trace_id is not None


@pytest.mark.asyncio
async def test_receive_request_accepts_existing_ctx():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-ctx", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="run task",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate(p, requestor_id=None):
        return make_orch_result([make_task()])

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate

    ctx = ArchitectExecutionContext(user_id="user-999", correlation_id="my-corr-id")

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("run task", ctx=ctx)

    assert result.correlation_id == "my-corr-id"


@pytest.mark.asyncio
async def test_receive_request_failure_sets_error_summary():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-fail", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="do something",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate_fail(p, requestor_id=None):
        return make_orch_result([make_task()], success=False)

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate_fail

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("do something")

    assert result.success is False
    assert result.error_summary is not None


@pytest.mark.asyncio
async def test_receive_request_populates_agents_used():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-agents", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="build utility",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate(p, requestor_id=None):
        return make_orch_result([make_task()])

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("build utility")

    assert "agent-forge-01" in result.agents_used
    assert len(result.runtimes_used) > 0


@pytest.mark.asyncio
async def test_receive_request_risk_score_set_for_low():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-risk", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="simple task",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    captured_ctx = {}

    async def mock_orchestrate(p, requestor_id=None):
        return make_orch_result([make_task()])

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate

    original_build = core._build_execution_result
    def capture_build(ctx, p, o):
        captured_ctx["risk_score"] = ctx.risk_score
        return original_build(ctx, p, o)
    core._build_execution_result = capture_build

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        await core.receive_request("simple task")

    assert captured_ctx["risk_score"] == 10  # low → 10


@pytest.mark.asyncio
async def test_receive_request_audit_refs_populated():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    plan = TaskPlan(
        plan_id="p-audit", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="audit test",
        task_type="code_generate", complexity="simple", risk_level="low",
        ai_reasoning="keyword_match", subtasks=[make_task()],
        requires_human_approval=False,
    )

    async def mock_orchestrate(p, requestor_id=None):
        return make_orch_result([make_task()])

    core = ArchitectCore(department_architects={}, dispatcher=MagicMock())
    core.orchestrate = mock_orchestrate

    with patch("core.architect.architect_core.AgentTaskPlanner") as MockPlanner:
        MockPlanner.return_value.plan.return_value = plan
        result = await core.receive_request("audit test")

    # audit_refs comes from completed_tasks execution_ids + any logged events
    assert isinstance(result.audit_refs, list)


# ── _build_execution_result tests ─────────────────────────────────────────────

def test_build_execution_result_success():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    core = ArchitectCore.__new__(ArchitectCore)
    ctx = ArchitectExecutionContext(user_id="u1")
    plan = TaskPlan(
        plan_id="p-build", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="x", task_type="code_generate",
        complexity="simple", risk_level="low", ai_reasoning="x",
        subtasks=[make_task()], requires_human_approval=False,
    )
    orch = make_orch_result([make_task()])
    result = core._build_execution_result(ctx, plan, orch)

    assert isinstance(result, ArchitectExecutionResult)
    assert result.success is True
    assert result.error_summary is None
    assert result.task_count == 1
    assert result.failed_task_count == 0


def test_build_execution_result_failure_has_error_summary():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    core = ArchitectCore.__new__(ArchitectCore)
    ctx = ArchitectExecutionContext()
    plan = TaskPlan(
        plan_id="p-f", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="x", task_type="code_generate",
        complexity="simple", risk_level="low", ai_reasoning="x",
        subtasks=[make_task()], requires_human_approval=False,
    )
    orch = make_orch_result([make_task()], success=False)
    result = core._build_execution_result(ctx, plan, orch)

    assert result.success is False
    assert result.error_summary is not None


def test_build_execution_result_collects_outputs():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    core = ArchitectCore.__new__(ArchitectCore)
    ctx = ArchitectExecutionContext()
    plan = TaskPlan(
        plan_id="p-out", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="x", task_type="code_generate",
        complexity="simple", risk_level="low", ai_reasoning="x",
        subtasks=[make_task("t-1"), make_task("t-2")],
        requires_human_approval=False,
    )
    orch = make_orch_result([make_task("t-1"), make_task("t-2")])
    result = core._build_execution_result(ctx, plan, orch)

    assert len(result.outputs) == 2  # one per completed task with output


def test_build_execution_result_fallback_chain_populated():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    core = ArchitectCore.__new__(ArchitectCore)
    ctx = ArchitectExecutionContext()

    # Create a task result with fallback (fallback_level > 0)
    dr = make_dispatch_result("t-001")
    object.__setattr__(dr, "fallback_level", 2)  # simulate degradation
    object.__setattr__(dr, "output", "degraded output")

    orch = OrchestrationResult(
        plan_id="p-fb", overall_success=True,
        completed_tasks=[dr], failed_tasks=[], skipped_tasks=[],
        total_duration_ms=100,
        isolation_summary={"tiers_used": ["SANDBOX"], "avg_security_score": 40},
        audit_chain=[dr.execution_id],
        human_approval_required=False, human_approval_granted=None,
    )
    plan = TaskPlan(
        plan_id="p-fb", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="x", task_type="code_generate",
        complexity="simple", risk_level="low", ai_reasoning="x",
        subtasks=[make_task()], requires_human_approval=False,
    )
    result = core._build_execution_result(ctx, plan, orch)

    assert len(result.fallback_chain) == 1
    assert result.fallback_chain[0]["fallback_level"] == 2


def test_build_approval_required_sets_error():
    from core.architect.architect_core import ArchitectCore
    from core.architect.models import TaskPlan

    core = ArchitectCore.__new__(ArchitectCore)
    ctx = ArchitectExecutionContext()
    plan = TaskPlan(
        plan_id="p-appr", parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="deploy to prod", task_type="deployment",
        complexity="complex", risk_level="critical", ai_reasoning="keyword_match",
        subtasks=[make_task(risk_level="critical")],
        requires_human_approval=True,
    )
    orch = OrchestrationResult(
        plan_id="p-appr", overall_success=False,
        completed_tasks=[], failed_tasks=["t-001"], skipped_tasks=[],
        total_duration_ms=0, isolation_summary={}, audit_chain=[],
        human_approval_required=True, human_approval_granted=None,
    )
    result = core._build_execution_result(ctx, plan, orch)

    assert result.success is False
    assert "human_approval_required" in (result.error_summary or "")
