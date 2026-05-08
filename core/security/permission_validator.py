"""
PermissionValidator — zero-trust permission enforcement for Nexus BNL agents.

Validates every action before execution:
  1. Check the agent is not isolated
  2. Check the agent holds the required permission
  3. Check the permission's minimum trust level vs the agent's actual level
  4. Emit violation records on any failure

The validator is stateless — all state lives in PermissionManager.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.security.permission_manager import PermissionManager, get_permission_manager
from core.security.permissions import PERM_BY_ID, TrustLevel

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a permission check."""
    allowed: bool
    agent_id: str
    permission_id: str
    reason: str = ""
    # Extra context attached by the validator for the policy engine
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.allowed


# ── Validator ──────────────────────────────────────────────────────────────────

class PermissionValidator:
    """
    Stateless validator that wraps PermissionManager with richer logic:
      - level-based pre-check before hitting the DB
      - structured ValidationResult for downstream consumers
      - bulk validation for multi-permission operations
      - workspace boundary check helpers
    """

    def __init__(self, manager: Optional[PermissionManager] = None) -> None:
        self._mgr = manager or get_permission_manager()

    # ── Single check ───────────────────────────────────────────────────────────

    def validate(
        self,
        agent_id: str,
        permission_id: str,
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """
        Full validation pipeline for one (agent, permission) pair.

        Checks (in order):
          1. Permission exists in catalog
          2. Agent is not isolated
          3. Agent's trust level meets the permission's minimum
          4. Active grant exists in DB
        """
        # 1. Catalog check
        catalog_entry = PERM_BY_ID.get(permission_id)
        if catalog_entry is None:
            return ValidationResult(
                allowed=False,
                agent_id=agent_id,
                permission_id=permission_id,
                reason=f"Unknown permission '{permission_id}'",
            )

        # 2. Isolation check (fast path — no DB round-trip for the grant table)
        if self._mgr.is_isolated(agent_id):
            self._mgr.log_security_event(
                event_type="ACCESS_DENIED",
                description=f"Isolated agent attempted {permission_id}",
                agent_id=agent_id,
                severity="WARNING",
                metadata={"permission_id": permission_id},
            )
            return ValidationResult(
                allowed=False,
                agent_id=agent_id,
                permission_id=permission_id,
                reason="agent_isolated",
            )

        # 3. Trust level pre-check
        min_level = catalog_entry["min_level"]
        if isinstance(min_level, TrustLevel):
            min_level = int(min_level)
        if agent_trust_level < min_level:
            level_name = TrustLevel(min_level).name if min_level in TrustLevel._value2member_map_ else str(min_level)
            return ValidationResult(
                allowed=False,
                agent_id=agent_id,
                permission_id=permission_id,
                reason=f"trust_level_insufficient (agent={agent_trust_level} min={level_name})",
                metadata={"required_level": level_name, "agent_level": agent_trust_level},
            )

        # 4. DB grant check (also writes the permission log)
        allowed = self._mgr.check_permission(agent_id, permission_id, log_check=True)
        reason = "ok" if allowed else "no_active_grant"

        return ValidationResult(
            allowed=allowed,
            agent_id=agent_id,
            permission_id=permission_id,
            reason=reason,
        )

    # ── Bulk check ─────────────────────────────────────────────────────────────

    def validate_all(
        self,
        agent_id: str,
        permission_ids: List[str],
        agent_trust_level: int = 0,
    ) -> Dict[str, ValidationResult]:
        """Validate multiple permissions at once. Returns {permission_id: result}."""
        return {
            pid: self.validate(agent_id, pid, agent_trust_level)
            for pid in permission_ids
        }

    def require_all(
        self,
        agent_id: str,
        permission_ids: List[str],
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """
        Returns a passing result only if ALL permissions are granted.
        Returns the first failure if any check fails.
        """
        for pid in permission_ids:
            result = self.validate(agent_id, pid, agent_trust_level)
            if not result:
                return result
        return ValidationResult(
            allowed=True,
            agent_id=agent_id,
            permission_id=",".join(permission_ids),
            reason="all_granted",
        )

    def require_any(
        self,
        agent_id: str,
        permission_ids: List[str],
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """Returns a passing result if ANY of the permissions is granted."""
        for pid in permission_ids:
            result = self.validate(agent_id, pid, agent_trust_level)
            if result:
                return result
        return ValidationResult(
            allowed=False,
            agent_id=agent_id,
            permission_id=",".join(permission_ids),
            reason="none_granted",
        )

    # ── Workspace boundary ─────────────────────────────────────────────────────

    def validate_filesystem_access(
        self,
        agent_id: str,
        path: str,
        operation: str,
        workspace_root: str,
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """
        Validate filesystem operations with workspace boundary enforcement.
        `operation` must be one of: read, write, delete
        """
        import os
        perm_map = {
            "read":   "filesystem.read",
            "write":  "filesystem.write",
            "delete": "filesystem.delete",
        }
        permission_id = perm_map.get(operation, "filesystem.read")

        # Workspace boundary check — path must be under workspace_root
        try:
            abs_path = os.path.realpath(os.path.abspath(path))
            abs_root = os.path.realpath(os.path.abspath(workspace_root))
            within = abs_path.startswith(abs_root)
        except Exception:
            within = False

        if not within:
            self._mgr.log_security_event(
                event_type="OUT_OF_WORKSPACE",
                description=f"Agent attempted {operation} outside workspace: {path}",
                agent_id=agent_id,
                severity="CRITICAL",
                metadata={"path": path, "workspace_root": workspace_root, "operation": operation},
            )
            return ValidationResult(
                allowed=False,
                agent_id=agent_id,
                permission_id=permission_id,
                reason="out_of_workspace",
                metadata={"path": path, "workspace_root": workspace_root},
            )

        return self.validate(agent_id, permission_id, agent_trust_level)

    def validate_subprocess_spawn(
        self,
        agent_id: str,
        command: str,
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """Validate that an agent may spawn a subprocess."""
        result = self.validate(agent_id, "subprocess.spawn", agent_trust_level)
        if not result:
            self._mgr.log_security_event(
                event_type="UNAUTHORIZED_SUBPROCESS",
                description=f"Agent attempted subprocess without permission: {command[:80]}",
                agent_id=agent_id,
                severity="WARNING",
                metadata={"command": command[:200]},
            )
        return result

    def validate_runtime_operation(
        self,
        agent_id: str,
        operation: str,
        agent_trust_level: int = 0,
    ) -> ValidationResult:
        """Validate runtime.restart or runtime.shutdown."""
        perm = "runtime.shutdown" if operation == "shutdown" else "runtime.restart"
        result = self.validate(agent_id, perm, agent_trust_level)
        if not result:
            self._mgr.log_security_event(
                event_type="UNAUTHORIZED_RUNTIME_OP",
                description=f"Agent attempted runtime.{operation} without permission",
                agent_id=agent_id,
                severity="CRITICAL",
                metadata={"operation": operation},
            )
        return result


# ── Module-level singleton ─────────────────────────────────────────────────────

_validator: Optional[PermissionValidator] = None


def get_validator() -> PermissionValidator:
    global _validator
    if _validator is None:
        _validator = PermissionValidator()
    return _validator
