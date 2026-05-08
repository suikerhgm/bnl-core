# Nexus Architect Layer — Design Spec
**Date:** 2026-05-08
**Status:** Approved — ready for implementation
**Phase:** Nexus BNL — Autonomous Agent Orchestration Layer

---

## 1. Goals

Build the hierarchical agent orchestration layer for Nexus — the foundation for autonomous multi-agent execution. Every sub-system action routes through `UnifiedIsolationRuntime.execute_isolated()` without exception.

**Primary objectives:**
- ArchitectCore as gatekeeper: validate, sequence, route — zero business logic
- Deterministic agent assignment via existing `NexusAgentRegistry` + `PermissionManager`
- AI used only for task classification — all routing is rule-based
- Complete forensic traceability on every execution (execution_id, correlation_id, trace_id)
- Future-ready hooks for reputation system, autonomous hiring, self-learning

**Not in scope (Plan D):**
- Self-learning / adaptive strategy
- Reputation system logic
- Autonomous hiring decisions
- External agent auto-discovery

---

## 2. Existing Infrastructure (used, not modified)

| Component | Location | Role in Architect Layer |
|---|---|---|
| `NexusAgentRegistry` | `core/agents/nexus_registry.py` | Agent lookup, hire_temporary, terminate |
| `PermissionManager` | `core/security/permission_manager.py` | Permission validation + grant/revoke |
| `UnifiedIsolationRuntime` | `core/isolation_abstraction/unified_isolation_runtime.py` | **The only execution path** |
| `IsolationAuditLogger` | `core/isolation_abstraction/isolation_audit_logger.py` | Forensic audit trail |
| `TrustLevel` | `core/security/permissions.py` | 0=READ_ONLY → 5=ROOT |
| `ApprovalSystem` | `core/approval_system.py` | Human approval for critical tasks |
| `ASTSecurityEngine` | `core/ast_security/ast_security_engine.py` | External agent code scanning |

---

## 3. New Files

```
core/architect/
├── __init__.py
├── models.py                   # All shared data models (AgentTask, TaskPlan, etc.)
├── agent_task_planner.py       # AI classification + deterministic decomposition
├── architect_core.py           # Gatekeeper + DAG executor + aggregator (pure façade)
├── department_architect.py     # Per-department agent selection + temp hiring
├── agent_dispatcher.py         # execute_isolated() wrapper — the only executor
└── external_agent_integration.py  # Quarantine onboarding for external agents
```

No existing file is modified.

---

## 4. Data Models — `core/architect/models.py`

All components share these types. No component defines its own data models.

### 4.1 `AgentTask` — atomic unit of work

```python
@dataclass
class AgentTask:
    task_id: str                          # UUID — stable identifier for forensics
    task_type: str                        # "code_generate" | "security_scan" | "file_write" |
                                          #   "api_design" | "data_pipeline" | "frontend_ui" |
                                          #   "threat_model" | "test_automation" | "deployment"
    description: str
    required_capabilities: list[str]      # capability names from capabilities table
    required_department: str              # "engineering" | "security" | "frontend" |
                                          #   "research" | "runtime" | "repairs"
    payload: dict                         # ExecutionPayload-compatible data:
                                          #   {command?, code?, timeout?, environment?}
    payload_hash: str                     # SHA256 of payload for tamper detection
    priority: int                         # 1 (low) – 5 (critical)
    risk_level: str                       # "low" | "medium" | "high" | "critical"
    depends_on: list[str]                 # task_ids that must complete before this (DAG)
    minimum_trust_level: int              # min trust_level agent must have (0–100)
    isolation_policy: IsolationPolicy     # BEST_AVAILABLE | SAFE_DEGRADATION | STRICT_ISOLATION
    timeout_seconds: int                  # hard kill after this many seconds (default: 30)
    retry_policy: RetryPolicy             # see below
    expected_output_type: str            # "code" | "report" | "confirmation" | "data"
```

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 0                  # 0 = no retry
    retry_on_failure: bool = False
    escalate_on_final_failure: bool = True  # notify ArchitectCore if all retries exhausted
```

### 4.2 `TaskPlan` — contract produced by AgentTaskPlanner

```python
@dataclass
class TaskPlan:
    # Identity
    plan_id: str                          # UUID
    parent_request_id: str | None        # links to parent plan if nested
    origin: str                           # "user" | "agent" | "system"
    created_at: datetime

    # Classification (AI-produced)
    original_request: str
    task_type: str                        # top-level: "development" | "security" | "research" | ...
    complexity: str                       # "simple" | "moderate" | "complex"
    risk_level: str                       # "low" | "medium" | "high" | "critical"
    ai_reasoning: str                     # AI's one-sentence explanation

    # Execution plan (deterministic)
    subtasks: list[AgentTask]
    requires_human_approval: bool

    # Future hooks (not populated until Plan D)
    performance_snapshot: dict            # for reputation system — always {} now
```

### 4.3 `AgentAssignment` — DepartmentArchitect's decision

```python
@dataclass
class AgentAssignment:
    task: AgentTask
    assigned_agent_id: str
    agent_name: str
    agent_trust_level: int
    department: str
    hired_temporary: bool
    contract_id: str | None              # populated if hired_temporary=True
    assignment_reason: str               # "existing_agent" | "temporary_hired" | "escalated"
    # Future hooks
    expected_performance_score: float = 0.0   # baseline for reputation delta (Plan D)
```

### 4.4 `DispatchResult` — result of one executed task

```python
@dataclass
class DispatchResult:
    # Identification
    task_id: str
    plan_id: str
    agent_id: str

    # Execution outcome
    success: bool
    output: str                           # truncated to MAX_OUTPUT_BYTES if needed
    error: str | None
    exit_code: int

    # Isolation metadata
    tier_used: IsolationTier
    security_score: int                   # from NegotiationResult
    fallback_level: int                   # 0 = exact match, >0 = degraded
    duration_ms: int

    # Forensic chain
    execution_id: str
    correlation_id: str
    trace_id: str | None

    # Future hooks
    reputation_delta: float = 0.0         # +/- for agent reputation (Plan D)
```

### 4.5 `OrchestrationResult` — final result returned to caller

```python
@dataclass
class OrchestrationResult:
    plan_id: str
    overall_success: bool
    completed_tasks: list[DispatchResult]
    failed_tasks: list[str]              # task_ids that failed after retries
    skipped_tasks: list[str]             # task_ids skipped due to dependency failure
    total_duration_ms: int
    isolation_summary: dict              # {tier: str, avg_score: int, fallbacks: int}
    audit_chain: list[str]              # event_ids from IsolationAuditLogger
    human_approval_required: bool
    human_approval_granted: bool | None  # None if not asked

    # Future hooks (Plan D)
    performance_report: dict             # per-agent performance metrics — always {} now
    recommended_agents: list[str]        # agents that performed well — always [] now
```

### 4.6 Deterministic lookup tables (in `models.py`)

```python
CAPABILITY_MAP: dict[str, list[str]] = {
    "code_generate":  ["code_generation"],
    "security_scan":  ["security_analysis", "threat_modeling"],
    "api_design":     ["api_design", "code_generation"],
    "frontend_ui":    ["frontend_ui"],
    "data_pipeline":  ["data_pipeline"],
    "test_automation":["test_automation"],
    "deployment":     ["deployment", "process_management"],
    "file_write":     [],               # no specific capability needed
    "threat_model":   ["threat_modeling"],
}

DEPARTMENT_MAP: dict[str, str] = {
    "code_generate":  "engineering",
    "security_scan":  "security",
    "api_design":     "engineering",
    "frontend_ui":    "frontend",
    "data_pipeline":  "research",
    "test_automation":"engineering",
    "deployment":     "runtime",
    "file_write":     "engineering",
    "threat_model":   "security",
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
```

---

## 5. `AgentTaskPlanner` — `core/architect/agent_task_planner.py`

**Single responsibility:** Classify user intent via AI, decompose into `AgentTask` list via deterministic rules. Produces a `TaskPlan`. Does nothing else.

### 5.1 AI Classification

One AI call per `plan()` invocation. Returns structured JSON:

```json
{
  "task_type": "code_generate",
  "complexity": "moderate",
  "risk_level": "medium",
  "domains": ["engineering"],
  "requires_human_approval": false,
  "reasoning": "JWT endpoint requires code generation and light security review"
}
```

The prompt is minimal and structured. The AI's role is classification only — it does not decide which agent runs the task.

### 5.2 Deterministic Decomposition

After AI classification, `_decompose()` applies the lookup tables to produce `AgentTask` objects:

```python
def _decompose(self, classification: dict, request: str) -> list[AgentTask]:
    # One primary task always created
    primary = AgentTask(
        task_id=str(uuid4()),
        task_type=classification["task_type"],
        required_capabilities=CAPABILITY_MAP[classification["task_type"]],
        required_department=DEPARTMENT_MAP[classification["task_type"]],
        isolation_policy=RISK_TO_POLICY[classification["risk_level"]],
        minimum_trust_level=RISK_TO_MIN_TRUST[classification["risk_level"]],
        payload_hash=sha256(request.encode()).hexdigest(),
        ...
    )
    tasks = [primary]

    # Secondary security review for high/critical
    if classification["risk_level"] in ("high", "critical"):
        review = AgentTask(
            task_id=str(uuid4()),
            task_type="security_scan",
            depends_on=[primary.task_id],   # runs AFTER primary
            ...
        )
        tasks.append(review)

    return tasks
```

### 5.3 Interface

```python
class AgentTaskPlanner:
    async def plan(
        self,
        user_request: str,
        origin: str = "user",
        parent_request_id: str | None = None,
    ) -> TaskPlan: ...
```

**Dependency imports:** AI cascade only (no registry, no runtime, no permission_manager).

---

## 6. `ArchitectCore` — `core/architect/architect_core.py`

**Single responsibility:** Pure façade — validate, sequence, route, aggregate. Zero business logic.

Registered in `NexusAgentRegistry` with:
- `agent_id = "nexus-architect-core"`
- `trust_level = 100` (ROOT equivalent in 0–100 scale)
- `department = "engineering"` (cross-department visibility)

### 6.1 Validation gates (in order, all must pass)

```
Gate 1: Plan-level risk → human approval if requires_human_approval=True
Gate 2: Requestor has permission to trigger this plan's risk level
         (risk=critical → requestor needs AGENT_REGISTER permission)
Gate 3: DAG validity → no circular dependencies in depends_on
Gate 4: All required departments exist in registry
```

If any gate fails → return `OrchestrationResult(overall_success=False)` immediately.

### 6.2 DAG execution

```python
def _resolve_dag(self, tasks: list[AgentTask]) -> list[list[AgentTask]]:
    """Topological sort. Raises CyclicDependencyError if circular."""

async def _execute_wave(self, tasks: list[AgentTask], plan_id: str) -> list[DispatchResult]:
    """Concurrent execution within a wave (asyncio.gather)."""

async def orchestrate(self, plan: TaskPlan, requestor_id: str) -> OrchestrationResult:
    # Validate → Resolve DAG → Execute waves → Aggregate
```

Execution waves example:
```
depends_on graph: B→A, C→A, D→B
→ wave 1: [A]
→ wave 2: [B, C]  (concurrent)
→ wave 3: [D]
```

### 6.3 Fail-fast policy

- `risk_level=critical`: stop on first failed wave
- `risk_level=high`: continue but flag failures in result
- `risk_level=low/medium`: continue, collect all results

### 6.4 Routing

```python
async def _route_to_department(self, task: AgentTask, plan_id: str) -> DispatchResult:
    dept_architect = self._get_department_architect(task.required_department)
    assignment = await dept_architect.assign(task, plan_id)
    return await self._dispatcher.dispatch(assignment, plan_id)
```

ArchitectCore never touches `execute_isolated()` directly.

### 6.5 Aggregation

```python
def _aggregate(self, plan: TaskPlan, results: list[DispatchResult]) -> OrchestrationResult:
    # Compute overall_success, isolation_summary, build audit_chain
    # Populate performance_report={}, recommended_agents=[]  # hooks for Plan D
```

**Dependency imports:** `agent_task_planner`, `department_architect`, `agent_dispatcher`, `permission_manager`, `approval_system`, `isolation_audit_logger`. Never imports `unified_isolation_runtime`.

---

## 7. `DepartmentArchitect` — `core/architect/department_architect.py`

**Single responsibility:** Given an `AgentTask`, select (or hire) the best eligible agent within its department and produce an `AgentAssignment`.

### 7.1 Per-department configuration

```python
DEPT_CONFIG: dict[str, dict] = {
    "engineering": {
        "agent_id":           "dept-arch-engineering",
        "trust_level":        70,
        "can_hire_temporary": True,
        "max_temp_risk":      "medium",   # can hire temps for low/medium tasks only
    },
    "security": {
        "agent_id":           "dept-arch-security",
        "trust_level":        85,
        "can_hire_temporary": False,      # security agents must be pre-approved
        "max_temp_risk":      None,
    },
    "frontend": {
        "agent_id":           "dept-arch-frontend",
        "trust_level":        70,
        "can_hire_temporary": True,
        "max_temp_risk":      "medium",
    },
    "research": {
        "agent_id":           "dept-arch-research",
        "trust_level":        70,
        "can_hire_temporary": True,
        "max_temp_risk":      "low",
    },
    "runtime": {
        "agent_id":           "dept-arch-runtime",
        "trust_level":        85,
        "can_hire_temporary": False,
        "max_temp_risk":      None,
    },
    "repairs": {
        "agent_id":           "dept-arch-repairs",
        "trust_level":        70,
        "can_hire_temporary": True,
        "max_temp_risk":      "medium",
    },
}
```

### 7.2 Assignment logic

```python
async def assign(self, task: AgentTask, plan_id: str) -> AgentAssignment:
    # Step 1: Security gate — task allowed in this dept?
    self._validate_task_risk(task)

    # Step 2: Find eligible existing agents
    candidates = registry.find_agents_by_capability(task.required_capabilities[0])
    eligible = [a for a in candidates
                if a.department == self.department
                and a.trust_level >= task.minimum_trust_level
                and a.status == "active"]

    if eligible:
        agent = eligible[0]  # registry sorts by trust_level DESC
        return AgentAssignment(..., hired_temporary=False)

    # Step 3: Hire temporary if dept policy allows
    config = DEPT_CONFIG[self.department]
    if config["can_hire_temporary"] and task.risk_level in ("low", "medium"):
        agent_id = registry.hire_temporary_agent(
            name=f"temp-{task.task_type}-{uuid4().hex[:6]}",
            role=task.task_type,
            department=self.department,
            capabilities=task.required_capabilities,
            task_description=task.description,
        )
        permission_manager.grant_permission(agent_id, self._min_permissions(task))
        return AgentAssignment(..., hired_temporary=True)

    # Step 4: No eligible agent, no hiring allowed → escalate
    raise NoEligibleAgentError(
        f"dept={self.department} task_type={task.task_type} "
        f"min_trust={task.minimum_trust_level}"
    )
```

### 7.3 Future reputation hooks (not implemented, structure only)

```python
@dataclass
class DepartmentPerformanceState:
    department: str
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    avg_duration_ms: float = 0.0
    # Plan D: these feed into reputation system
    success_rate: float = 0.0           # computed post-execution
    top_performing_agents: list[str] = field(default_factory=list)
    historical_failures: list[dict] = field(default_factory=list)
```

**Dependency imports:** `models`, `registry`, `permission_manager`. Never imports `unified_isolation_runtime` or `architect_core`.

---

## 8. `AgentDispatcher` — `core/architect/agent_dispatcher.py`

**Single responsibility:** Execute one `AgentAssignment` via `execute_isolated()`. Return `DispatchResult`. Nothing else.

### 8.1 Execution flow

```python
async def dispatch(self, assignment: AgentAssignment, plan_id: str) -> DispatchResult:

    # Security: verify permissions at dispatch time (not just at planning time)
    required_perm = TASK_TYPE_TO_PERMISSION[assignment.task.task_type]
    if not permission_manager.has_permission(assignment.assigned_agent_id, required_perm):
        return DispatchResult(success=False, error="permission_denied_at_dispatch", ...)

    # Build forensic execution context
    ctx = ExecutionContext(
        correlation_id=f"{plan_id}:{assignment.task.task_id}",
        trace_id=str(uuid4()),
        preserve_forensics=(assignment.task.risk_level in ("high", "critical")),
    )

    # THE ONLY EXECUTION PATH — no exceptions to this rule
    payload = ExecutionPayload(
        command=assignment.task.payload.get("command"),
        code=assignment.task.payload.get("code"),
        timeout_seconds=assignment.task.timeout_seconds,
        environment=assignment.task.payload.get("environment", {}),
    )

    result = await unified_runtime.execute_isolated(
        payload=payload,
        policy=assignment.task.isolation_policy,
        ctx=ctx,
        minimum_security_score=RISK_TO_MIN_SECURITY_SCORE[assignment.task.risk_level],
        requires_forensics=(assignment.task.risk_level == "critical"),
    )

    # Enforce output size limits
    output = (result.output or "")[:MAX_DISPATCH_OUTPUT_BYTES]
    error  = (result.error  or "")[:MAX_DISPATCH_ERROR_BYTES] if result.error else None

    # Cleanup: terminate temporary agents after their task completes
    if assignment.hired_temporary:
        try:
            registry.terminate_temporary_agent(assignment.assigned_agent_id)
            permission_manager.revoke_all_for_agent(assignment.assigned_agent_id)
        except Exception:
            pass  # log but never fail the dispatch result

    return DispatchResult(
        task_id=assignment.task.task_id,
        plan_id=plan_id,
        agent_id=assignment.assigned_agent_id,
        success=result.success,
        output=output,
        error=error,
        exit_code=result.exit_code,
        tier_used=result.tier_used,
        security_score=result.negotiation.security_score if result.negotiation else 0,
        fallback_level=result.negotiation.fallback_level if result.negotiation else 0,
        duration_ms=result.duration_ms,
        execution_id=result.execution_id,
        correlation_id=ctx.correlation_id,
        trace_id=ctx.trace_id,
        reputation_delta=0.0,  # Plan D hook
    )
```

### 8.2 Hardening constants

```python
MAX_DISPATCH_OUTPUT_BYTES = 512 * 1024   # 512 KB
MAX_DISPATCH_ERROR_BYTES  = 64  * 1024   # 64 KB
```

### 8.3 Retry logic

```python
async def dispatch_with_retry(
    self, assignment: AgentAssignment, plan_id: str
) -> DispatchResult:
    policy = assignment.task.retry_policy
    for attempt in range(policy.max_retries + 1):
        result = await self.dispatch(assignment, plan_id)
        if result.success or not policy.retry_on_failure:
            return result
    return result  # final attempt result, success=False
```

**Dependency imports:** `models`, `unified_isolation_runtime`, `permission_manager`, `registry`. Never imports `architect_core` or `department_architect`.

---

## 9. `ExternalAgentIntegration` — `core/architect/external_agent_integration.py`

**Single responsibility:** Gate for external agents (agency-agents, The Architect, etc.) entering Nexus. Multi-step quarantine onboarding.

### 9.1 Onboarding pipeline

```python
async def onboard_external_agent(
    self,
    agent_spec: dict,          # {name, code, capabilities, description, source_url?}
    requested_department: str,
) -> ExternalAgentOnboardResult:

    # Step 1: AST Security scan
    if agent_spec.get("code"):
        scan = ast_engine.scan(agent_spec["code"], filename=agent_spec["name"])
        if scan.action == "BLOCK":
            return ExternalAgentOnboardResult(
                success=False, reason="ast_blocked", scan_id=scan.scan_id
            )

    # Step 2: Behavioral sandbox evaluation (STRICT_ISOLATION always)
    sandbox_result = await unified_runtime.execute_isolated(
        payload=ExecutionPayload(code=agent_spec.get("code", "pass")),
        policy=IsolationPolicy.STRICT_ISOLATION,
        ctx=ExecutionContext(preserve_forensics=True),
    )
    if not sandbox_result.success:
        return ExternalAgentOnboardResult(
            success=False, reason="sandbox_rejected",
            execution_id=sandbox_result.execution_id,
        )

    # Step 3: Register with QUARANTINE status + minimum trust
    agent_id = registry.register_agent(
        name=agent_spec["name"],
        role="external_agent",
        department=requested_department,
        trust_level=10,                   # minimum — READ_ONLY equivalent
        permissions=["FS_READ", "DB_READ"],
        source="external",
        status="quarantine",              # custom status, not "active" yet
    )

    # Step 4: Log onboarding event
    audit_logger.log_event(
        vm_id="system",
        event_type="EXTERNAL_AGENT_ONBOARDED",
        severity="WARNING",
        description=f"External agent {agent_spec['name']} in quarantine",
        metadata={
            "agent_id": agent_id,
            "source": agent_spec.get("source_url", "unknown"),
            "scan_id": scan.scan_id if agent_spec.get("code") else None,
        },
        origin_component="external_agent_integration",
    )

    return ExternalAgentOnboardResult(
        success=True,
        agent_id=agent_id,
        status="quarantine",
        next_step="manual_review_required",
    )
```

### 9.2 Promotion from quarantine

Requires explicit human approval (via `ApprovalSystem`). Only ArchitectCore can promote a quarantined agent to `active` status. Trust level elevation is manual and incremental.

```python
async def promote_from_quarantine(
    self, agent_id: str, approved_by: str, new_trust_level: int
) -> bool:
    # Requires approval + only ArchitectCore can call this
    ...
```

---

## 10. Execution Context — always required

Every dispatch carries a full `ExecutionContext`:

```python
ctx = ExecutionContext(
    execution_id=str(uuid4()),      # auto-generated, unique per dispatch
    correlation_id=f"{plan_id}:{task_id}",  # links plan → task → dispatch
    trace_id=str(uuid4()),          # for distributed tracing (Plan E)
    preserve_forensics=True,        # for high/critical risk tasks
)
```

This propagates into: IsolationAuditLogger, UnifiedIsolationRuntime, vm_events table, and ExecutionResult. Every DispatchResult carries all three IDs.

---

## 11. Hierarchical Agent Registry Entries

These agents are registered in `NexusAgentRegistry` at system startup:

```python
ARCHITECT_AGENTS = [
    {"agent_id": "nexus-architect-core",    "trust_level": 100, "department": "engineering"},
    {"agent_id": "dept-arch-engineering",   "trust_level": 70,  "department": "engineering"},
    {"agent_id": "dept-arch-security",      "trust_level": 85,  "department": "security"},
    {"agent_id": "dept-arch-frontend",      "trust_level": 70,  "department": "frontend"},
    {"agent_id": "dept-arch-research",      "trust_level": 70,  "department": "research"},
    {"agent_id": "dept-arch-runtime",       "trust_level": 85,  "department": "runtime"},
    {"agent_id": "dept-arch-repairs",       "trust_level": 70,  "department": "repairs"},
]
```

---

## 12. Full Execution Flow

```
User: "Build a REST endpoint that validates JWT tokens"
        ↓
AgentTaskPlanner.plan()
  AI → {task_type: "code_generate", complexity: "moderate", risk: "medium"}
  Deterministic → subtasks: [task_api (code_generate), task_review (security_scan, depends_on=task_api)]
  → TaskPlan(plan_id="p-001", subtasks=[task_api, task_review], requires_approval=False)
        ↓
ArchitectCore.orchestrate(plan, requestor_id)
  Gate 1: requires_approval=False → skip
  Gate 2: requestor has FS_READ → ok for medium risk
  Gate 3: DAG → wave1=[task_api], wave2=[task_review]
  Gate 4: "engineering" and "security" depts exist → ok
        ↓
  Wave 1: route task_api → DepartmentArchitect("engineering")
        ↓
  DepartmentArchitect("engineering").assign(task_api)
    find_agents_by_capability("code_generation") → [agent-forge-01 trust=80]
    eligible: 80 >= 50 (medium min) ✓
    → AgentAssignment(agent="agent-forge-01", hired_temporary=False)
        ↓
  AgentDispatcher.dispatch(assignment)
    verify has_permission("agent-forge-01", "FS_WRITE") → ✓
    ctx = ExecutionContext(correlation_id="p-001:task_api", preserve_forensics=False)
    execute_isolated(policy=SAFE_DEGRADATION, min_score=40)
    → DispatchResult(success=True, tier=DOCKER_HARDENED, score=70, execution_id="e-001")
        ↓
  Wave 2: route task_review → DepartmentArchitect("security")
    find_agents_by_capability("security_analysis") → []
    can_hire_temporary=False for security dept
    → raises NoEligibleAgentError
    ArchitectCore: skipped_tasks=["task_review"], continue (medium risk, no fail-fast)
        ↓
OrchestrationResult(
  overall_success=True,
  completed=[DispatchResult(task_api, success=True, score=70)],
  skipped=["task_review"],
  isolation_summary={tier: "DOCKER_HARDENED", score: 70, fallbacks: 0},
  audit_chain=["evt-001", "evt-002"],
  performance_report={},        # Plan D hook
  recommended_agents=[],        # Plan D hook
)
```

---

## 13. Dependency Direction (enforced, no exceptions)

```
models.py               → no project imports (stdlib only)
agent_task_planner.py   → models, AI cascade
architect_core.py       → models, agent_task_planner, department_architect,
                          agent_dispatcher, permission_manager, approval_system,
                          isolation_audit_logger
department_architect.py → models, registry, permission_manager
agent_dispatcher.py     → models, unified_isolation_runtime, permission_manager, registry
external_agent_integration.py → models, ast_engine, unified_isolation_runtime,
                                 registry, approval_system, isolation_audit_logger
```

`agent_dispatcher.py` never imports from `architect_core` or `department_architect`.
`department_architect.py` never imports from `architect_core` or `agent_dispatcher`.
No circular imports.

---

## 14. Future Hooks — Plan D

These are stubs — defined but not implemented:

| Hook | Location | Purpose |
|---|---|---|
| `reputation_delta` | `DispatchResult` | Per-task performance signal |
| `performance_snapshot` | `TaskPlan` | Baseline for plan-level metrics |
| `performance_report` | `OrchestrationResult` | Aggregated agent performance |
| `recommended_agents` | `OrchestrationResult` | Agents that exceeded baseline |
| `expected_performance_score` | `AgentAssignment` | Pre-execution baseline |
| `DepartmentPerformanceState` | `department_architect.py` | Per-dept success/failure tracking |
| `success_rate` | `DepartmentPerformanceState` | Rolling success rate |
| `promote_from_quarantine()` | `external_agent_integration.py` | Trust elevation for external agents |

---

## 15. File Count Summary

| File | New / Modified |
|---|---|
| `core/architect/__init__.py` | New |
| `core/architect/models.py` | New |
| `core/architect/agent_task_planner.py` | New |
| `core/architect/architect_core.py` | New |
| `core/architect/department_architect.py` | New |
| `core/architect/agent_dispatcher.py` | New |
| `core/architect/external_agent_integration.py` | New |
| **Total** | **7 new files** |

No existing file is modified.
