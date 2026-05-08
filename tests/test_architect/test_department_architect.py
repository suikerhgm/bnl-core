# tests/test_architect/test_department_architect.py
import pytest
from unittest.mock import MagicMock
from core.architect.models import AgentTask, AgentAssignment, RetryPolicy, RISK_TO_POLICY, RISK_TO_MIN_TRUST
import hashlib, json


def make_task(risk_level="low", task_type="code_generate", min_trust=None) -> AgentTask:
    payload = {"description": "test", "task_type": task_type}
    return AgentTask(
        task_id="t-001", task_type=task_type, description="test task",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        priority=2, risk_level=risk_level, depends_on=[],
        minimum_trust_level=min_trust if min_trust is not None else RISK_TO_MIN_TRUST[risk_level],
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )


def make_agent(trust_level=70, department="engineering", status="active"):
    return MagicMock(
        agent_id="agent-forge-01", name="Forge",
        trust_level=trust_level, department=department, status=status,
    )


@pytest.fixture
def dept_arch():
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = [make_agent()]
    reg.hire_temporary_agent.return_value = "temp-agent-001"
    perm = MagicMock()
    perm.grant_permission.return_value = True
    return DepartmentArchitect("engineering", registry=reg, permission_manager=perm)


def test_assign_returns_agent_assignment(dept_arch):
    result = dept_arch.assign(make_task(), plan_id="p-001")
    assert isinstance(result, AgentAssignment)


def test_assign_picks_existing_eligible_agent(dept_arch):
    result = dept_arch.assign(make_task(), plan_id="p-001")
    assert result.assigned_agent_id == "agent-forge-01"
    assert result.hired_temporary is False
    assert result.assignment_reason == "existing_agent"


def test_assign_skips_insufficient_trust_agent():
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = [make_agent(trust_level=20)]
    reg.hire_temporary_agent.return_value = "temp-001"
    perm = MagicMock()
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=perm)
    result = dept.assign(make_task(min_trust=70), plan_id="p-001")
    assert result.hired_temporary is True


def test_assign_hires_temporary_when_no_eligible():
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []
    reg.hire_temporary_agent.return_value = "temp-001"
    perm = MagicMock()
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=perm)
    result = dept.assign(make_task(risk_level="low"), plan_id="p-001")
    assert result.hired_temporary is True
    assert result.assigned_agent_id == "temp-001"
    assert result.assignment_reason == "temporary_hired"


def test_assign_security_dept_raises_if_no_agent():
    from core.architect.department_architect import DepartmentArchitect, NoEligibleAgentError
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []
    dept = DepartmentArchitect("security", registry=reg, permission_manager=MagicMock())
    with pytest.raises(NoEligibleAgentError):
        dept.assign(make_task(), plan_id="p-001")


def test_assign_grants_permissions_for_temp_agent():
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []
    reg.hire_temporary_agent.return_value = "temp-001"
    perm = MagicMock()
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=perm)
    dept.assign(make_task(), plan_id="p-001")
    perm.grant_permission.assert_called()


def test_assign_high_risk_no_temp_in_engineering():
    from core.architect.department_architect import DepartmentArchitect, NoEligibleAgentError
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=MagicMock())
    # high risk → no temp hiring allowed
    with pytest.raises(NoEligibleAgentError):
        dept.assign(make_task(risk_level="high"), plan_id="p-001")
