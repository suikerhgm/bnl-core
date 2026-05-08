"""
QuarantineDecisionEngine — maps risk levels to concrete actions and integrates
with Nexus BNL security infrastructure.

Decision matrix:
    SAFE        → allow execution
    LOW         → allow + monitor (log finding)
    MEDIUM      → sandbox restrict (RESTRICTED_EXECUTION mode)
    HIGH        → quarantine (FULL_QUARANTINE mode)
    CRITICAL    → block execution + notify security department
    BLACKLISTED → block + emergency isolation + forensic snapshot + rollback evaluation

Integration hooks (stubs if systems not available):
    - SandboxManager: route to appropriate sandbox mode
    - SecurityPolicyEngine: log violation
    - PermissionManager: revoke agent execution permission
    - RecoveryGuardian: trigger forensic snapshot
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.ast_security.behavioral_risk_scorer import RiskAssessment
from core.ast_security.dangerous_patterns import RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class QuarantineDecision:
    """The action decided for a scanned code artifact."""
    scan_id:          str
    risk_level:       str
    action:           str         # ALLOW | MONITOR | SANDBOX | QUARANTINE | BLOCK | EMERGENCY
    sandbox_mode:     Optional[str]  # None or sandbox mode string
    block_execution:  bool
    notify_security:  bool
    create_snapshot:  bool
    revoke_agent:     bool
    reasoning:        List[str] = field(default_factory=list)
    timestamp:        str = field(default_factory=lambda: _now())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id":         self.scan_id,
            "risk_level":      self.risk_level,
            "action":          self.action,
            "sandbox_mode":    self.sandbox_mode,
            "block_execution": self.block_execution,
            "notify_security": self.notify_security,
            "create_snapshot": self.create_snapshot,
            "revoke_agent":    self.revoke_agent,
            "reasoning":       self.reasoning,
            "timestamp":       self.timestamp,
        }


# Action mapping per risk level
_ACTION_MAP = {
    RiskLevel.SAFE:        ("ALLOW",     None,                False, False, False, False),
    RiskLevel.LOW:         ("MONITOR",   None,                False, False, False, False),
    RiskLevel.MEDIUM:      ("SANDBOX",   "RESTRICTED_EXECUTION", False, True,  False, False),
    RiskLevel.HIGH:        ("QUARANTINE","FULL_QUARANTINE",   True,  True,  False, False),
    RiskLevel.CRITICAL:    ("BLOCK",     "FULL_QUARANTINE",   True,  True,  True,  False),
    RiskLevel.BLACKLISTED: ("EMERGENCY", "FULL_QUARANTINE",   True,  True,  True,  True),
}


class QuarantineDecisionEngine:
    """Maps RiskAssessment → QuarantineDecision and executes integration hooks."""

    def decide(
        self,
        assessment: RiskAssessment,
        agent_id: Optional[str] = None,
    ) -> QuarantineDecision:
        """Determine action and execute side effects."""
        row = _ACTION_MAP.get(assessment.risk_level, _ACTION_MAP[RiskLevel.CRITICAL])
        action, sandbox_mode, block, notify, snapshot, revoke = row

        decision = QuarantineDecision(
            scan_id=assessment.scan_id,
            risk_level=assessment.risk_level,
            action=action,
            sandbox_mode=sandbox_mode,
            block_execution=block,
            notify_security=notify,
            create_snapshot=snapshot,
            revoke_agent=revoke,
            reasoning=list(assessment.reasoning),
        )

        # Execute integration hooks
        if notify:
            self._notify_security(assessment, agent_id)
        if snapshot:
            self._create_forensic_snapshot(assessment)
        if revoke and agent_id:
            self._revoke_agent_permissions(agent_id, assessment)
        if assessment.risk_level == RiskLevel.BLACKLISTED:
            self._emergency_protocol(assessment, agent_id)

        level = assessment.risk_level
        logger.log(
            logging.CRITICAL if block else logging.WARNING if notify else logging.INFO,
            "[AST] Decision: %s → %s (score=%d)", level, action, assessment.final_score,
        )
        return decision

    # ── Integration hooks ──────────────────────────────────────────────────────

    @staticmethod
    def _notify_security(assessment: RiskAssessment, agent_id: Optional[str]) -> None:
        try:
            from core.security.capability_guard import get_guard
            guard = get_guard()
            guard.log_security_event(
                event_type=f"AST_THREAT_{assessment.risk_level}",
                description=(
                    f"AST scan detected {assessment.risk_level} threat "
                    f"(score={assessment.final_score})"
                ),
                agent_id=agent_id,
                severity="CRITICAL" if assessment.final_score >= 76 else "WARNING",
                metadata={"scan_id": assessment.scan_id, "score": assessment.final_score,
                          "reasoning": assessment.reasoning[:3]},
            )
        except Exception as exc:
            logger.debug("[AST] Security notify failed: %s", exc)

    @staticmethod
    def _create_forensic_snapshot(assessment: RiskAssessment) -> None:
        try:
            from core.recovery.snapshot_manager import get_snapshot_manager
            get_snapshot_manager().create_snapshot(
                label=f"ast_threat_{assessment.risk_level}",
                created_by="ast_security_engine",
                notes=f"Auto-snapshot: AST {assessment.risk_level} threat detected scan={assessment.scan_id[:8]}",
            )
            logger.info("[AST] Forensic snapshot created for scan %s", assessment.scan_id[:8])
        except Exception as exc:
            logger.debug("[AST] Forensic snapshot failed: %s", exc)

    @staticmethod
    def _revoke_agent_permissions(agent_id: str, assessment: RiskAssessment) -> None:
        try:
            from core.security.capability_guard import get_guard
            get_guard().isolate(
                agent_id,
                reason=f"AST BLACKLISTED: score={assessment.final_score}",
                by="ast_security_engine",
            )
            logger.critical("[AST] Agent %s isolated by AST engine", agent_id)
        except Exception as exc:
            logger.debug("[AST] Agent revoke failed: %s", exc)

    @staticmethod
    def _emergency_protocol(assessment: RiskAssessment, agent_id: Optional[str]) -> None:
        """Full emergency response for BLACKLISTED code."""
        logger.critical(
            "[AST] EMERGENCY PROTOCOL: BLACKLISTED code scan_id=%s score=%d",
            assessment.scan_id[:8], assessment.final_score,
        )
        try:
            from core.recovery.recovery_guardian import get_recovery_guardian
            guardian = get_recovery_guardian()
            # Force an immediate health check + auto-snapshot
            guardian._auto_snapshot()
        except Exception as exc:
            logger.debug("[AST] Emergency guardian hook failed: %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
