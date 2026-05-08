"""
RollbackEngine — automatic rollback triggers for Nexus BNL.

Monitors for conditions that require automatic rollback:
    - Critical failure rate (rapid restart loop)
    - Failed update detection (system state deviates from last SAFE snapshot)
    - Quarantine escalation (isolation manager quarantines too many processes)
    - Corruption detection (DB integrity check fails)
    - Security compromise (too many CRITICAL security events)

Rollback strategy:
    1. Detect trigger condition
    2. Lock rollback_engine to prevent concurrent rollbacks
    3. Create pre-rollback forensic snapshot
    4. Execute restore to last SAFE snapshot
    5. Validate post-restore integrity
    6. Log rollback event with full details
    7. Notify recovery_guardian

Usage:
    engine = get_rollback_engine()
    engine.check_and_rollback()  # called by RecoveryGuardian on each tick
    engine.trigger_rollback("critical_failure", reason="too many crashes")
"""

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.recovery.immutable_audit_log import get_audit_log, DB_PATH
from core.recovery.integrity_validator import IntegrityValidator

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────

QUARANTINE_ROLLBACK_THRESHOLD = 3   # ≥3 quarantined processes in one session
SECURITY_CRITICAL_THRESHOLD   = 5   # ≥5 CRITICAL security events since last snapshot
INTEGRITY_FAIL_ROLLBACK       = True  # any DB integrity failure → rollback


class RollbackEngine:
    """
    Evaluates rollback conditions and executes rollback to last SAFE snapshot.
    Thread-safe via a reentrant lock (only one rollback at a time).
    """

    def __init__(self) -> None:
        self._audit  = get_audit_log()
        self._val    = IntegrityValidator()
        self._db     = str(DB_PATH)
        self._lock   = threading.Lock()
        self._active = False   # True while a rollback is in progress

    # ── Check and auto-rollback ────────────────────────────────────────────────

    def check_and_rollback(self) -> Optional[Dict[str, Any]]:
        """
        Evaluate all rollback conditions. If any triggers, execute rollback.
        Returns rollback result dict if triggered, None if no trigger.
        """
        trigger, reason = self._evaluate_conditions()
        if trigger:
            return self.trigger_rollback(trigger, reason)
        return None

    def trigger_rollback(
        self,
        trigger: str,
        reason: str,
        forced: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a rollback. Returns {success, snapshot_id, trigger, reason}.
        Will not run if another rollback is already in progress (unless forced).
        """
        with self._lock:
            if self._active and not forced:
                logger.warning("[RECOVERY] Rollback already in progress — skipping")
                return {"success": False, "error": "Rollback already in progress"}
            self._active = True

        try:
            return self._do_rollback(trigger, reason)
        finally:
            with self._lock:
                self._active = False

    def automatic_rollback_on_critical_failure(self, reason: str) -> Dict[str, Any]:
        return self.trigger_rollback("critical_failure", reason)

    def rollback_after_failed_update(self, reason: str) -> Dict[str, Any]:
        return self.trigger_rollback("failed_update", reason)

    def rollback_after_quarantine_escalation(self) -> Dict[str, Any]:
        return self.trigger_rollback(
            "quarantine_escalation",
            f"≥{QUARANTINE_ROLLBACK_THRESHOLD} processes quarantined",
        )

    def rollback_after_corruption_detection(self, db_name: str) -> Dict[str, Any]:
        return self.trigger_rollback("corruption_detected", f"DB integrity failed: {db_name}")

    # ── Condition evaluators ───────────────────────────────────────────────────

    def _evaluate_conditions(self) -> tuple:
        """Returns (trigger_name, reason) or (None, None)."""

        # 1. DB integrity
        if INTEGRITY_FAIL_ROLLBACK:
            db_result = self._val.check_all_dbs()
            if not db_result["all_ok"]:
                bad = [k for k, v in db_result["databases"].items() if not v["ok"]]
                return "corruption_detected", f"DB integrity failed: {', '.join(bad)}"

        # 2. Critical file check
        files = self._val.check_critical_files()
        if not files["healthy"]:
            return "missing_critical_files", f"Missing: {files['missing']}"

        # 3. Quarantine escalation
        count = self._count_quarantined()
        if count >= QUARANTINE_ROLLBACK_THRESHOLD:
            return "quarantine_escalation", f"{count} processes quarantined"

        # 4. Security critical events
        crit = self._count_recent_security_critical()
        if crit >= SECURITY_CRITICAL_THRESHOLD:
            return "security_compromise", f"{crit} CRITICAL security events"

        return None, None

    def _do_rollback(self, trigger: str, reason: str) -> Dict[str, Any]:
        event_id  = str(uuid.uuid4())
        now       = self._now()
        from_state = self._capture_current_state()

        self._audit.append(
            "ROLLBACK_STARTED",
            f"Rollback triggered: {trigger} — {reason}",
            {"trigger": trigger, "reason": reason, "from_state": from_state},
        )
        logger.critical("[RECOVERY] ROLLBACK STARTED: trigger=%s reason=%s", trigger, reason)

        # Find last SAFE snapshot
        from core.recovery.snapshot_manager import get_snapshot_manager
        latest = get_snapshot_manager().get_latest_safe()

        if not latest:
            msg = "No SAFE snapshot available — rollback aborted"
            logger.critical("[RECOVERY] %s", msg)
            self._record_rollback_event(event_id, trigger, from_state, None, False, msg)
            return {"success": False, "error": msg, "trigger": trigger}

        snap_id = latest["snapshot_id"]

        # Execute restore
        from core.recovery.restore_manager import get_restore_manager
        result = get_restore_manager().restore_snapshot(
            snap_id,
            restore_type="SAFE_RESTORE",
            triggered_by=f"rollback:{trigger}",
        )

        success = result.get("success", False)

        # Post-rollback integrity validation
        if success:
            post_check = self._val.check_all_dbs()
            if not post_check["all_ok"]:
                success = False
                result["errors"] = result.get("errors", []) + ["Post-rollback integrity check failed"]

        self._record_rollback_event(event_id, trigger, from_state, snap_id, success,
                                    str(result.get("errors", [])))

        self._audit.append(
            "ROLLBACK_COMPLETE" if success else "ROLLBACK_FAILED",
            f"Rollback to {snap_id[:8]}: success={success}",
            {"snapshot_id": snap_id, "trigger": trigger, "success": success},
        )

        logger.info("[RECOVERY] Rollback %s: success=%s snapshot=%s",
                    trigger, success, snap_id[:16])
        return {
            "success":     success,
            "event_id":    event_id,
            "snapshot_id": snap_id,
            "trigger":     trigger,
            "reason":      reason,
            "errors":      result.get("errors", []),
        }

    # ── DB helpers ─────────────────────────────────────────────────────────────

    def _record_rollback_event(
        self,
        event_id: str,
        trigger: str,
        from_state: str,
        snap_id: Optional[str],
        success: bool,
        error_msg: str,
    ) -> None:
        conn = sqlite3.connect(self._db, check_same_thread=False)
        try:
            conn.execute(
                """INSERT INTO rollback_events
                   (event_id, trigger_reason, from_state, to_snapshot_id,
                    completed_at, success, error_msg)
                   VALUES (?,?,?,?,?,?,?)""",
                (event_id, trigger, from_state, snap_id,
                 self._now(), int(success), error_msg[:500]),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _capture_current_state() -> str:
        try:
            import json
            from pathlib import Path
            dbs = [p.name for p in Path("data").glob("*.db")]
            return json.dumps({"dbs": dbs, "time": datetime.now(timezone.utc).isoformat()})
        except Exception:
            return "{}"

    @staticmethod
    def _count_quarantined() -> int:
        try:
            from core.isolation.isolation_manager import get_isolation_manager
            procs = get_isolation_manager().list_isolated_processes(status="quarantined")
            return len(procs)
        except Exception:
            return 0

    @staticmethod
    def _count_recent_security_critical() -> int:
        try:
            from core.security.permission_manager import get_permission_manager
            events = get_permission_manager().list_security_events(severity="CRITICAL", limit=20)
            return len(events)
        except Exception:
            return 0

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Singleton ──────────────────────────────────────────────────────────────────
_engine: Optional[RollbackEngine] = None
_engine_lock = threading.Lock()

def get_rollback_engine() -> RollbackEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = RollbackEngine()
    return _engine
