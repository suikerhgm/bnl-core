"""
core.sandbox — Sandbox System for Nexus BNL.

Public API:
    get_sandbox_manager()     — SandboxManager singleton (main entry point)
    SandboxMode               — execution mode enum
    SandboxStatus             — lifecycle status enum
    get_audit_logger()        — SandboxAuditLogger singleton
"""

from core.sandbox.sandbox_environment import SandboxMode, SandboxStatus, SandboxEnvironment
from core.sandbox.sandbox_audit_logger import SandboxAuditLogger, get_audit_logger
from core.sandbox.sandbox_manager import SandboxManager, get_sandbox_manager
from core.sandbox.sandbox_filesystem_guard import SandboxFilesystemGuard
from core.sandbox.sandbox_network_guard import SandboxNetworkGuard
from core.sandbox.sandbox_process_monitor import SandboxProcessMonitor

__all__ = [
    "SandboxMode",
    "SandboxStatus",
    "SandboxEnvironment",
    "SandboxAuditLogger",
    "get_audit_logger",
    "SandboxManager",
    "get_sandbox_manager",
    "SandboxFilesystemGuard",
    "SandboxNetworkGuard",
    "SandboxProcessMonitor",
]
