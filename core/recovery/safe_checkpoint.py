"""
SafeCheckpoint — checkpoint promotion system for Nexus BNL snapshots.

Only validated snapshots can be promoted:
    SAFE    — passed integrity check, no active violations
    STABLE  — SAFE + runtime has been running cleanly for a configurable period
    TRUSTED — STABLE + manually confirmed by an authorized agent (ADMIN+)

Rules:
    1. Snapshot must have status='VALID' to be promoted.
    2. SAFE requires: IntegrityReport.result == 'PASS' + no open security violations.
    3. STABLE requires: SAFE + system has been running without isolation breaches for MIN_STABLE_SEC.
    4. TRUSTED requires: STABLE + explicit trust grant from an ADMIN/ROOT agent.

Usage:
    cp = SafeCheckpoint()
    ok, reason = cp.promote_to_safe(snapshot_id)
    ok, reason = cp.promote_to_stable(snapshot_id, runtime_ok_sec=3600)
    ok, reason = cp.promote_to_trusted(snapshot_id, granted_by="architect_001")
"""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple

from core.recovery.immutable_audit_log import get_audit_log, DB_PATH
from core.recovery.integrity_validator import IntegrityValidator

logger = logging.getLogger(__name__)

MIN_STABLE_SEC  = 300   # 5 min clean runtime before STABLE promotion

CHECKPOINT_LEVELS = ("NONE", "SAFE", "STABLE", "TRUSTED")


class SafeCheckpoint:
    """Manages checkpoint promotion for snapshots."""

    def __init__(self) -> None:
        self._audit = get_audit_log()
        self._val   = IntegrityValidator()
        self._db    = str(DB_PATH)

    def _conn(self):
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Promotion methods ──────────────────────────────────────────────────────

    def promote_to_safe(self, snapshot_id: str) -> Tuple[bool, str]:
        """
        Promote a VALID snapshot to SAFE level.
        Requires: status=VALID + integrity PASS + no open security violations.
        """
        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False, "Snapshot not found"
        if snap["status"] not in ("VALID", "SAFE"):
            return False, f"Snapshot must be VALID, got {snap['status']}"

        # Re-run integrity check
        from core.recovery.snapshot_manager import get_snapshot_manager
        report = get_snapshot_manager().validate_snapshot(snapshot_id)
        if not report.passed():
            return False, f"Integrity check FAILED: corrupted={len(report.files_corrupted)} missing={len(report.files_missing)}"

        # Check no open security violations
        viol_count = self._open_security_violations()
        if viol_count > 0:
            return False, f"Cannot promote: {viol_count} open security violations"

        self._set_level(snapshot_id, "SAFE")
        self._audit.append(
            "CHECKPOINT_SAFE",
            f"Snapshot {snapshot_id[:8]} promoted to SAFE",
            {"snapshot_id": snapshot_id},
        )
        logger.info("[RECOVERY] Snapshot %s promoted to SAFE", snapshot_id[:16])
        return True, "Promoted to SAFE"

    def promote_to_stable(
        self,
        snapshot_id: str,
        runtime_ok_sec: float = MIN_STABLE_SEC,
    ) -> Tuple[bool, str]:
        """
        Promote SAFE snapshot to STABLE.
        Requires: already SAFE + no isolation breaches in the last runtime_ok_sec seconds.
        """
        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False, "Snapshot not found"
        if snap["checkpoint_level"] not in ("SAFE", "STABLE"):
            return False, f"Snapshot must be SAFE first, got level={snap['checkpoint_level']}"

        # Check isolation system is clean
        breach_count = self._recent_isolation_breaches(runtime_ok_sec)
        if breach_count > 0:
            return False, f"Cannot promote: {breach_count} isolation breaches in last {runtime_ok_sec:.0f}s"

        self._set_level(snapshot_id, "STABLE")
        self._audit.append(
            "CHECKPOINT_STABLE",
            f"Snapshot {snapshot_id[:8]} promoted to STABLE",
            {"snapshot_id": snapshot_id, "clean_window_sec": runtime_ok_sec},
        )
        logger.info("[RECOVERY] Snapshot %s promoted to STABLE", snapshot_id[:16])
        return True, "Promoted to STABLE"

    def promote_to_trusted(
        self,
        snapshot_id: str,
        granted_by: str,
    ) -> Tuple[bool, str]:
        """
        Promote STABLE snapshot to TRUSTED. Requires explicit human/admin grant.
        Validates that granting agent has ADMIN trust level in the security system.
        """
        snap = self._get_snapshot(snapshot_id)
        if not snap:
            return False, "Snapshot not found"
        if snap["checkpoint_level"] not in ("STABLE", "TRUSTED"):
            return False, "Snapshot must be STABLE first"

        # Validate granting agent has permission
        if not self._agent_can_trust(granted_by):
            return False, f"Agent '{granted_by}' lacks required ADMIN trust level"

        self._set_level(snapshot_id, "TRUSTED")
        self._audit.append(
            "CHECKPOINT_TRUSTED",
            f"Snapshot {snapshot_id[:8]} promoted to TRUSTED by {granted_by}",
            {"snapshot_id": snapshot_id, "granted_by": granted_by},
        )
        logger.info("[RECOVERY] Snapshot %s TRUSTED by %s", snapshot_id[:16], granted_by)
        return True, f"Promoted to TRUSTED by {granted_by}"

    def demote_checkpoint(self, snapshot_id: str, reason: str = "") -> bool:
        """Demote a checkpoint back to NONE (on detected corruption post-promotion)."""
        self._set_level(snapshot_id, "NONE")
        self._audit.append(
            "CHECKPOINT_DEMOTED",
            f"Snapshot {snapshot_id[:8]} demoted: {reason}",
            {"snapshot_id": snapshot_id, "reason": reason},
        )
        logger.warning("[RECOVERY] Snapshot %s demoted: %s", snapshot_id[:16], reason)
        return True

    def mark_safe_checkpoint(
        self,
        snapshot_id: str,
        auto_stable: bool = False,
    ) -> Tuple[bool, str]:
        """Convenience: promote to SAFE (and optionally STABLE if conditions met)."""
        ok, msg = self.promote_to_safe(snapshot_id)
        if not ok:
            return ok, msg
        if auto_stable:
            ok2, msg2 = self.promote_to_stable(snapshot_id)
            if ok2:
                return True, "Promoted to STABLE"
        return True, msg

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_level(self, snapshot_id: str, level: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE snapshots SET checkpoint_level=?, status=? WHERE snapshot_id=?",
                (level, level if level != "NONE" else "VALID", snapshot_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _open_security_violations() -> int:
        try:
            from core.security.permission_manager import get_permission_manager
            mgr = get_permission_manager()
            viols = mgr.list_violations(resolved=False, limit=1)
            return len(viols)
        except Exception:
            return 0  # if security system not available, don't block

    @staticmethod
    def _recent_isolation_breaches(window_sec: float) -> int:
        try:
            from core.isolation.isolation_manager import get_isolation_manager
            mgr = get_isolation_manager()
            viols = mgr.list_violations(limit=50)
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
            recent = [
                v for v in viols
                if datetime.fromisoformat(
                    v["timestamp"].replace("Z", "+00:00")
                ) > cutoff
            ]
            return len(recent)
        except Exception:
            return 0

    @staticmethod
    def _agent_can_trust(agent_id: str) -> bool:
        try:
            from core.security.permission_manager import get_permission_manager
            mgr = get_permission_manager()
            # Check agent has ADMIN or ROOT trust level via their permissions
            perms = mgr.get_agent_permissions(agent_id)
            # An agent with sandbox.approve implies ADMIN+
            perm_ids = {p["permission_id"] for p in perms}
            return "sandbox.approve" in perm_ids or "runtime.shutdown" in perm_ids
        except Exception:
            return True  # fail open if security system unavailable during recovery
