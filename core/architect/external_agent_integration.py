# core/architect/external_agent_integration.py
"""
ExternalAgentIntegration — gate for external agents (agency-agents, The Architect, etc.)
FASE 1: stubs only — raises NotImplementedError with documented FASE 3 steps.
FASE 3: implement multi-step quarantine onboarding.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExternalAgentOnboardResult:
    success: bool
    agent_id: Optional[str] = None
    status: Optional[str] = None           # "quarantine" | "active"
    reason: Optional[str] = None
    next_step: Optional[str] = None
    execution_id: Optional[str] = None
    scan_id: Optional[str] = None


class ExternalAgentIntegration:
    """
    Gate for external agents entering Nexus. All external agents start in quarantine.
    Promotion requires explicit human approval via ArchitectCore.

    FASE 3 onboarding pipeline:
      1. AST scan of agent_spec["code"]
      2. STRICT_ISOLATION sandbox evaluation via execute_isolated()
      3. Register with trust_level=10, status="quarantine"
      4. Log onboarding event to IsolationAuditLogger
      5. Require human approval to promote to "active"
    """

    async def onboard_external_agent(
        self,
        agent_spec: dict,
        requested_department: str,
    ) -> ExternalAgentOnboardResult:
        """
        FASE 1 stub. Raises NotImplementedError.
        FASE 3: implement AST scan -> sandbox eval -> quarantine registration -> audit log.
        agent_spec keys: name, code (optional), capabilities, description, source_url (optional)
        """
        raise NotImplementedError(
            "ExternalAgentIntegration.onboard_external_agent — implement in FASE 3. "
            "Pipeline: AST scan → STRICT_ISOLATION sandbox → quarantine registration → audit log."
        )

    async def promote_from_quarantine(
        self,
        agent_id: str,
        approved_by: str,
        new_trust_level: int,
    ) -> bool:
        """
        FASE 1 stub. Only ArchitectCore (ROOT trust level) can call this.
        FASE 3: validate approval -> update registry status -> grant new permissions.
        new_trust_level must be 10-50 (incremental elevation, never direct to high trust).
        """
        raise NotImplementedError(
            "ExternalAgentIntegration.promote_from_quarantine — implement in FASE 3. "
            "Requires human approval + ArchitectCore authorization."
        )
