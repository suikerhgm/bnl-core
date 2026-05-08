# core/architect/models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

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
    tier_used: Optional[IsolationTier]
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


# ── Architect-level execution context ──────────────────────────────────────────
# Distinct from core.isolation_abstraction.isolation_driver.ExecutionContext
# This is the high-level orchestration context, not the runtime isolation context.

@dataclass
class ArchitectExecutionContext:
    """High-level orchestration context. Propagates through the full pipeline."""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "anonymous"
    requested_capabilities: list[str] = field(default_factory=list)
    isolation_policy: Optional[IsolationPolicy] = None   # None = let planner decide
    trust_level: int = 50                                 # requestor trust (0–100)
    risk_score: int = 0                                   # computed during planning
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parent_execution_id: Optional[str] = None            # for nested orchestrations
    audit_refs: list[str] = field(default_factory=list)  # event_ids from audit logger


@dataclass
class ArchitectExecutionResult:
    """Final consolidated result returned to the caller."""
    # Identity
    execution_id: str
    plan_id: str
    correlation_id: str
    trace_id: str

    # Outcome
    success: bool
    outputs: list[str]                    # collected outputs from all completed tasks
    error_summary: Optional[str]          # None if success

    # Agents & runtimes used
    agents_used: list[str]                # agent_ids that ran tasks
    runtimes_used: list[str]              # tier names (DOCKER_HARDENED, PROCESS_JAIL, etc.)
    fallback_chain: list[dict]            # [{task_id, requested_tier, actual_tier, level}]

    # Security & audit
    security_events: list[dict]           # from isolation layer
    audit_refs: list[str]                 # execution_ids + correlation_ids
    avg_security_score: int

    # Timing
    execution_time_ms: int
    task_count: int
    failed_task_count: int
    skipped_task_count: int

    # Repair hooks (Plan D)
    repair_attempts: list[dict] = field(default_factory=list)   # always [] for now
