"""
core.isolation — Runtime Isolation System for Nexus BNL.

Public API:
    get_isolation_manager()  — IsolationManager singleton (main entry point)
    IsolationLevel           — SOFT / RESTRICTED / HARD / QUARANTINE / LOCKDOWN
    get_guardian()           — RuntimeGuardian singleton (monitoring daemon)
    LEVEL_LIMITS             — default limit profiles per level
"""

from core.isolation.resource_limiter import IsolationLevel, LEVEL_LIMITS
from core.isolation.runtime_guardian import RuntimeGuardian, get_guardian
from core.isolation.emergency_kill_switch import EmergencyKillSwitch
from core.isolation.process_jail import ProcessJail
from core.isolation.isolation_manager import IsolationManager, get_isolation_manager

__all__ = [
    "IsolationLevel",
    "LEVEL_LIMITS",
    "RuntimeGuardian",
    "get_guardian",
    "EmergencyKillSwitch",
    "ProcessJail",
    "IsolationManager",
    "get_isolation_manager",
]
