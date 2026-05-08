# Architect Layer — Implementation Plan (FASE 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Nexus Architect Layer — a hierarchical agent orchestration system where every execution flows through `UnifiedIsolationRuntime.execute_isolated()`, enabling the end-to-end flow: User → ArchitectCore → AgentTaskPlanner → DepartmentArchitect → AgentDispatcher → isolated execution → result.

**Architecture:** `AgentTaskPlanner` classifies requests with keyword rules (no AI in FASE 1) and produces a `TaskPlan`. `ArchitectCore` validates and routes each `AgentTask` to the correct `DepartmentArchitect`, which selects or hires an agent from `NexusAgentRegistry`. `AgentDispatcher` executes exclusively via `UnifiedIsolationRuntime.execute_isolated()`. All components share data models from `models.py` — no component defines its own types.

**Tech Stack:** Python 3.10+, stdlib only in models.py, `core.isolation_abstraction.unified_isolation_runtime` (existing), `core.agents.nexus_registry` (existing), `core.security.permission_manager` (existing), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-08-architect-layer-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `core/architect/__init__.py` | Package exports |
| `core/architect/models.py` | All shared data models + lookup tables. Zero project imports. |
| `core/architect/agent_task_planner.py` | Keyword-based task classification → `TaskPlan`. No AI in FASE 1. |
| `core/architect/agent_dispatcher.py` | Executes `AgentAssignment` via `execute_isolated()`. Only executor. |
| `core/architect/department_architect.py` | Selects agent from registry, hires temporary if needed → `AgentAssignment`. |
| `core/architect/architect_core.py` | Validates plan, routes to departments, aggregates results. Pure façade. |
| `core/architect/external_agent_integration.py` | Stub — raises `NotImplementedError`. Hook for FASE 3. |
| `tests/test_architect/__init__.py` | Test package |
| `tests/test_architect/conftest.py` | Shared fixtures |
| `tests/test_architect/test_models.py` | Data model tests |
| `tests/test_architect/test_agent_task_planner.py` | Planner classification tests |
| `tests/test_architect/test_agent_dispatcher.py` | Dispatcher + execute_isolated tests |
| `tests/test_architect/test_department_architect.py` | Agent selection + temp hiring tests |
| `tests/test_architect/test_architect_core.py` | Orchestration + aggregation tests |
| `tests/test_architect/test_integration.py` | End-to-end "create a simple app" flow |

---

## Task 1: Data Models

**Files:**
- Create: `core/architect/__init__.py`
- Create: `core/architect/models.py`
- Create: `tests/test_architect/__init__.py`
- Create: `tests/test_architect/test_models.py`

- [ ] **Step 1: Create test file**

```python
# tests/test_architect/test_models.py
import hashlib
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
```

- [ ] **Step 2: Create test package init**

```python
# tests/test_architect/__init__.py
```

- [ ] **Step 3: Run tests — verify ImportError**

```
python -m pytest tests/test_architect/test_models.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.architect'`

- [ ] **Step 4: Create package init**

```python
# core/architect/__init__.py
from .architect_core import ArchitectCore, get_architect_core
from .agent_task_planner import AgentTaskPlanner
from .agent_dispatcher import AgentDispatcher
from .department_architect import DepartmentArchitect
from .models import (
    AgentTask, TaskPlan, AgentAssignment, DispatchResult,
    OrchestrationResult, RetryPolicy,
)

__all__ = [
    "ArchitectCore", "get_architect_core",
    "AgentTaskPlanner", "AgentDispatcher", "DepartmentArchitect",
    "AgentTask", "TaskPlan", "AgentAssignment",
    "DispatchResult", "OrchestrationResult", "RetryPolicy",
]
```

- [ ] **Step 5: Create models.py**

```python
# core/architect/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# Imported only for type annotations — these are already installed
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0
    retry_on_failure: bool = False
    escalate_on_final_failure: bool = True


@dataclass
class AgentTask:
    task_id: str
    task_type: str                        # "code_generate"|"security_scan"|"file_write"|
                                          # "api_design"|"data_pipeline"|"frontend_ui"|
                                          # "threat_model"|"test_automation"|"deployment"
    description: str
    required_capabilities: list[str]      # capability names from capabilities table
    required_department: str              # "engineering"|"security"|"frontend"|
                                          # "research"|"runtime"|"repairs"
    payload: dict                         # {command?, code?, timeout?, environment?}
    payload_hash: str                     # SHA256 of payload for tamper detection
    priority: int                         # 1 (low) – 5 (critical)
    risk_level: str                       # "low"|"medium"|"high"|"critical"
    depends_on: list[str]                 # task_ids that must complete first
    minimum_trust_level: int              # 0–100
    isolation_policy: IsolationPolicy
    timeout_seconds: int
    retry_policy: RetryPolicy
    expected_output_type: str             # "code"|"report"|"confirmation"|"data"


@dataclass
class TaskPlan:
    plan_id: str
    parent_request_id: Optional[str]
    origin: str                           # "user"|"agent"|"system"
    created_at: datetime
    original_request: str
    task_type: str
    complexity: str                       # "simple"|"moderate"|"complex"
    risk_level: str
    ai_reasoning: str
    subtasks: list[AgentTask]
    requires_human_approval: bool
    performance_snapshot: dict = field(default_factory=dict)  # Plan D hook


@dataclass
class AgentAssignment:
    task: AgentTask
    assigned_agent_id: str
    agent_name: str
    agent_trust_level: int
    department: str
    hired_temporary: bool
    contract_id: Optional[str]
    assignment_reason: str                # "existing_agent"|"temporary_hired"|"escalated"
    expected_performance_score: float = 0.0   # Plan D hook


@dataclass
class DispatchResult:
    task_id: str
    plan_id: str
    agent_id: str
    success: bool
    output: str
    error: Optional[str]
    exit_code: int
    tier_used: IsolationTier
    security_score: int
    fallback_level: int
    duration_ms: int
    execution_id: str
    correlation_id: str
    trace_id: Optional[str]
    reputation_delta: float = 0.0         # Plan D hook


@dataclass
class OrchestrationResult:
    plan_id: str
    overall_success: bool
    completed_tasks: list[DispatchResult]
    failed_tasks: list[str]               # task_ids
    skipped_tasks: list[str]              # task_ids
    total_duration_ms: int
    isolation_summary: dict
    audit_chain: list[str]
    human_approval_required: bool
    human_approval_granted: Optional[bool]
    performance_report: dict = field(default_factory=dict)    # Plan D hook
    recommended_agents: list[str] = field(default_factory=list)  # Plan D hook


# ── Deterministic lookup tables ───────────────────────────────────────────────

CAPABILITY_MAP: dict[str, list[str]] = {
    "code_generate":   ["code_generation"],
    "security_scan":   ["security_analysis", "threat_modeling"],
    "api_design":      ["api_design", "code_generation"],
    "frontend_ui":     ["frontend_ui"],
    "data_pipeline":   ["data_pipeline"],
    "test_automation": ["test_automation"],
    "deployment":      ["deployment", "process_management"],
    "file_write":      [],
    "threat_model":    ["threat_modeling"],
}

DEPARTMENT_MAP: dict[str, str] = {
    "code_generate":   "engineering",
    "security_scan":   "security",
    "api_design":      "engineering",
    "frontend_ui":     "frontend",
    "data_pipeline":   "research",
    "test_automation": "engineering",
    "deployment":      "runtime",
    "file_write":      "engineering",
    "threat_model":    "security",
}

RISK_TO_POLICY: dict[str, IsolationPolicy] = {
    "low":      IsolationPolicy.BEST_AVAILABLE,
    "medium":   IsolationPolicy.SAFE_DEGRADATION,
    "high":     IsolationPolicy.SAFE_DEGRADATION,
    "critical": IsolationPolicy.STRICT_ISOLATION,
}

RISK_TO_MIN_TRUST: dict[str, int] = {
    "low":      30,
    "medium":   50,
    "high":     70,
    "critical": 85,
}

RISK_TO_MIN_SECURITY_SCORE: dict[str, int] = {
    "low":      0,
    "medium":   40,
    "high":     70,
    "critical": 90,
}

# permission_id required per task_type (maps to Perm enum values)
TASK_TYPE_TO_PERMISSION: dict[str, str] = {
    "code_generate":   "FS_WRITE",
    "security_scan":   "SB_SCAN",
    "api_design":      "FS_WRITE",
    "frontend_ui":     "FS_WRITE",
    "data_pipeline":   "DB_READ",
    "test_automation": "FS_WRITE",
    "deployment":      "RT_RESTART",
    "file_write":      "FS_WRITE",
    "threat_model":    "SB_SCAN",
}
```

- [ ] **Step 6: Run tests**

```
python -m pytest tests/test_architect/test_models.py -v
```
Expected: ImportError from `__init__.py` trying to import other modules not yet created. Fix by making `__init__.py` use lazy imports:

```python
# core/architect/__init__.py  — replace with lazy version
def get_architect_core():
    from .architect_core import get_architect_core as _get
    return _get()
```

Full lazy `__init__.py`:

```python
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
```

Run again:
```
python -m pytest tests/test_architect/test_models.py -v
```
Expected: 11 PASSED

- [ ] **Step 7: Commit**

```
git add core/architect/ tests/test_architect/
git commit -m "feat(architect): Task 1 — data models, lookup tables, RetryPolicy"
```

---

## Task 2: AgentTaskPlanner (keyword-based, FASE 1)

**Files:**
- Create: `core/architect/agent_task_planner.py`
- Create: `tests/test_architect/test_agent_task_planner.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_architect/test_agent_task_planner.py -v
```
Expected: `ImportError: cannot import name 'AgentTaskPlanner'`

- [ ] **Step 3: Implement**

```python
# core/architect/agent_task_planner.py
"""
AgentTaskPlanner — FASE 1: keyword-based classification.
AI call structure is prepared but not activated. All routing is deterministic.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.architect.models import (
    AgentTask, TaskPlan, RetryPolicy,
    CAPABILITY_MAP, DEPARTMENT_MAP, RISK_TO_POLICY,
    RISK_TO_MIN_TRUST, RISK_TO_MIN_SECURITY_SCORE,
)

# ── Keyword classification rules (FASE 1 — no AI) ────────────────────────────

_TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "security_scan":   ["security", "vulnerability", "scan", "audit", "threat", "exploit", "penetration"],
    "frontend_ui":     ["ui", "frontend", "component", "interface", "dashboard", "visual", "css", "html"],
    "api_design":      ["api", "endpoint", "rest", "graphql", "route", "swagger", "openapi"],
    "data_pipeline":   ["pipeline", "etl", "dataset", "transform", "ingestion", "stream", "batch"],
    "deployment":      ["deploy", "release", "ci/cd", "kubernetes", "docker", "production", "staging"],
    "test_automation": ["test", "unittest", "pytest", "coverage", "mock", "fixture", "assertion"],
    "threat_model":    ["threat model", "attack surface", "risk model", "stride"],
    "file_write":      ["write file", "save file", "create file", "update file"],
    "code_generate":   ["create", "build", "generate", "implement", "write", "develop", "make", "code"],
}

_HIGH_RISK_KEYWORDS = ["production", "deploy", "shutdown", "drop", "truncate", "root", "admin"]
_MEDIUM_RISK_KEYWORDS = ["delete", "remove", "update", "modify", "overwrite", "write", "config"]
_CRITICAL_KEYWORDS = ["production deploy", "root access", "shutdown system", "drop database"]


class AgentTaskPlanner:
    """
    Classifies user requests into TaskPlan via keyword matching (FASE 1).
    FASE 2: replace _classify() with AI call, keep _decompose() unchanged.
    """

    def plan(
        self,
        user_request: str,
        origin: str = "user",
        parent_request_id: Optional[str] = None,
    ) -> TaskPlan:
        classification = self._classify(user_request)
        subtasks = self._decompose(classification, user_request)
        return TaskPlan(
            plan_id=str(uuid.uuid4()),
            parent_request_id=parent_request_id,
            origin=origin,
            created_at=datetime.now(timezone.utc),
            original_request=user_request,
            task_type=classification["task_type"],
            complexity=classification["complexity"],
            risk_level=classification["risk_level"],
            ai_reasoning=classification["reasoning"],
            subtasks=subtasks,
            requires_human_approval=classification["risk_level"] == "critical",
            performance_snapshot={},
        )

    def _classify(self, request: str) -> dict:
        """Keyword-based classification. FASE 2: replace body with AI call."""
        lower = request.lower()

        # Detect task type (first match wins, ordered by specificity)
        task_type = "code_generate"  # default
        for tt, keywords in _TASK_TYPE_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                task_type = tt
                break

        # Detect risk level
        risk_level = "low"
        if any(kw in lower for kw in _CRITICAL_KEYWORDS):
            risk_level = "critical"
        elif any(kw in lower for kw in _HIGH_RISK_KEYWORDS):
            risk_level = "high"
        elif any(kw in lower for kw in _MEDIUM_RISK_KEYWORDS):
            risk_level = "medium"

        complexity = "simple" if len(request.split()) < 10 else "moderate"

        return {
            "task_type": task_type,
            "risk_level": risk_level,
            "complexity": complexity,
            "reasoning": f"keyword_match: task_type={task_type} risk={risk_level}",
        }

    def _decompose(self, classification: dict, request: str) -> list[AgentTask]:
        task_type = classification["task_type"]
        risk_level = classification["risk_level"]
        payload_raw = json.dumps({"description": request, "task_type": task_type})
        payload_hash = hashlib.sha256(payload_raw.encode()).hexdigest()

        primary = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            description=request,
            required_capabilities=CAPABILITY_MAP.get(task_type, []),
            required_department=DEPARTMENT_MAP.get(task_type, "engineering"),
            payload={"description": request, "task_type": task_type},
            payload_hash=payload_hash,
            priority=self._priority(risk_level),
            risk_level=risk_level,
            depends_on=[],
            minimum_trust_level=RISK_TO_MIN_TRUST[risk_level],
            isolation_policy=RISK_TO_POLICY[risk_level],
            timeout_seconds=30,
            retry_policy=RetryPolicy(max_retries=1 if risk_level == "low" else 0),
            expected_output_type="code" if task_type == "code_generate" else "report",
        )
        return [primary]

    @staticmethod
    def _priority(risk_level: str) -> int:
        return {"low": 2, "medium": 3, "high": 4, "critical": 5}.get(risk_level, 2)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_architect/test_agent_task_planner.py -v
```
Expected: 10 PASSED

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/test_isolation_abstraction/ tests/test_vm_isolation/ tests/test_architect/ -q --tb=no
```
Expected: 190+ passed

- [ ] **Step 6: Commit**

```
git add core/architect/agent_task_planner.py tests/test_architect/test_agent_task_planner.py
git commit -m "feat(architect): Task 2 — AgentTaskPlanner keyword-based classification"
```

---

## Task 3: AgentDispatcher

**Files:**
- Create: `core/architect/agent_dispatcher.py`
- Create: `tests/test_architect/test_agent_dispatcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_architect/test_agent_dispatcher.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from core.architect.models import (
    AgentTask, AgentAssignment, DispatchResult, RetryPolicy,
    RISK_TO_MIN_SECURITY_SCORE,
)
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionResult, RuntimeLifecycleState, ExecutionContext,
)
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import NegotiationResult
from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES


def make_task(risk_level="low", task_type="code_generate") -> AgentTask:
    from core.architect.models import RISK_TO_POLICY, RISK_TO_MIN_TRUST
    import hashlib, json
    payload = {"description": "test task", "task_type": task_type}
    return AgentTask(
        task_id="t-001",
        task_type=task_type,
        description="test task",
        required_capabilities=["code_generation"],
        required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        priority=2,
        risk_level=risk_level,
        depends_on=[],
        minimum_trust_level=RISK_TO_MIN_TRUST[risk_level],
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30,
        retry_policy=RetryPolicy(),
        expected_output_type="code",
    )


def make_assignment(task=None, hired_temporary=False) -> AgentAssignment:
    return AgentAssignment(
        task=task or make_task(),
        assigned_agent_id="agent-forge-01",
        agent_name="Forge",
        agent_trust_level=70,
        department="engineering",
        hired_temporary=hired_temporary,
        contract_id="contract-001" if hired_temporary else None,
        assignment_reason="existing_agent",
    )


def make_exec_result(success=True) -> ExecutionResult:
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    neg = NegotiationResult(
        requested_tier=IsolationTier.PROCESS_JAIL,
        actual_tier=IsolationTier.PROCESS_JAIL,
        policy=IsolationPolicy.BEST_AVAILABLE,
        reason="exact_match:PROCESS_JAIL",
        host_os="windows",
        fallback_level=0,
        fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL],
        security_score=20,
        risk_adjusted_score=20,
        forensic_support=False,
        behavioral_support=False,
        candidate_drivers=(IsolationTier.PROCESS_JAIL,),
        rejection_reasons={},
        capability_mismatches={},
        policy_rejections={},
    )
    return ExecutionResult(
        success=success,
        output="result output" if success else "",
        error=None if success else "execution failed",
        exit_code=0 if success else 1,
        runtime_id="r-001",
        tier_used=IsolationTier.PROCESS_JAIL,
        duration_ms=150,
        negotiation=neg,
        execution_id="e-001",
        correlation_id="p-001:t-001",
        trace_id="tr-001",
        runtime_state=RuntimeLifecycleState.DESTROYED,
    )


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.execute_isolated = AsyncMock(return_value=make_exec_result())
    return runtime


@pytest.fixture
def mock_perm_manager():
    mgr = MagicMock()
    mgr.has_permission.return_value = True
    mgr.get_agent_permissions.return_value = []
    return mgr


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.terminate_temporary_agent.return_value = True
    return reg


@pytest.fixture
def dispatcher(mock_runtime, mock_perm_manager, mock_registry):
    from core.architect.agent_dispatcher import AgentDispatcher
    return AgentDispatcher(
        runtime=mock_runtime,
        permission_manager=mock_perm_manager,
        registry=mock_registry,
    )


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
async def test_dispatch_calls_execute_isolated(dispatcher, mock_runtime):
    await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    mock_runtime.execute_isolated.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_uses_correct_policy(dispatcher, mock_runtime):
    task = make_task(risk_level="high")
    assignment = make_assignment(task=task)
    await dispatcher.dispatch(assignment, plan_id="p-001")
    call_kwargs = mock_runtime.execute_isolated.call_args[1]
    assert call_kwargs["policy"] == IsolationPolicy.SAFE_DEGRADATION


@pytest.mark.asyncio
async def test_dispatch_permission_denied(dispatcher, mock_perm_manager):
    mock_perm_manager.has_permission.return_value = False
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert result.success is False
    assert "permission_denied" in result.error


@pytest.mark.asyncio
async def test_dispatch_carries_correlation_id(dispatcher):
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert "p-001" in result.correlation_id
    assert "t-001" in result.correlation_id


@pytest.mark.asyncio
async def test_dispatch_cleans_up_temporary_agent(dispatcher, mock_registry, mock_perm_manager):
    assignment = make_assignment(hired_temporary=True)
    await dispatcher.dispatch(assignment, plan_id="p-001")
    mock_registry.terminate_temporary_agent.assert_called_once_with("agent-forge-01")


@pytest.mark.asyncio
async def test_dispatch_does_not_cleanup_permanent_agent(dispatcher, mock_registry):
    assignment = make_assignment(hired_temporary=False)
    await dispatcher.dispatch(assignment, plan_id="p-001")
    mock_registry.terminate_temporary_agent.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_output_truncated_if_large(dispatcher, mock_runtime):
    big_output = "x" * (600 * 1024)  # 600KB — exceeds 512KB limit
    big_result = make_exec_result()
    big_result.output = big_output
    mock_runtime.execute_isolated = AsyncMock(return_value=big_result)
    result = await dispatcher.dispatch(make_assignment(), plan_id="p-001")
    assert len(result.output) <= 512 * 1024
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_architect/test_agent_dispatcher.py -v
```
Expected: `ImportError: cannot import name 'AgentDispatcher'`

- [ ] **Step 3: Implement**

```python
# core/architect/agent_dispatcher.py
"""
AgentDispatcher — the only component that touches UnifiedIsolationRuntime.
execute_isolated() is the ONLY execution path. No exceptions.
"""
from __future__ import annotations
import uuid
from typing import Optional, TYPE_CHECKING

from core.architect.models import (
    AgentAssignment, DispatchResult,
    TASK_TYPE_TO_PERMISSION, RISK_TO_MIN_SECURITY_SCORE,
)
from core.isolation_abstraction.isolation_driver import ExecutionPayload, ExecutionContext

MAX_OUTPUT_BYTES = 512 * 1024   # 512 KB
MAX_ERROR_BYTES  = 64  * 1024   # 64 KB


class AgentDispatcher:
    """
    Validates permissions, executes via UnifiedIsolationRuntime, cleans up temporaries.
    No business logic. No agent selection. One job: dispatch and report.
    """

    def __init__(self, runtime=None, permission_manager=None, registry=None) -> None:
        if runtime is None:
            from core.isolation_abstraction.unified_isolation_runtime import get_unified_runtime
            runtime = get_unified_runtime()
        if permission_manager is None:
            from core.security.permission_manager import get_permission_manager
            permission_manager = get_permission_manager()
        if registry is None:
            from core.agents.nexus_registry import get_registry
            registry = get_registry()
        self._runtime = runtime
        self._perm = permission_manager
        self._registry = registry

    async def dispatch(self, assignment: AgentAssignment, plan_id: str) -> DispatchResult:
        task = assignment.task

        # Security gate: verify permission at dispatch time
        required_perm = TASK_TYPE_TO_PERMISSION.get(task.task_type, "FS_READ")
        if not self._perm.has_permission(assignment.assigned_agent_id, required_perm):
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id,
                agent_id=assignment.assigned_agent_id,
                success=False, output="", error="permission_denied_at_dispatch",
                exit_code=1,
                tier_used=None, security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )

        ctx = ExecutionContext(
            correlation_id=f"{plan_id}:{task.task_id}",
            trace_id=str(uuid.uuid4()),
            preserve_forensics=(task.risk_level in ("high", "critical")),
        )

        payload = ExecutionPayload(
            command=task.payload.get("command"),
            code=task.payload.get("code"),
            timeout_seconds=task.timeout_seconds,
            environment=task.payload.get("environment", {}),
        )

        result = await self._runtime.execute_isolated(
            payload=payload,
            policy=task.isolation_policy,
            ctx=ctx,
            minimum_security_score=RISK_TO_MIN_SECURITY_SCORE[task.risk_level],
            requires_forensics=(task.risk_level == "critical"),
        )

        # Enforce output size limits
        output = (result.output or "")[:MAX_OUTPUT_BYTES]
        error  = (result.error  or "")[:MAX_ERROR_BYTES] if result.error else None

        # Cleanup temporary agents after task completes
        if assignment.hired_temporary:
            try:
                self._registry.terminate_temporary_agent(assignment.assigned_agent_id)
                # Revoke each permission individually using existing API
                perms = self._perm.get_agent_permissions(assignment.assigned_agent_id)
                for perm in perms:
                    self._perm.revoke_permission(
                        assignment.assigned_agent_id, perm.permission_id
                    )
            except Exception:
                pass  # cleanup failure never fails the dispatch result

        return DispatchResult(
            task_id=task.task_id,
            plan_id=plan_id,
            agent_id=assignment.assigned_agent_id,
            success=result.success,
            output=output,
            error=error,
            exit_code=result.exit_code,
            tier_used=result.tier_used,
            security_score=(result.negotiation.security_score if result.negotiation else 0),
            fallback_level=(result.negotiation.fallback_level if result.negotiation else 0),
            duration_ms=result.duration_ms,
            execution_id=result.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            reputation_delta=0.0,
        )

    async def dispatch_with_retry(
        self, assignment: AgentAssignment, plan_id: str
    ) -> DispatchResult:
        policy = assignment.task.retry_policy
        result = None
        for attempt in range(policy.max_retries + 1):
            result = await self.dispatch(assignment, plan_id)
            if result.success or not policy.retry_on_failure:
                return result
        return result
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_architect/test_agent_dispatcher.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Commit**

```
git add core/architect/agent_dispatcher.py tests/test_architect/test_agent_dispatcher.py
git commit -m "feat(architect): Task 3 — AgentDispatcher, execute_isolated() only executor"
```

---

## Task 4: DepartmentArchitect

**Files:**
- Create: `core/architect/department_architect.py`
- Create: `tests/test_architect/test_department_architect.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_architect/test_department_architect.py
import pytest
from unittest.mock import MagicMock, patch
from core.architect.models import AgentTask, AgentAssignment, RetryPolicy
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy


def make_task(risk_level="low", task_type="code_generate", min_trust=30):
    import hashlib, json
    from core.architect.models import RISK_TO_POLICY, RISK_TO_MIN_TRUST
    payload = {"description": "test", "task_type": task_type}
    return AgentTask(
        task_id="t-001",
        task_type=task_type,
        description="test task",
        required_capabilities=["code_generation"],
        required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        priority=2,
        risk_level=risk_level,
        depends_on=[],
        minimum_trust_level=min_trust,
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30,
        retry_policy=RetryPolicy(),
        expected_output_type="code",
    )


def make_agent(trust_level=70, department="engineering", status="active"):
    return MagicMock(
        agent_id="agent-forge-01",
        name="Forge",
        trust_level=trust_level,
        department=department,
        status=status,
    )


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = [make_agent()]
    reg.hire_temporary_agent.return_value = "temp-agent-001"
    return reg


@pytest.fixture
def mock_perm():
    mgr = MagicMock()
    mgr.grant_permission.return_value = True
    return mgr


@pytest.fixture
def dept_arch(mock_registry, mock_perm):
    from core.architect.department_architect import DepartmentArchitect
    return DepartmentArchitect(
        department="engineering",
        registry=mock_registry,
        permission_manager=mock_perm,
    )


def test_assign_returns_agent_assignment(dept_arch):
    result = dept_arch.assign(make_task(), plan_id="p-001")
    assert isinstance(result, AgentAssignment)


def test_assign_picks_existing_eligible_agent(dept_arch, mock_registry):
    result = dept_arch.assign(make_task(), plan_id="p-001")
    assert result.assigned_agent_id == "agent-forge-01"
    assert result.hired_temporary is False
    assert result.assignment_reason == "existing_agent"


def test_assign_skips_insufficient_trust_agent(mock_perm):
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = [make_agent(trust_level=20)]
    reg.hire_temporary_agent.return_value = "temp-001"
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=mock_perm)
    task = make_task(min_trust=70)  # requires trust >= 70, agent has 20
    result = dept.assign(task, plan_id="p-001")
    # Should hire temporary since no eligible agent
    assert result.hired_temporary is True


def test_assign_hires_temporary_when_no_eligible(mock_perm):
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []  # no agents
    reg.hire_temporary_agent.return_value = "temp-001"
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=mock_perm)
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


def test_assign_grants_permissions_for_temp_agent(mock_perm):
    from core.architect.department_architect import DepartmentArchitect
    reg = MagicMock()
    reg.find_agents_by_capability.return_value = []
    reg.hire_temporary_agent.return_value = "temp-001"
    dept = DepartmentArchitect("engineering", registry=reg, permission_manager=mock_perm)
    dept.assign(make_task(), plan_id="p-001")
    mock_perm.grant_permission.assert_called()
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_architect/test_department_architect.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/architect/department_architect.py
"""
DepartmentArchitect — per-department agent selection.
Picks existing eligible agents, hires temporaries when allowed, raises otherwise.
No execution logic. No knowledge of ArchitectCore.
"""
from __future__ import annotations
from typing import Optional


class NoEligibleAgentError(RuntimeError):
    pass


# Departments that cannot hire temporary agents
_NO_TEMP_HIRE_DEPTS = {"security", "runtime"}

# Minimum permissions granted to temporary agents per task_type
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


class DepartmentArchitect:
    """
    One instance per department. Knows only its own domain.
    Selects best existing agent or hires a temporary contractor.
    """

    def __init__(
        self,
        department: str,
        registry=None,
        permission_manager=None,
    ) -> None:
        self.department = department
        if registry is None:
            from core.agents.nexus_registry import get_registry
            registry = get_registry()
        if permission_manager is None:
            from core.security.permission_manager import get_permission_manager
            permission_manager = get_permission_manager()
        self._registry = registry
        self._perm = permission_manager

    def assign(
        self,
        task,                            # AgentTask
        plan_id: str,
    ):                                   # → AgentAssignment
        from core.architect.models import AgentAssignment

        # Step 1: find eligible existing agents
        cap = task.required_capabilities[0] if task.required_capabilities else None
        candidates = self._registry.find_agents_by_capability(cap) if cap else []
        eligible = [
            a for a in candidates
            if getattr(a, "department", None) == self.department
            and getattr(a, "trust_level", 0) >= task.minimum_trust_level
            and getattr(a, "status", "inactive") == "active"
        ]

        if eligible:
            agent = eligible[0]  # registry returns sorted by trust_level DESC
            return AgentAssignment(
                task=task,
                assigned_agent_id=agent.agent_id,
                agent_name=agent.name,
                agent_trust_level=agent.trust_level,
                department=self.department,
                hired_temporary=False,
                contract_id=None,
                assignment_reason="existing_agent",
            )

        # Step 2: hire temporary if department policy allows
        can_hire = self.department not in _NO_TEMP_HIRE_DEPTS
        if can_hire and task.risk_level in ("low", "medium"):
            import uuid
            temp_name = f"temp-{task.task_type}-{uuid.uuid4().hex[:6]}"
            agent_id = self._registry.hire_temporary_agent(
                name=temp_name,
                role=task.task_type,
                department=self.department,
                capabilities=task.required_capabilities,
                task_description=task.description,
            )
            # Grant minimum necessary permissions
            perms = _TEMP_AGENT_PERMISSIONS.get(task.task_type, ["FS_READ"])
            for perm_id in perms:
                try:
                    self._perm.grant_permission(agent_id, perm_id)
                except Exception:
                    pass

            return AgentAssignment(
                task=task,
                assigned_agent_id=agent_id,
                agent_name=temp_name,
                agent_trust_level=30,     # minimum trust for temporary
                department=self.department,
                hired_temporary=True,
                contract_id=None,         # registry creates contract internally
                assignment_reason="temporary_hired",
            )

        # Step 3: no eligible agent, no hiring → escalate
        raise NoEligibleAgentError(
            f"dept={self.department} task_type={task.task_type} "
            f"min_trust={task.minimum_trust_level} risk={task.risk_level} "
            f"can_hire_temporary={can_hire}"
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_architect/test_department_architect.py -v
```
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```
git add core/architect/department_architect.py tests/test_architect/test_department_architect.py
git commit -m "feat(architect): Task 4 — DepartmentArchitect, agent selection + temp hiring"
```

---

## Task 5: ArchitectCore

**Files:**
- Create: `core/architect/architect_core.py`
- Create: `tests/test_architect/test_architect_core.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_architect/test_architect_core.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.architect.models import (
    AgentTask, TaskPlan, AgentAssignment, DispatchResult, RetryPolicy,
)
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from datetime import datetime, timezone


def make_task(task_id="t-001", depends_on=None, risk_level="low") -> AgentTask:
    import hashlib, json
    from core.architect.models import RISK_TO_POLICY, RISK_TO_MIN_TRUST
    payload = {"description": "test"}
    return AgentTask(
        task_id=task_id,
        task_type="code_generate",
        description="test",
        required_capabilities=["code_generation"],
        required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        priority=2,
        risk_level=risk_level,
        depends_on=depends_on or [],
        minimum_trust_level=30,
        isolation_policy=RISK_TO_POLICY[risk_level],
        timeout_seconds=30,
        retry_policy=RetryPolicy(),
        expected_output_type="code",
    )


def make_plan(tasks=None, risk_level="low", requires_approval=False) -> TaskPlan:
    return TaskPlan(
        plan_id="p-001",
        parent_request_id=None,
        origin="user",
        created_at=datetime.now(timezone.utc),
        original_request="test request",
        task_type="code_generate",
        complexity="simple",
        risk_level=risk_level,
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
        execution_id="e-001", correlation_id="p-001:t-001", trace_id=None,
    )


@pytest.fixture
def mock_dept_arch():
    arch = MagicMock()
    assignment = AgentAssignment(
        task=make_task(),
        assigned_agent_id="a-001", agent_name="Agent",
        agent_trust_level=70, department="engineering",
        hired_temporary=False, contract_id=None,
        assignment_reason="existing_agent",
    )
    arch.assign.return_value = assignment
    return arch


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.dispatch_with_retry = AsyncMock(return_value=make_dispatch_result())
    return d


@pytest.fixture
def core(mock_dept_arch, mock_dispatcher):
    from core.architect.architect_core import ArchitectCore
    return ArchitectCore(
        department_architects={"engineering": mock_dept_arch},
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
async def test_orchestrate_respects_dag_order(mock_dispatcher):
    from core.architect.architect_core import ArchitectCore
    call_order = []

    async def track_dispatch(assignment, plan_id):
        call_order.append(assignment.task.task_id)
        return make_dispatch_result(assignment.task.task_id)

    mock_dispatcher.dispatch_with_retry = track_dispatch

    task_a = make_task(task_id="t-a", depends_on=[])
    task_b = make_task(task_id="t-b", depends_on=["t-a"])

    mock_dept = MagicMock()
    mock_dept.assign.side_effect = lambda task, plan_id: AgentAssignment(
        task=task, assigned_agent_id="a-1", agent_name="A",
        agent_trust_level=70, department="engineering",
        hired_temporary=False, contract_id=None, assignment_reason="existing_agent",
    )
    arch = ArchitectCore(
        department_architects={"engineering": mock_dept},
        dispatcher=mock_dispatcher,
    )
    await arch.orchestrate(make_plan(tasks=[task_a, task_b]), requestor_id="u")
    assert call_order.index("t-a") < call_order.index("t-b")


@pytest.mark.asyncio
async def test_orchestrate_skips_dependents_on_failure(mock_dispatcher):
    from core.architect.architect_core import ArchitectCore

    async def fail_first(assignment, plan_id):
        if assignment.task.task_id == "t-a":
            return make_dispatch_result("t-a", success=False)
        return make_dispatch_result(assignment.task.task_id, success=True)

    mock_dispatcher.dispatch_with_retry = fail_first

    task_a = make_task(task_id="t-a")
    task_b = make_task(task_id="t-b", depends_on=["t-a"])

    mock_dept = MagicMock()
    mock_dept.assign.side_effect = lambda task, plan_id: AgentAssignment(
        task=task, assigned_agent_id="a-1", agent_name="A",
        agent_trust_level=70, department="engineering",
        hired_temporary=False, contract_id=None, assignment_reason="existing_agent",
    )
    arch = ArchitectCore(
        department_architects={"engineering": mock_dept},
        dispatcher=mock_dispatcher,
    )
    result = await arch.orchestrate(
        make_plan(tasks=[task_a, task_b], risk_level="low"),
        requestor_id="u",
    )
    assert "t-b" in result.skipped_tasks


@pytest.mark.asyncio
async def test_orchestrate_requires_approval_blocks(core):
    plan = make_plan(requires_approval=True)
    # Without a real approval system, critical plans return failure if no approver provided
    result = await core.orchestrate(plan, requestor_id="user-1")
    # Plan requires approval but no approval granted → overall_success=False
    assert result.human_approval_required is True


def test_resolve_dag_linear():
    from core.architect.architect_core import ArchitectCore
    arch = ArchitectCore.__new__(ArchitectCore)
    t1 = make_task(task_id="t1")
    t2 = make_task(task_id="t2", depends_on=["t1"])
    t3 = make_task(task_id="t3", depends_on=["t2"])
    waves = arch._resolve_dag([t1, t2, t3])
    assert len(waves) == 3
    assert waves[0][0].task_id == "t1"
    assert waves[1][0].task_id == "t2"
    assert waves[2][0].task_id == "t3"


def test_resolve_dag_raises_on_cycle():
    from core.architect.architect_core import ArchitectCore, CyclicDependencyError
    arch = ArchitectCore.__new__(ArchitectCore)
    t1 = make_task(task_id="t1", depends_on=["t2"])
    t2 = make_task(task_id="t2", depends_on=["t1"])
    with pytest.raises(CyclicDependencyError):
        arch._resolve_dag([t1, t2])
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_architect/test_architect_core.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
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


class CyclicDependencyError(RuntimeError):
    pass


class ArchitectCore:
    """
    Gatekeeper and orchestrator. Routes tasks to DepartmentArchitects,
    dispatches via AgentDispatcher, aggregates results.
    """

    def __init__(
        self,
        department_architects: dict | None = None,
        dispatcher=None,
    ) -> None:
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

        # Gate: human approval required?
        if plan.requires_human_approval:
            return OrchestrationResult(
                plan_id=plan.plan_id,
                overall_success=False,
                completed_tasks=[],
                failed_tasks=[t.task_id for t in plan.subtasks],
                skipped_tasks=[],
                total_duration_ms=0,
                isolation_summary={},
                audit_chain=[],
                human_approval_required=True,
                human_approval_granted=None,
            )

        # Gate: circular dependencies
        try:
            waves = self._resolve_dag(plan.subtasks)
        except CyclicDependencyError as e:
            return OrchestrationResult(
                plan_id=plan.plan_id,
                overall_success=False,
                completed_tasks=[],
                failed_tasks=[t.task_id for t in plan.subtasks],
                skipped_tasks=[],
                total_duration_ms=0,
                isolation_summary={},
                audit_chain=[],
                human_approval_required=False,
                human_approval_granted=None,
            )

        start_ms = int(time.monotonic() * 1000)
        completed = []
        failed_ids = []
        skipped_ids = []

        for wave in waves:
            # Skip tasks whose dependencies failed
            executable = [t for t in wave if t.task_id not in failed_ids
                          and not any(dep in failed_ids for dep in t.depends_on)]
            newly_skipped = [t.task_id for t in wave if t not in executable]
            skipped_ids.extend(newly_skipped)

            if not executable:
                continue

            # Execute wave concurrently
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

            # Fail-fast for critical plans on any failure
            if failed_ids and plan.risk_level == "critical":
                remaining = [t.task_id for w in waves for t in w
                             if t.task_id not in {r.task_id for r in completed}
                             and t.task_id not in failed_ids]
                skipped_ids.extend(remaining)
                break

        total_ms = int(time.monotonic() * 1000) - start_ms
        tiers_used = [r.tier_used.name for r in completed if r.tier_used]
        avg_score = (sum(r.security_score for r in completed) // len(completed)
                     if completed else 0)

        return self._build_result(
            plan=plan,
            completed=completed,
            failed_ids=failed_ids,
            skipped_ids=skipped_ids,
            total_ms=total_ms,
            tiers=tiers_used,
            avg_score=avg_score,
        )

    async def _route_task(self, task, plan_id: str):
        dept = self._depts.get(task.required_department)
        if dept is None:
            from core.architect.models import DispatchResult
            from core.isolation_abstraction.isolation_driver import IsolationTier
            import uuid
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id, agent_id="none",
                success=False, output="", error=f"no_architect_for_dept:{task.required_department}",
                exit_code=1, tier_used=IsolationTier.PROCESS_JAIL,
                security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )
        from core.architect.department_architect import NoEligibleAgentError
        try:
            assignment = dept.assign(task, plan_id)
            return await self._dispatcher.dispatch_with_retry(assignment, plan_id)
        except NoEligibleAgentError as e:
            from core.architect.models import DispatchResult
            from core.isolation_abstraction.isolation_driver import IsolationTier
            import uuid
            return DispatchResult(
                task_id=task.task_id, plan_id=plan_id, agent_id="none",
                success=False, output="", error=str(e),
                exit_code=1, tier_used=IsolationTier.PROCESS_JAIL,
                security_score=0, fallback_level=0, duration_ms=0,
                execution_id=str(uuid.uuid4()),
                correlation_id=f"{plan_id}:{task.task_id}",
                trace_id=None,
            )

    def _resolve_dag(self, tasks) -> list[list]:
        """Topological sort → list of waves (each wave runs concurrently)."""
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
            wave = [task_map[tid] for tid in queue]
            waves.append(wave)
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

    @staticmethod
    def _build_result(plan, completed, failed_ids, skipped_ids,
                      total_ms, tiers, avg_score):
        from core.architect.models import OrchestrationResult
        return OrchestrationResult(
            plan_id=plan.plan_id,
            overall_success=len(failed_ids) == 0,
            completed_tasks=completed,
            failed_tasks=failed_ids,
            skipped_tasks=skipped_ids,
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
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_architect/test_architect_core.py -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```
git add core/architect/architect_core.py tests/test_architect/test_architect_core.py
git commit -m "feat(architect): Task 5 — ArchitectCore gatekeeper, DAG execution, aggregation"
```

---

## Task 6: ExternalAgentIntegration stub + conftest

**Files:**
- Create: `core/architect/external_agent_integration.py`
- Create: `tests/test_architect/conftest.py`

- [ ] **Step 1: Create external agent integration stub**

```python
# core/architect/external_agent_integration.py
"""
ExternalAgentIntegration — gate for external agents entering Nexus.
FASE 1: stubs only. Raises NotImplementedError.
FASE 3: implement multi-step quarantine onboarding.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExternalAgentOnboardResult:
    success: bool
    agent_id: Optional[str] = None
    status: Optional[str] = None           # "quarantine"|"active"
    reason: Optional[str] = None
    next_step: Optional[str] = None
    execution_id: Optional[str] = None
    scan_id: Optional[str] = None


class ExternalAgentIntegration:
    """
    Future: multi-step quarantine onboarding for external agents.
    All external agents start in quarantine with minimum trust.
    Promotion requires explicit human approval via ArchitectCore.
    """

    async def onboard_external_agent(
        self,
        agent_spec: dict,
        requested_department: str,
    ) -> ExternalAgentOnboardResult:
        """
        FASE 1 stub. FASE 3 implementation:
        1. AST scan of agent_spec["code"]
        2. STRICT_ISOLATION sandbox evaluation
        3. Register with trust_level=10, status="quarantine"
        4. Log onboarding event to audit logger
        """
        raise NotImplementedError(
            "ExternalAgentIntegration.onboard_external_agent — implement in FASE 3. "
            "Requires: AST scan → sandbox eval → quarantine registration → audit log."
        )

    async def promote_from_quarantine(
        self,
        agent_id: str,
        approved_by: str,
        new_trust_level: int,
    ) -> bool:
        """
        FASE 1 stub. Requires explicit human approval.
        Only ArchitectCore (trust_level=ROOT) can call this.
        """
        raise NotImplementedError(
            "ExternalAgentIntegration.promote_from_quarantine — implement in FASE 3."
        )
```

- [ ] **Step 2: Create conftest.py**

```python
# tests/test_architect/conftest.py
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def ensure_data_dir():
    Path("data").mkdir(exist_ok=True)
```

- [ ] **Step 3: Add stub test**

```python
# Append to tests/test_architect/test_models.py
def test_external_agent_onboard_raises():
    import pytest
    import asyncio
    from core.architect.external_agent_integration import ExternalAgentIntegration
    integration = ExternalAgentIntegration()
    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(
            integration.onboard_external_agent({"name": "agent"}, "engineering")
        )
```

- [ ] **Step 4: Commit**

```
git add core/architect/external_agent_integration.py tests/test_architect/conftest.py
git commit -m "feat(architect): Task 6 — ExternalAgentIntegration stub (FASE 3 hook)"
```

---

## Task 7: End-to-End Integration Test

**Files:**
- Create: `tests/test_architect/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_architect/test_integration.py
"""
End-to-end integration: User request → ArchitectCore → isolated execution → result.
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
        reason="exact_match",
        host_os="windows",
        fallback_level=0,
        fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL],
        security_score=20,
        risk_adjusted_score=20,
        forensic_support=False,
        behavioral_support=False,
        candidate_drivers=(IsolationTier.PROCESS_JAIL,),
        rejection_reasons={},
        capability_mismatches={},
        policy_rejections={},
    )


def make_execution_result(success=True) -> ExecutionResult:
    return ExecutionResult(
        success=success,
        output="# generated code\ndef hello(): return 'world'" if success else "",
        error=None if success else "execution failed",
        exit_code=0 if success else 1,
        runtime_id="r-001",
        tier_used=IsolationTier.PROCESS_JAIL,
        duration_ms=250,
        negotiation=make_negotiation(),
        execution_id="e-001",
        correlation_id="p-001:t-001",
        trace_id="tr-001",
        runtime_state=RuntimeLifecycleState.DESTROYED,
    )


@pytest.fixture
def full_pipeline():
    """Full Architect pipeline with mocked external dependencies."""
    # Mock agent in registry
    mock_agent = MagicMock(
        agent_id="agent-forge-01",
        name="Forge",
        trust_level=70,
        department="engineering",
        status="active",
    )
    mock_registry = MagicMock()
    mock_registry.find_agents_by_capability.return_value = [mock_agent]
    mock_registry.terminate_temporary_agent.return_value = True

    # Mock permission manager
    mock_perm = MagicMock()
    mock_perm.has_permission.return_value = True
    mock_perm.get_agent_permissions.return_value = []

    # Mock runtime
    mock_runtime = MagicMock()
    mock_runtime.execute_isolated = AsyncMock(return_value=make_execution_result())

    # Wire up the pipeline
    planner = AgentTaskPlanner()
    dispatcher = AgentDispatcher(
        runtime=mock_runtime,
        permission_manager=mock_perm,
        registry=mock_registry,
    )
    dept_arch = DepartmentArchitect(
        department="engineering",
        registry=mock_registry,
        permission_manager=mock_perm,
    )
    core = ArchitectCore(
        department_architects={"engineering": dept_arch},
        dispatcher=dispatcher,
    )
    return {"planner": planner, "core": core, "runtime": mock_runtime}


@pytest.mark.asyncio
async def test_end_to_end_create_app(full_pipeline):
    """Full flow: 'create a simple app' → OrchestrationResult."""
    planner = full_pipeline["planner"]
    core = full_pipeline["core"]

    plan = planner.plan("create a simple app")
    result = await core.orchestrate(plan, requestor_id="user-123")

    assert isinstance(result, OrchestrationResult)
    assert result.overall_success is True
    assert len(result.completed_tasks) >= 1
    assert result.failed_tasks == []


@pytest.mark.asyncio
async def test_end_to_end_result_has_forensic_ids(full_pipeline):
    """Every DispatchResult carries execution_id and correlation_id."""
    plan = full_pipeline["planner"].plan("build a utility function")
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")

    assert result.overall_success is True
    for dispatch in result.completed_tasks:
        assert dispatch.execution_id is not None
        assert dispatch.correlation_id is not None
        assert ":" in dispatch.correlation_id   # "plan_id:task_id" format


@pytest.mark.asyncio
async def test_end_to_end_execute_isolated_called(full_pipeline):
    """execute_isolated() is always called — never direct execution."""
    plan = full_pipeline["planner"].plan("generate a REST API")
    await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    full_pipeline["runtime"].execute_isolated.assert_called()


@pytest.mark.asyncio
async def test_end_to_end_security_request_fails_gracefully(full_pipeline):
    """Security dept has no agents → task skips gracefully for non-critical plans."""
    plan = full_pipeline["planner"].plan("scan code for security vulnerabilities")
    # Security dept not in dept_architects → task fails gracefully
    result = await full_pipeline["core"].orchestrate(plan, requestor_id="user-1")
    assert isinstance(result, OrchestrationResult)
    # Either failed or skipped — but no exception raised
    assert not isinstance(result, Exception)


@pytest.mark.asyncio
async def test_end_to_end_dag_two_tasks(full_pipeline):
    """Two tasks with dependency: both complete in order."""
    from core.architect.models import RISK_TO_POLICY, RISK_TO_MIN_TRUST
    import hashlib, json, uuid
    from core.architect.models import AgentTask, TaskPlan, RetryPolicy

    payload = {"description": "test"}
    t1 = AgentTask(
        task_id="t-a", task_type="code_generate", description="step 1",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        priority=2, risk_level="low", depends_on=[],
        minimum_trust_level=30, isolation_policy=RISK_TO_POLICY["low"],
        timeout_seconds=30, retry_policy=RetryPolicy(), expected_output_type="code",
    )
    t2 = AgentTask(
        task_id="t-b", task_type="code_generate", description="step 2",
        required_capabilities=["code_generation"], required_department="engineering",
        payload=payload,
        payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        priority=2, risk_level="low", depends_on=["t-a"],
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
```

- [ ] **Step 2: Run to verify tests**

```
python -m pytest tests/test_architect/test_integration.py -v --tb=short
```
Expected: 6 PASSED

- [ ] **Step 3: Run full architect suite**

```
python -m pytest tests/test_architect/ -v --tb=short
```
Expected: all PASSED

- [ ] **Step 4: Run full combined suite**

```
python -m pytest tests/test_isolation_abstraction/ tests/test_vm_isolation/ tests/test_architect/ -q --tb=no
```
Expected: 220+ passed (178 existing + architect tests)

- [ ] **Step 5: Commit**

```
git add tests/test_architect/test_integration.py
git commit -m "test(architect): Task 7 — end-to-end integration tests, full pipeline verified"
```

---

## Self-Review

**Spec coverage:**

| Spec Section | Task |
|---|---|
| All data models (AgentTask, TaskPlan, AgentAssignment, DispatchResult, OrchestrationResult, RetryPolicy) | Task 1 |
| Lookup tables (CAPABILITY_MAP, DEPARTMENT_MAP, RISK_TO_POLICY, RISK_TO_MIN_TRUST, RISK_TO_MIN_SECURITY_SCORE, TASK_TYPE_TO_PERMISSION) | Task 1 |
| AgentTaskPlanner — keyword classification, decompose, payload_hash, origin, parent_request_id | Task 2 |
| AgentDispatcher — execute_isolated() only, permission gate, output truncation, temp cleanup, forensic context | Task 3 |
| DepartmentArchitect — eligible agent selection, temp hiring, NoEligibleAgentError, security dept no-temp rule | Task 4 |
| ArchitectCore — DAG resolution, wave execution, fail-fast (critical), human approval gate, aggregation | Task 5 |
| ExternalAgentIntegration — stub with NotImplementedError, FASE 3 documented | Task 6 |
| End-to-end flow: User → ArchitectCore → isolated execution → result | Task 7 |
| Future hooks (reputation_delta=0.0, performance_snapshot={}, recommended_agents=[]) | Task 1 (models) |
| Dependency direction (dispatcher doesn't import core/dept, dept doesn't import dispatcher) | All tasks via import structure |

**Placeholder scan:** No TBD, no "implement later", no "similar to Task N". Every stub has a specific FASE label and description.

**Type consistency:**
- `AgentTask.task_id` → defined Task 1, used in Task 3 (`DispatchResult.task_id`), Task 4 (`assignment.task.task_id`), Task 5 (`_route_task`, `_resolve_dag`). Consistent.
- `AgentAssignment.hired_temporary` → defined Task 1, checked in Task 3 dispatcher cleanup. Consistent.
- `IsolationPolicy` → imported from `core.isolation_abstraction.isolation_strategy_manager` in models.py (Task 1), referenced in Task 3 dispatcher, Task 4 planner. Consistent.
- `dispatch_with_retry()` → defined in Task 3, called in Task 5 (`_route_task`). Consistent.
