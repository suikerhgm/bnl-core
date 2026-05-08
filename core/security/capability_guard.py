"""
AgentCapabilityGuard — unified security facade for Nexus BNL.

This is the single entry point for all permission-related operations.
Every component that needs to check, grant, or revoke permissions should
go through this guard, not call PermissionManager directly.

Integration points:
  - Agent Registry: call bootstrap_new_agent() whenever a new agent is registered
  - Execution Engine: call guard() before any privileged operation
  - Runtime Engine: call validate_runtime_op() before restart/shutdown
  - Action Router: call check() before dispatching any action

Architecture:
    AgentCapabilityGuard
        ├── PermissionManager   (storage + audit logs)
        ├── PermissionValidator (rule enforcement)
        └── SecurityPolicyEngine (violation detection + auto-isolation)
"""

import logging
import threading
from typing import Any, Dict, List, Optional

from core.security.permission_manager import PermissionManager, get_permission_manager
from core.security.permission_validator import PermissionValidator, ValidationResult, get_validator
from core.security.policy_engine import SecurityPolicyEngine, get_policy_engine
from core.security.permissions import (
    PERMISSION_CATALOG,
    ZERO_TRUST_DEFAULTS,
    Perm,
    TrustLevel,
    get_permissions_for_level,
)

logger = logging.getLogger(__name__)

# Default workspace root — override at app startup
_WORKSPACE_ROOT = "."


class AgentCapabilityGuard:
    """
    Unified permission facade.

    Usage:
        guard = get_guard()

        # Check a single permission
        if not guard.check("agent_001", Perm.FS_WRITE):
            raise PermissionError("Agent lacks filesystem.write")

        # Validate with full pipeline (raises on denial if strict=True)
        result = guard.guard("agent_001", Perm.PROC_SPAWN, trust_level=30)
        if not result:
            handle_denial(result)

        # Bootstrap a new agent (zero-trust defaults)
        guard.bootstrap_new_agent("agent_001")

        # Elevate an agent to STANDARD level
        guard.elevate("agent_001", TrustLevel.STANDARD, granted_by="admin")
    """

    _instance: Optional["AgentCapabilityGuard"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AgentCapabilityGuard":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._mgr    = get_permission_manager()
            self._val    = get_validator()
            self._policy = get_policy_engine()
            self._initialized = True
            logger.info("[PERMISSION] AgentCapabilityGuard initialized")

    # ── Fast check (no policy evaluation) ─────────────────────────────────────

    def check(self, agent_id: str, permission_id: str) -> bool:
        """
        Quick boolean check. No trust-level pre-check, no policy evaluation.
        Use this in hot paths where speed matters and the trust level is
        already confirmed upstream.
        """
        return self._mgr.check_permission(agent_id, permission_id, log_check=False)

    # ── Full validation + policy evaluation ───────────────────────────────────

    def guard(
        self,
        agent_id: str,
        permission_id: str,
        trust_level: int = 0,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Full pipeline: validate → policy engine → return result.
        The policy engine may trigger auto-isolation as a side effect.
        Always call this for user-facing or privileged operations.
        """
        result = self._val.validate(agent_id, permission_id, agent_trust_level=trust_level)
        self._policy.evaluate(result)
        if not result:
            logger.info("[PERMISSION] DENY %s → %s (%s)", agent_id, permission_id, result.reason)
        return result

    def guard_filesystem(
        self,
        agent_id: str,
        path: str,
        operation: str,
        trust_level: int = 0,
    ) -> ValidationResult:
        """Filesystem check with workspace boundary enforcement."""
        result = self._val.validate_filesystem_access(
            agent_id, path, operation,
            workspace_root=_WORKSPACE_ROOT,
            agent_trust_level=trust_level,
        )
        self._policy.evaluate(result)
        if result.reason == "out_of_workspace":
            self._policy.detect_policy_violation(
                agent_id, "OUT_OF_WORKSPACE",
                f"filesystem.{operation}",
                {"path": path, "operation": operation},
            )
        return result

    def guard_subprocess(
        self,
        agent_id: str,
        command: str,
        trust_level: int = 0,
    ) -> ValidationResult:
        """Subprocess spawn check with immediate-isolation policy."""
        result = self._val.validate_subprocess_spawn(agent_id, command, agent_trust_level=trust_level)
        if not result:
            self._policy.detect_policy_violation(
                agent_id, "UNAUTHORIZED_SUBPROCESS",
                Perm.PROC_SPAWN,
                {"command": command[:200]},
            )
        return result

    def guard_runtime(
        self,
        agent_id: str,
        operation: str,
        trust_level: int = 0,
    ) -> ValidationResult:
        """Runtime restart/shutdown check with immediate-isolation policy."""
        result = self._val.validate_runtime_operation(agent_id, operation, agent_trust_level=trust_level)
        if not result:
            self._policy.detect_policy_violation(
                agent_id, "UNAUTHORIZED_RUNTIME_OP",
                f"runtime.{operation}",
                {"operation": operation},
            )
        return result

    # ── Grant / revoke lifecycle ───────────────────────────────────────────────

    def bootstrap_new_agent(self, agent_id: str) -> List[str]:
        """
        Apply zero-trust defaults to a new agent.
        Must be called immediately after registering any agent.
        """
        granted = self._mgr.bootstrap_agent(agent_id)
        self._mgr.log_security_event(
            event_type="AGENT_BOOTSTRAPPED",
            description=f"Zero-trust defaults applied ({len(granted)} perms)",
            agent_id=agent_id,
            severity="INFO",
            metadata={"permissions": granted},
        )
        return granted

    def elevate(
        self,
        agent_id: str,
        level: TrustLevel,
        granted_by: str = "admin",
    ) -> List[str]:
        """Elevate an agent to a trust level, granting all cumulative permissions."""
        perms = self._mgr.grant_level_permissions(agent_id, level, granted_by=granted_by)
        self._mgr.log_security_event(
            event_type="AGENT_ELEVATED",
            description=f"Agent elevated to {level.name} ({len(perms)} perms)",
            agent_id=agent_id,
            severity="INFO",
            metadata={"level": level.name, "granted_by": granted_by, "permissions": perms},
        )
        logger.info("[PERMISSION] Agent %s elevated to %s by %s", agent_id, level.name, granted_by)
        return perms

    def grant(
        self,
        agent_id: str,
        permission_id: str,
        granted_by: str = "admin",
        expires_at: Optional[str] = None,
    ) -> bool:
        """Grant a single permission."""
        return self._mgr.grant_permission(agent_id, permission_id, granted_by, expires_at)

    def revoke(
        self,
        agent_id: str,
        permission_id: str,
        revoked_by: str = "admin",
    ) -> bool:
        """Revoke a single permission."""
        return self._mgr.revoke_permission(agent_id, permission_id, revoked_by)

    # ── Isolation ──────────────────────────────────────────────────────────────

    def isolate(self, agent_id: str, reason: str, by: str = "admin") -> bool:
        return self._mgr.isolate_agent(agent_id, reason=reason, isolated_by=by)

    def release(self, agent_id: str, by: str = "admin") -> bool:
        return self._mgr.release_agent(agent_id, released_by=by)

    def is_isolated(self, agent_id: str) -> bool:
        return self._mgr.is_isolated(agent_id)

    # ── Introspection ──────────────────────────────────────────────────────────

    def get_permissions(self, agent_id: str) -> List[Dict[str, Any]]:
        """Return all active permissions for an agent with catalog metadata."""
        return self._mgr.get_agent_permissions(agent_id)

    def get_threat_level(self, agent_id: str) -> Dict[str, Any]:
        """Compute the current threat assessment for an agent."""
        return self._policy.compute_threat_level(agent_id)

    def get_security_summary(self) -> Dict[str, Any]:
        """Full security system summary for the dashboard."""
        return self._policy.get_security_summary()

    def get_stats(self) -> Dict[str, Any]:
        return self._mgr.get_stats()

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Return the full permission catalog."""
        return [
            {
                "permission_id": p["permission_id"],
                "category":      p["category"],
                "name":          p["name"],
                "description":   p.get("description", ""),
                "min_level":     TrustLevel(int(p["min_level"])).name
                                 if int(p["min_level"]) in TrustLevel._value2member_map_
                                 else str(p["min_level"]),
                "risk_score":    p["risk_score"],
            }
            for p in PERMISSION_CATALOG
        ]

    def list_security_events(
        self,
        agent_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self._mgr.list_security_events(agent_id=agent_id, severity=severity, limit=limit)

    def list_violations(
        self,
        agent_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self._mgr.list_violations(agent_id=agent_id, resolved=resolved, limit=limit)

    def list_isolated_agents(self) -> List[Dict[str, Any]]:
        return self._mgr.list_isolated_agents()

    def list_permission_logs(
        self,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        return self._mgr.list_permission_logs(agent_id=agent_id, action=action, limit=limit)


# ── Workspace root setter ──────────────────────────────────────────────────────

def set_workspace_root(path: str) -> None:
    """Call this once at app startup with the absolute workspace root path."""
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = path
    logger.info("[PERMISSION] Workspace root set to: %s", path)


# ── Singleton accessor ─────────────────────────────────────────────────────────

_guard: Optional[AgentCapabilityGuard] = None
_guard_lock = threading.Lock()


def get_guard() -> AgentCapabilityGuard:
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = AgentCapabilityGuard()
    return _guard
