# tests/test_architect/test_agent_dispatcher.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from core.architect.models import (
    AgentTask, AgentAssignment, DispatchResult, RetryPolicy,
    RISK_TO_POLICY, RISK_TO_MIN_TRUST,
)
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionResult, RuntimeLifecycleState,
)
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import NegotiationResult
from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
import hashlib, json


def make_task(risk_level="low", task_type="code_generate") -> AgentTask:
    payload = {"description": "test task", "task_type": task_type}
    return AgentTask(
        task_id="t-001", task_type=task_type, description="test task",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        priority=2, risk_level=risk_level, depends_on=[],
        minimum_trust_level=RISK_TO_MIN_TRUST[risk_level],
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )


def make_assignment(task=None, hired_temporary=False) -> AgentAssignment:
    return AgentAssignment(
        task=task or make_task(),
        assigned_agent_id="agent-forge-01", agent_name="Forge",
        agent_trust_level=70, department="engineering",
        hired_temporary=hired_temporary,
        contract_id="contract-001" if hired_temporary else None,
        assignment_reason="existing_agent",
    )


def make_exec_result(success=True) -> ExecutionResult:
    neg = NegotiationResult(
        requested_tier=IsolationTier.PROCESS_JAIL,
        actual_tier=IsolationTier.PROCESS_JAIL,
        policy=IsolationPolicy.BEST_AVAILABLE,
        reason="exact_match:PROCESS_JAIL", host_os="windows",
        fallback_level=0, fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL],
        security_score=20, risk_adjusted_score=20,
        forensic_support=False, behavioral_support=False,
        candidate_drivers=(IsolationTier.PROCESS_JAIL,),
        rejection_reasons={}, capability_mismatches={}, policy_rejections={},
    )
    return ExecutionResult(
        success=success, output="result output" if success else "",
        error=None if success else "execution failed",
        exit_code=0 if success else 1, runtime_id="r-001",
        tier_used=IsolationTier.PROCESS_JAIL, duration_ms=150,
        negotiation=neg, execution_id="e-001",
        correlation_id="p-001:t-001", trace_id="tr-001",
        runtime_state=RuntimeLifecycleState.DESTROYED,
    )


@pytest.fixture
def dispatcher():
    from core.architect.agent_dispatcher import AgentDispatcher
    runtime = MagicMock()
    runtime.execute_isolated = AsyncMock(return_value=make_exec_result())
    perm = MagicMock()
    perm.has_permission.return_value = True
    perm.get_agent_permissions.return_value = []
    registry = MagicMock()
    registry.terminate_temporary_agent.return_value = True
    return AgentDispatcher(runtime=runtime, permission_manager=perm, registry=registry)


@pytest.mark.asyncio
async def test_dispatch_returns_dispatch_result(dispatcher):
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert isinstance(result, DispatchResult)


@pytest.mark.asyncio
async def test_dispatch_success(dispatcher):
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert result.success is True
    assert result.output == "result output"
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_dispatch_calls_execute_isolated(dispatcher):
    await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    dispatcher._runtime.execute_isolated.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_uses_correct_policy(dispatcher):
    task = make_task(risk_level="high")
    await dispatcher.dispatch(make_assignment(task=task), plan_id="p-001")
    call_kwargs = dispatcher._runtime.execute_isolated.call_args[1]
    assert call_kwargs["policy"] == IsolationPolicy.SAFE_DEGRADATION


@pytest.mark.asyncio
async def test_dispatch_permission_denied(dispatcher):
    dispatcher._perm.has_permission.return_value = False
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert result.success is False
    assert "permission_denied" in result.error


@pytest.mark.asyncio
async def test_dispatch_carries_correlation_id(dispatcher):
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert "p-001" in result.correlation_id
    assert "t-001" in result.correlation_id


@pytest.mark.asyncio
async def test_dispatch_cleans_up_temporary_agent(dispatcher):
    await dispatcher.dispatch(make_assignment(hired_temporary=True), plan_id="p-001")
    dispatcher._registry.terminate_temporary_agent.assert_called_once_with("agent-forge-01")


@pytest.mark.asyncio
async def test_dispatch_does_not_cleanup_permanent_agent(dispatcher):
    await dispatcher.dispatch(make_assignment(hired_temporary=False), plan_id="p-001")
    dispatcher._registry.terminate_temporary_agent.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_output_truncated_if_large(dispatcher):
    big_result = make_exec_result()
    big_result.output = "x" * (600 * 1024)
    dispatcher._runtime.execute_isolated = AsyncMock(return_value=big_result)
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert len(result.output) <= 512 * 1024
