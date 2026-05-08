"""
core.recovery — Safe Restore System for Nexus BNL.

Public API:
    get_snapshot_manager()   — create/validate/sign/list snapshots
    get_restore_manager()    — restore/emergency_restore/partial_restore
    get_rollback_engine()    — automatic rollback on critical failure
    get_recovery_guardian()  — background health monitoring daemon
    get_audit_log()          — immutable chained-hash audit trail
    IntegrityValidator       — SHA256 verification + corruption detection
    SafeCheckpoint           — SAFE/STABLE/TRUSTED checkpoint marking
"""

from core.recovery.immutable_audit_log import ImmutableAuditLog, get_audit_log
from core.recovery.integrity_validator import IntegrityValidator, IntegrityReport, CRITICAL_FILES
from core.recovery.snapshot_manager import SnapshotManager, get_snapshot_manager
from core.recovery.safe_checkpoint import SafeCheckpoint
from core.recovery.restore_manager import RestoreManager, get_restore_manager
from core.recovery.rollback_engine import RollbackEngine, get_rollback_engine
from core.recovery.recovery_guardian import RecoveryGuardian, get_recovery_guardian

__all__ = [
    "ImmutableAuditLog", "get_audit_log",
    "IntegrityValidator", "IntegrityReport", "CRITICAL_FILES",
    "SnapshotManager", "get_snapshot_manager",
    "SafeCheckpoint",
    "RestoreManager", "get_restore_manager",
    "RollbackEngine", "get_rollback_engine",
    "RecoveryGuardian", "get_recovery_guardian",
]
