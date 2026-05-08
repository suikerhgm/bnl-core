# tests/test_architect/test_models.py
import pytest
from datetime import datetime, timezone
from core.architect.models import (
    AgentTask, TaskPlan, AgentAssignment, DispatchResult,
    OrchestrationResult, RetryPolicy,
    CAPABILITY_MAP, DEPARTMENT_MAP, RISK_TO_POLICY, RISK_TO_MIN_TRUST,
    RISK_TO_MIN_SECURITY_SCORE,
)
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy


def make_task(**kwargs) -> AgentTask:
    defaults = dict(
        task_id="t-001",
        task_type="code_generate",
        description="generate something",
        required_capabilities=["code_generation"],
        required_department="engineering",
        payload={"code": "print('hello')"},
        payload_hash="abc123",
        priority=3,
        risk_level="low",
        depends_on=[],
        minimum_trust_level=30,
        isolation_policy=IsolationPolicy.BEST_AVAILABLE,
        timeout_seconds=30,
        retry_policy=RetryPolicy(),
        expected_output_type="code",
    )
    defaults.update(kwargs)
    return AgentTask(**defaults)


def test_agent_task_creation():
    task = make_task()
    assert task.task_id == "t-001"
    assert task.task_type == "code_generate"
    assert task.risk_level == "low"


def test_retry_policy_defaults():
    policy = RetryPolicy()
    assert policy.max_retries == 0
    assert policy.retry_on_failure is False
    assert policy.escalate_on_final_failure is True


def test_retry_policy_frozen():
    policy = RetryPolicy()
    with pytest.raises(Exception):
        policy.max_retries = 5


def test_task_plan_creation():
    plan = TaskPlan(
        plan_id="p-001",
        parent_request_id=None,
        origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="build something",
        task_type="code_generate",
        complexity="simple",
        risk_level="low",
        ai_reasoning="keyword match",
        subtasks=[make_task()],
        requires_human_approval=False,
        performance_snapshot={},
    )
    assert plan.plan_id == "p-001"
    assert len(plan.subtasks) == 1


def test_dispatch_result_fields():
    result = DispatchResult(
        task_id="t-001",
        plan_id="p-001",
        agent_id="agent-1",
        success=True,
        output="hello",
        error=None,
        exit_code=0,
        tier_used=IsolationTier.PROCESS_JAIL,
        security_score=20,
        fallback_level=0,
        duration_ms=100,
        execution_id="e-001",
        correlation_id="p-001:t-001",
        trace_id="tr-001",
        reputation_delta=0.0,
    )
    assert result.success is True
    assert result.reputation_delta == 0.0


def test_orchestration_result_hooks_empty():
    result = OrchestrationResult(
        plan_id="p-001",
        overall_success=True,
        completed_tasks=[],
        failed_tasks=[],
        skipped_tasks=[],
        total_duration_ms=0,
        isolation_summary={},
        audit_chain=[],
        human_approval_required=False,
        human_approval_granted=None,
        performance_report={},
        recommended_agents=[],
    )
    assert result.performance_report == {}
    assert result.recommended_agents == []


def test_capability_map_covers_all_task_types():
    for task_type in DEPARTMENT_MAP:
        assert task_type in CAPABILITY_MAP, f"{task_type} missing from CAPABILITY_MAP"


def test_risk_to_policy_all_levels():
    for level in ("low", "medium", "high", "critical"):
        assert level in RISK_TO_POLICY
        assert level in RISK_TO_MIN_TRUST
        assert level in RISK_TO_MIN_SECURITY_SCORE


def test_critical_uses_strict_isolation():
    assert RISK_TO_POLICY["critical"] == IsolationPolicy.STRICT_ISOLATION


def test_low_uses_best_available():
    assert RISK_TO_POLICY["low"] == IsolationPolicy.BEST_AVAILABLE


def test_external_agent_onboard_raises():
    import asyncio
    from core.architect.external_agent_integration import ExternalAgentIntegration
    integration = ExternalAgentIntegration()
    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(
            integration.onboard_external_agent({"name": "agent"}, "engineering")
        )
