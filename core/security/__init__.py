"""
core.security — Agent Permission & Security System for Nexus BNL.

Public API (import from here):
    get_guard()             — AgentCapabilityGuard singleton (main entry point)
    get_permission_manager() — PermissionManager singleton (storage)
    get_validator()         — PermissionValidator singleton
    get_policy_engine()     — SecurityPolicyEngine singleton
    Perm                    — permission ID constants
    TrustLevel              — trust level enum
    set_workspace_root()    — configure workspace boundary
"""

from core.security.permissions import Perm, TrustLevel, PERMISSION_CATALOG, ZERO_TRUST_DEFAULTS
from core.security.permission_manager import PermissionManager, get_permission_manager
from core.security.permission_validator import PermissionValidator, ValidationResult, get_validator
from core.security.policy_engine import SecurityPolicyEngine, get_policy_engine
from core.security.capability_guard import AgentCapabilityGuard, get_guard, set_workspace_root

__all__ = [
    "Perm",
    "TrustLevel",
    "PERMISSION_CATALOG",
    "ZERO_TRUST_DEFAULTS",
    "PermissionManager",
    "get_permission_manager",
    "PermissionValidator",
    "ValidationResult",
    "get_validator",
    "SecurityPolicyEngine",
    "get_policy_engine",
    "AgentCapabilityGuard",
    "get_guard",
    "set_workspace_root",
]
