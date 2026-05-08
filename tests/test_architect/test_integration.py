# tests/test_architect/test_integration.py
"""
End-to-end integration: User request -> ArchitectCore -> isolated execution -> result.
Uses mocked registry and runtime to test the full pipeline without external services.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from core.architect.agent_task_planner import AgentTaskPlanner
from core.architect.architect_core import ArchitectCore
from core.architect.agent_dispatcher import AgentDispatcher
from core.architect.department_architect import DepartmentArchitect
from core.architect.models import OrchestrationResult
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionResult, RuntimeLifecycleState,
)
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import NegotiationResult
from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES


def make_negotiation():
    return NegotiationResult(
        requested_tier=IsolationTier.PROCESS_JAIL,
        actual_tier=IsolationTier.PROCESS_JAIL,
        policy=IsolationPolicy.BEST_AVAILABLE,
        reason="exact_match", host_os="windows",
        fallback_level=0, fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL],
        security_score=20, risk_adjusted_score=20,
        forensic_support=False, behavioral_support=False,
        candidate_drivers=(IsolationTier.PROCESS_JAIL,),
        rejection_reasons={}, capability_mismatches={}, policy_rejections={},
    )


def make_execution_result(success=True) -> ExecutionResult:
    return ExecutionResult(
        success=success,
        output="# generated code\ndef hello(): return 'world'" if success else "",
        error=None if success else "execution failed",
        exit_code=0 if success else 1, runtime_id="r-001",
        tier_used=IsolationTier.PROCESS_JAIL, duration_ms=250,
        negotiation=make_negotiation(), execution_id="e-001",
        correlation_id="p-001:t-001", trace_id="tr-001",
        runtime_state=RuntimeLifecycleState.DESTROYED,
    )


@pytest.fixture
def full_pipeline():
    """Full Architect pipeline with mocked external dependencies."""
    mock_agent = MagicMock(
        agent_id="agent-forge-01", name="Forge",
        trust_level=70, department="engineering", status="active",
    )
    mock_registry = MagicMock()
    mock_registry.find_agents_by_capability.return_value = [mock_agent]
    mock_registry.terminate_temporary_agent.return_value = True

    mock_perm = MagicMock()
    mock_perm.has_permission.return_value = True
    mock_perm.get_agent_permissions.return_value = []

    mock_runtime = MagicMock()
    mock_runtime.execute_isolated = AsyncMock(return_value=make_execution_result())

    planner = AgentTaskPlanner()
    dispatcher = AgentDispatcher(
        runtime=mock_runtime, permission_manager=mock_perm, registry=mock_registry,
    )
    dept_arch = DepartmentArchitect(
        department="engineering", registry=mock_registry, permission_manager=mock_perm,
    )
    core = ArchitectCore(
        department_architects={"engineering": dept_arch},
        dispatcher=dispatcher,
    )
    return {"planner": planner, "core": core, "runtime": mock_runtime}


@pytest.mark.asyncio
async def test_end_to_end_create_app(full_pipeline):
    """Full flow: 'create a simple app' -> OrchestrationResult."""
    plan = full_pipeline["planner"].plan("create a simple app")
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-123")
    assert isinstance(result, OrchestrationResult)
    assert result.overall_success is True
    assert len(result.completed_tasks) >= 1
    assert result.failed_tasks == []


@pytest.mark.asyncio
async def test_end_to_end_result_has_forensic_ids(full_pipeline):
    plan = full_pipeline["planner"].plan("build a utility function")
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    assert result.overall_success is True
    for dispatch in result.completed_tasks:
        assert dispatch.execution_id is not None
        assert dispatch.correlation_id is not None
        assert ":" in dispatch.correlation_id


@pytest.mark.asyncio
async def test_end_to_end_execute_isolated_called(full_pipeline):
    plan = full_pipeline["planner"].plan("generate a REST API")
    await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    full_pipeline["runtime"].execute_isolated.assert_called()


@pytest.mark.asyncio
async def test_end_to_end_security_request_fails_gracefully(full_pipeline):
    """Security dept has no agents -> fails gracefully, no exception."""
    plan = full_pipeline["planner"].plan("scan code for security vulnerabilities")
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    assert isinstance(result, OrchestrationResult)


@pytest.mark.asyncio
async def test_end_to_end_dag_two_tasks(full_pipeline):
    """Two tasks with dependency: both complete in order."""
    import hashlib, json, uuid
    from core.architect.models import AgentTask, TaskPlan, RetryPolicy, RISK_TO_POLICY, RISK_TO_MIN_TRUST

    payload = {"description": "test"}
    phash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    t1 = AgentTask(
        task_id="t-a", task_type="code_generate", description="step 1",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload, payload_hash=phash, priority=2, risk_level="low", depends_on=[],
        minimum_trust_level=30, isolation_policy=RISK_TO_POLICY["low"],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )
    t2 = AgentTask(
        task_id="t-b", task_type="code_generate", description="step 2",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload, payload_hash=phash, priority=2, risk_level="low", depends_on=["t-a"],
        minimum_trust_level=30, isolation_policy=RISK_TO_POLICY["low"],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )
    plan = TaskPlan(
        plan_id=str(uuid.uuid4()), parent_request_id=None, origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="two step task", task_type="code_generate",
        complexity="moderate", risk_level="low", ai_reasoning="test",
        subtasks=[t1, t2], requires_human_approval=False,
    )
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    assert result.overall_success is True
    assert len(result.completed_tasks) == 2


@pytest.mark.asyncio
async def test_end_to_end_critical_plan_requires_approval(full_pipeline):
    """Critical plans are blocked without human approval."""
    plan = full_pipeline["planner"].plan("deploy to production now")
    if plan.requires_human_approval:
        result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
        assert result.human_approval_required is True
        assert result.overall_success is False
