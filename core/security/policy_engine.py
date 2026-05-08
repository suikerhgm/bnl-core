"""
SecurityPolicyEngine — automated violation detection and response for Nexus BNL.

Responsibilities:
  - Define and evaluate security policies as declarative rules
  - Detect policy violations from permission check failures and security events
  - Auto-isolate agents that trip defined thresholds
  - Compute per-agent threat levels
  - Expose hooks for future integration with AI immune system and sandbox quarantine

Policies currently enforced:
  WORKSPACE_BOUNDARY     — any out-of-workspace access → immediate isolation
  UNAUTHORIZED_SUBPROCESS — subprocess.spawn without permission → immediate isolation
  UNAUTHORIZED_RUNTIME   — runtime.shutdown/restart without permission → immediate isolation
  CHECK_FAIL_BURST       — N consecutive CHECK_FAILs in T seconds → escalate to WARNING
  ESCALATION_LOCKOUT     — X WARNING events on same agent in T minutes → isolate

Future integration points (stubs):
  - ai_immune_system_hook()   → will notify the immune system on CRITICAL events
  - sandbox_quarantine_hook() → will push agent to sandbox quarantine queue
  - runtime_guardian_hook()   → will signal the runtime guardian to watch the agent
"""

import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.security.permission_manager import PermissionManager, get_permission_manager
from core.security.permission_validator import PermissionValidator, ValidationResult, get_validator
from core.security.permissions import Perm

logger = logging.getLogger(__name__)


# ── Policy thresholds (tunable) ────────────────────────────────────────────────

CHECK_FAIL_BURST_WINDOW_SEC  = 60    # window for counting consecutive failures
CHECK_FAIL_BURST_THRESHOLD   = 5     # N failures in window → WARNING event
ESCALATION_WINDOW_SEC        = 300   # 5 min window for escalation counting
ESCALATION_LOCKOUT_THRESHOLD = 3     # X WARNINGs in window → isolate


# ── Policy rule definitions ────────────────────────────────────────────────────

class PolicyTrigger:
    """Event types that the policy engine watches."""
    OUT_OF_WORKSPACE        = "OUT_OF_WORKSPACE"
    UNAUTHORIZED_SUBPROCESS = "UNAUTHORIZED_SUBPROCESS"
    UNAUTHORIZED_RUNTIME_OP = "UNAUTHORIZED_RUNTIME_OP"
    CHECK_FAIL_BURST        = "CHECK_FAIL_BURST"
    ESCALATION_LOCKOUT      = "ESCALATION_LOCKOUT"


# ── Engine ─────────────────────────────────────────────────────────────────────

class SecurityPolicyEngine:
    """
    Stateful policy engine that maintains sliding-window counters per agent
    and enforces isolation rules automatically.
    """

    def __init__(
        self,
        manager: Optional[PermissionManager] = None,
        validator: Optional[PermissionValidator] = None,
    ) -> None:
        self._mgr = manager or get_permission_manager()
        self._validator = validator or get_validator()
        self._lock = threading.Lock()

        # Sliding windows: agent_id → deque of (timestamp_float,)
        self._fail_windows:  Dict[str, deque] = defaultdict(deque)
        self._warn_windows:  Dict[str, deque] = defaultdict(deque)

    # ── Main dispatch ──────────────────────────────────────────────────────────

    def detect_policy_violation(
        self,
        agent_id: str,
        event_type: str,
        permission_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Evaluate policies for a given event.
        Returns violation_id if a violation was recorded, else None.
        Also triggers auto-isolation when policies require it.

        [POLICY] log prefix used for all decisions made here.
        """
        ctx = context or {}

        # Immediate-isolation policies
        if event_type == PolicyTrigger.OUT_OF_WORKSPACE:
            return self._handle_immediate_isolation(
                agent_id, permission_id,
                violation_type="OUT_OF_WORKSPACE",
                reason=f"Workspace boundary violation: {ctx.get('path', '?')}",
                context=ctx,
            )

        if event_type == PolicyTrigger.UNAUTHORIZED_SUBPROCESS:
            return self._handle_immediate_isolation(
                agent_id, permission_id,
                violation_type="UNAUTHORIZED_SUBPROCESS",
                reason=f"Subprocess spawn without permission: {ctx.get('command', '?')[:60]}",
                context=ctx,
            )

        if event_type == PolicyTrigger.UNAUTHORIZED_RUNTIME_OP:
            return self._handle_immediate_isolation(
                agent_id, permission_id,
                violation_type="UNAUTHORIZED_RUNTIME_OP",
                reason=f"Runtime operation without permission: {ctx.get('operation', '?')}",
                context=ctx,
            )

        # Sliding-window policies
        if event_type == "CHECK_FAIL":
            return self._handle_check_fail(agent_id, permission_id, ctx)

        if event_type == "WARNING":
            return self._handle_warning_escalation(agent_id, ctx)

        return None

    # ── Immediate isolation ────────────────────────────────────────────────────

    def _handle_immediate_isolation(
        self,
        agent_id: str,
        permission_id: str,
        violation_type: str,
        reason: str,
        context: Dict,
    ) -> str:
        vid = self._mgr.record_violation(agent_id, permission_id, violation_type, context)
        logger.warning("[POLICY] Immediate isolation triggered for %s: %s", agent_id, violation_type)
        self._mgr.isolate_agent(agent_id, reason=reason, isolated_by="policy_engine")
        self._ai_immune_system_hook(agent_id, violation_type, context)
        self._sandbox_quarantine_hook(agent_id, violation_type)
        return vid

    # ── Burst-failure window ───────────────────────────────────────────────────

    def _handle_check_fail(
        self, agent_id: str, permission_id: str, context: Dict
    ) -> Optional[str]:
        now = _ts()
        with self._lock:
            dq = self._fail_windows[agent_id]
            dq.append(now)
            # Trim old entries outside the window
            while dq and (now - dq[0]) > CHECK_FAIL_BURST_WINDOW_SEC:
                dq.popleft()
            count = len(dq)

        if count >= CHECK_FAIL_BURST_THRESHOLD:
            logger.warning(
                "[POLICY] CHECK_FAIL burst — agent=%s count=%d/%ds perm=%s",
                agent_id, count, CHECK_FAIL_BURST_WINDOW_SEC, permission_id,
            )
            self._mgr.log_security_event(
                event_type=PolicyTrigger.CHECK_FAIL_BURST,
                description=f"{count} permission failures in {CHECK_FAIL_BURST_WINDOW_SEC}s",
                agent_id=agent_id,
                severity="WARNING",
                metadata={"count": count, "permission_id": permission_id},
            )
            vid = self._mgr.record_violation(
                agent_id, permission_id, "CHECK_FAIL_BURST",
                {"count": count, "window_sec": CHECK_FAIL_BURST_WINDOW_SEC},
            )
            self._handle_warning_escalation(agent_id, {"source": "burst"})
            return vid

        return None

    # ── Warning escalation ─────────────────────────────────────────────────────

    def _handle_warning_escalation(
        self, agent_id: str, context: Dict
    ) -> Optional[str]:
        now = _ts()
        with self._lock:
            dq = self._warn_windows[agent_id]
            dq.append(now)
            while dq and (now - dq[0]) > ESCALATION_WINDOW_SEC:
                dq.popleft()
            count = len(dq)

        if count >= ESCALATION_LOCKOUT_THRESHOLD:
            logger.critical(
                "[POLICY] Escalation lockout — agent=%s warnings=%d/%ds",
                agent_id, count, ESCALATION_WINDOW_SEC,
            )
            reason = f"Escalation lockout: {count} warnings in {ESCALATION_WINDOW_SEC}s"
            self._mgr.isolate_agent(agent_id, reason=reason, isolated_by="policy_engine")
            self._ai_immune_system_hook(agent_id, "ESCALATION_LOCKOUT", context)
            return self._mgr.record_violation(
                agent_id, "escalation", "ESCALATION_LOCKOUT",
                {"warning_count": count, "window_sec": ESCALATION_WINDOW_SEC},
            )

        return None

    # ── Evaluate ValidationResult ──────────────────────────────────────────────

    def evaluate(self, result: ValidationResult) -> None:
        """
        Feed a ValidationResult into the policy engine.
        Called automatically by AgentCapabilityGuard after every validation.
        """
        if result.allowed:
            return

        reason = result.reason
        agent_id = result.agent_id
        permission_id = result.permission_id

        # Map reason → policy trigger
        if reason == "out_of_workspace":
            self.detect_policy_violation(
                agent_id, PolicyTrigger.OUT_OF_WORKSPACE,
                permission_id, result.metadata,
            )
        elif reason == "unauthorized_subprocess":
            self.detect_policy_violation(
                agent_id, PolicyTrigger.UNAUTHORIZED_SUBPROCESS,
                permission_id, result.metadata,
            )
        elif reason == "unauthorized_runtime":
            self.detect_policy_violation(
                agent_id, PolicyTrigger.UNAUTHORIZED_RUNTIME_OP,
                permission_id, result.metadata,
            )
        elif reason in ("no_active_grant", "trust_level_insufficient"):
            self.detect_policy_violation(
                agent_id, "CHECK_FAIL",
                permission_id, result.metadata,
            )

    # ── Threat level ───────────────────────────────────────────────────────────

    def compute_threat_level(self, agent_id: str) -> Dict[str, Any]:
        """
        Compute a composite threat assessment for an agent.
        Returns score (0–100) and label (NONE/LOW/MEDIUM/HIGH/CRITICAL).
        """
        violations   = len(self._mgr.list_violations(agent_id=agent_id, resolved=False))
        events       = self._mgr.list_security_events(agent_id=agent_id, limit=50)
        critical_cnt = sum(1 for e in events if e.get("severity") == "CRITICAL")
        warning_cnt  = sum(1 for e in events if e.get("severity") == "WARNING")
        isolated     = self._mgr.is_isolated(agent_id)
        risk_score   = self._mgr.compute_agent_risk_score(agent_id)

        score = min(100, (
            (violations  * 10) +
            (critical_cnt * 20) +
            (warning_cnt  * 5) +
            (50 if isolated else 0) +
            (risk_score // 5)
        ))

        label = (
            "CRITICAL" if score >= 80 or isolated else
            "HIGH"     if score >= 50 else
            "MEDIUM"   if score >= 20 else
            "LOW"      if score >= 5  else
            "NONE"
        )

        return {
            "agent_id":     agent_id,
            "threat_score": score,
            "threat_level": label,
            "isolated":     isolated,
            "violations":   violations,
            "critical_events": critical_cnt,
            "warning_events":  warning_cnt,
            "risk_score":   risk_score,
        }

    # ── Future integration stubs ───────────────────────────────────────────────

    def _ai_immune_system_hook(
        self,
        agent_id: str,
        event_type: str,
        context: Dict,
    ) -> None:
        """
        [STUB] Notify the AI immune system of a critical security event.
        Future: will enqueue to core/immune/response_queue.
        """
        logger.debug("[POLICY] ai_immune_system_hook: agent=%s event=%s", agent_id, event_type)

    def _sandbox_quarantine_hook(self, agent_id: str, reason: str) -> None:
        """
        [STUB] Push agent to sandbox quarantine queue.
        Future: will call core/sandbox/quarantine_manager.quarantine(agent_id).
        """
        logger.debug("[POLICY] sandbox_quarantine_hook: agent=%s reason=%s", agent_id, reason)

    def _runtime_guardian_hook(self, agent_id: str) -> None:
        """
        [STUB] Signal runtime guardian to monitor this agent's subprocesses.
        Future: will call core/runtime/guardian.watch(agent_id).
        """
        logger.debug("[POLICY] runtime_guardian_hook: agent=%s", agent_id)

    # ── System-wide summary ────────────────────────────────────────────────────

    def get_security_summary(self) -> Dict[str, Any]:
        """Aggregate security health view for the dashboard."""
        isolated = self._mgr.list_isolated_agents()
        violations = self._mgr.list_violations(resolved=False, limit=20)
        events = self._mgr.list_security_events(severity="CRITICAL", limit=20)
        stats = self._mgr.get_stats()

        return {
            "stats": stats,
            "isolated_agents": isolated,
            "open_violations": violations,
            "critical_events": events,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts() -> float:
    return datetime.now(timezone.utc).timestamp()


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[SecurityPolicyEngine] = None
_engine_lock = threading.Lock()


def get_policy_engine() -> SecurityPolicyEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SecurityPolicyEngine()
    return _engine
