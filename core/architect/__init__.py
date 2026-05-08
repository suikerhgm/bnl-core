# core/architect/__init__.py
from .models import (
    AgentTask, TaskPlan, AgentAssignment, DispatchResult,
    OrchestrationResult, RetryPolicy,
    CAPABILITY_MAP, DEPARTMENT_MAP, RISK_TO_POLICY,
    RISK_TO_MIN_TRUST, RISK_TO_MIN_SECURITY_SCORE,
    TASK_TYPE_TO_PERMISSION,
)

def get_architect_core():
    from .architect_core import get_architect_core as _g
    return _g()

__all__ = [
    "get_architect_core",
    "AgentTask", "TaskPlan", "AgentAssignment",
    "DispatchResult", "OrchestrationResult", "RetryPolicy",
]
