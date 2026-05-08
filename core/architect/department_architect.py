# core/architect/department_architect.py
"""
DepartmentArchitect — per-department agent selection.
Picks existing eligible agents, hires temporaries when allowed, raises otherwise.
"""
from __future__ import annotations
from typing import Optional

from core.architect.models import AgentAssignment, AgentTask


class NoEligibleAgentError(RuntimeError):
    pass


_NO_TEMP_HIRE_DEPTS = {"security", "runtime"}

_TEMP_AGENT_PERMISSIONS: dict[str, list[str]] = {
    "code_generate":   ["FS_WRITE", "FS_READ"],
    "api_design":      ["FS_WRITE", "FS_READ"],
    "frontend_ui":     ["FS_WRITE", "FS_READ"],
    "data_pipeline":   ["DB_READ", "FS_READ"],
    "test_automation": ["FS_WRITE", "FS_READ"],
    "file_write":      ["FS_WRITE", "FS_READ"],
    "deployment":      ["FS_READ"],
    "security_scan":   ["SB_SCAN"],
    "threat_model":    ["SB_SCAN"],
}


def _agent_attr(agent, key, default=None):
    """
    Retrieve an attribute from an agent that may be a dict (production,
    NexusAgentRegistry returns dicts) or a MagicMock / object (tests).
    """
    if isinstance(agent, dict):
        return agent.get(key, default)
    return getattr(agent, key, default)


class DepartmentArchitect:
    def __init__(self, department: str, registry=None, permission_manager=None) -> None:
        self.department = department
        if registry is None:
            from core.agents.nexus_registry import get_registry
            registry = get_registry()
        if permission_manager is None:
            from core.security.permission_manager import get_permission_manager
            permission_manager = get_permission_manager()
        self._registry = registry
        self._perm = permission_manager

    def assign(self, task: AgentTask, plan_id: str) -> AgentAssignment:
        # Step 1: find eligible existing agents
        cap = task.required_capabilities[0] if task.required_capabilities else None
        candidates = self._registry.find_agents_by_capability(cap) if cap else []
        eligible = [
            a for a in candidates
            if _agent_attr(a, "department") == self.department
            and _agent_attr(a, "trust_level", 0) >= task.minimum_trust_level
            and _agent_attr(a, "status", "inactive") == "active"
        ]

        if eligible:
            agent = eligible[0]
            return AgentAssignment(
                task=task,
                assigned_agent_id=_agent_attr(agent, "agent_id"),
                agent_name=_agent_attr(agent, "name"),
                agent_trust_level=_agent_attr(agent, "trust_level"),
                department=self.department,
                hired_temporary=False,
                contract_id=None,
                assignment_reason="existing_agent",
            )

        # Step 2: hire temporary if allowed
        can_hire = self.department not in _NO_TEMP_HIRE_DEPTS
        if can_hire and task.risk_level in ("low", "medium"):
            import uuid
            temp_name = f"temp-{task.task_type}-{uuid.uuid4().hex[:6]}"
            result = self._registry.hire_temporary_agent(
                name=temp_name,
                role=task.task_type,
                department=self.department,
                capabilities=task.required_capabilities,
                task_description=task.description,
            )
            # hire_temporary_agent returns either a dict {"agent": {...}, "contract": {...}}
            # (production NexusAgentRegistry) or a plain agent_id string (mock in tests).
            if isinstance(result, dict):
                agent_id = result["agent"]["agent_id"]
            else:
                agent_id = result

            for perm_id in _TEMP_AGENT_PERMISSIONS.get(task.task_type, ["FS_READ"]):
                try:
                    self._perm.grant_permission(agent_id, perm_id)
                except Exception:
                    pass
            return AgentAssignment(
                task=task,
                assigned_agent_id=agent_id,
                agent_name=temp_name,
                agent_trust_level=30,
                department=self.department,
                hired_temporary=True,
                contract_id=None,
                assignment_reason="temporary_hired",
            )

        raise NoEligibleAgentError(
            f"dept={self.department} task_type={task.task_type} "
            f"min_trust={task.minimum_trust_level} risk={task.risk_level} "
            f"can_hire_temporary={can_hire}"
        )
