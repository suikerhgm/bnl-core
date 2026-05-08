# tests/test_architect/test_agent_task_planner.py
import pytest
from core.architect.agent_task_planner import AgentTaskPlanner
from core.architect.models import TaskPlan, AgentTask
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy


@pytest.fixture
def planner():
    return AgentTaskPlanner()


def test_plan_returns_task_plan(planner):
    plan = planner.plan("create a simple REST endpoint")
    assert isinstance(plan, TaskPlan)
    assert plan.plan_id is not None
    assert plan.origin == "user"
    assert len(plan.subtasks) >= 1


def test_code_keywords_map_to_engineering(planner):
    plan = planner.plan("build a function to parse JSON")
    task = plan.subtasks[0]
    assert task.required_department == "engineering"
    assert task.task_type == "code_generate"


def test_security_keywords_map_to_security(planner):
    plan = planner.plan("scan this code for security vulnerabilities")
    task = plan.subtasks[0]
    assert task.required_department == "security"
    assert task.task_type == "security_scan"


def test_frontend_keywords_map_to_frontend(planner):
    plan = planner.plan("create a UI component for the dashboard")
    task = plan.subtasks[0]
    assert task.required_department == "frontend"
    assert task.task_type == "frontend_ui"


def test_risk_level_low_by_default(planner):
    plan = planner.plan("generate a utility function")
    assert plan.risk_level == "low"
    assert plan.subtasks[0].isolation_policy == IsolationPolicy.BEST_AVAILABLE


def test_risk_level_medium_for_write_operations(planner):
    plan = planner.plan("delete the temporary files and write new config")
    assert plan.risk_level in ("medium", "high")


def test_critical_risk_requires_approval(planner):
    plan = planner.plan("deploy to production environment now")
    if plan.risk_level == "critical":
        assert plan.requires_human_approval is True


def test_payload_hash_computed(planner):
    plan = planner.plan("create a function")
    task = plan.subtasks[0]
    assert len(task.payload_hash) == 64  # SHA256 hex


def test_task_has_all_required_fields(planner):
    plan = planner.plan("write a data pipeline")
    task = plan.subtasks[0]
    assert task.task_id is not None
    assert task.required_capabilities is not None
    assert task.minimum_trust_level >= 0
    assert task.timeout_seconds > 0


def test_plan_with_parent_request_id(planner):
    plan = planner.plan("refactor the auth module", parent_request_id="p-parent-001")
    assert plan.parent_request_id == "p-parent-001"
