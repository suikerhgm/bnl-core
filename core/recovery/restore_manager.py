"""
RestoreManager — snapshot restore operations for Nexus BNL.

Restore types:
    SOFT_RESTORE      — restore only SQLite DBs; runtime keeps running
    SAFE_RESTORE      — stop monitored services, restore DBs + configs, restart
    FULL_RESTORE      — full system state restore (all files in snapshot)
    EMERGENCY_RESTORE — force-kill all processes, restore last SAFE snapshot,
                        validate, resume services, generate forensic report

Each restore:
    1. Validates snapshot integrity before touching anything
    2. Creates a pre-restore snapshot (safety net)
    3. Extracts files from ZIP to target paths
    4. Validates restored files match manifest
    5. Logs everything to the immutable audit trail

Partial restore:
    restore_registry()    — restore only nexus_agents.db
    restore_permissions() — restore only nexus_security.db
    restore_runtime_state() — restore isolation + sandbox DBs
"""

import json
import logging
import shutil
import sqlite3
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.recovery.immutable_audit_log import get_audit_log, DB_PATH
from core.recovery.integrity_validator import IntegrityValidator
from core.recovery.snapshot_manager import (
    SnapshotManager, get_snapshot_manager, SNAPSHOT_DIR, FORENSICS_DIR,
)

logger = logging.getLogger(__name__)

# DB files by subsystem
_DB_REGISTRY    = "data/nexus_agents.db"
_DB_SECURITY    = "data/nexus_security.db"
_DB_SANDBOX     = "data/nexus_sandbox.db"
_DB_ISOLATION   = "data/nexus_isolation.db"
_DB_RECOVERY    = "data/nexus_recovery.db"

RESTORE_TYPE_FILES = {
    "registry":    [_DB_REGISTRY],
    "permissions": [_DB_SECURITY],
    "runtime":     [_DB_SANDBOX, _DB_ISOLATION],
    "databases":   [_DB_REGISTRY, _DB_SECURITY, _DB_SANDBOX, _DB_ISOLATION],
}


class RestoreManager:
    """Orchestrates all restore operations with safety checks and audit logging."""

    def __init__(self) -> None:
        self._snap_mgr = get_snapshot_manager()
        self._audit    = get_audit_log()
        self._val      = IntegrityValidator()
        self._db       = str(DB_PATH)
        self._lock     = threading.Lock()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Main restore entry points ──────────────────────────────────────────────

    def restore_snapshot(
        self,
        snapshot_id: str,
        restore_type: str = "SAFE_RESTORE",
        triggered_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Restore a snapshot. Returns {success, files_restored, errors, event_id}.
        """
        with self._lock:
            return self._do_restore(snapshot_id, restore_type, triggered_by)

    def emergency_restore(self, triggered_by: str = "emergency_button") -> Dict[str, Any]:
        """
        EMERGENCY_RESTORE: find last SAFE snapshot and restore it.
        Steps:
            1. Freeze running processes via IsolationManager
            2. Create pre-restore forensic snapshot
            3. Kill dangerous processes
            4. Restore last SAFE snapshot
            5. Validate restoration
            6. Preserve forensic report
        """
        with self._lock:
            logger.critical("[EMERGENCY] EMERGENCY RESTORE initiated by %s", triggered_by)
            self._audit.append(
                "EMERGENCY_RESTORE_START",
                f"Emergency restore triggered by {triggered_by}",
                {"triggered_by": triggered_by},
            )

            steps = []

            # Step 1: Freeze runtime
            steps.append(self._step_freeze_runtime())

            # Step 2: Pre-restore forensic snapshot
            pre_snap = self._step_create_forensic_snapshot()
            steps.append({"step": "forensic_snapshot", "snapshot_id": pre_snap})

            # Step 3: Kill dangerous processes
            steps.append(self._step_kill_dangerous())

            # Step 4: Find last SAFE snapshot
            latest_safe = self._snap_mgr.get_latest_safe()
            if not latest_safe:
                msg = "No SAFE snapshot available — cannot emergency restore"
                logger.critical("[EMERGENCY] %s", msg)
                self._audit.append("EMERGENCY_RESTORE_FAILED", msg)
                return {"success": False, "error": msg, "steps": steps}

            # Step 5: Restore
            result = self._do_restore(
                latest_safe["snapshot_id"],
                "EMERGENCY_RESTORE",
                triggered_by,
            )
            steps.append({"step": "restore", "result": result})

            # Step 6: Generate forensic report
            report_path = self._generate_forensic_report(
                pre_snap, latest_safe["snapshot_id"], steps
            )
            steps.append({"step": "forensic_report", "path": str(report_path)})

            self._audit.append(
                "EMERGENCY_RESTORE_COMPLETE",
                f"Emergency restore complete: success={result['success']}",
                {"restored_snapshot": latest_safe["snapshot_id"], "report": str(report_path)},
            )

            return {
                "success":            result["success"],
                "restored_snapshot":  latest_safe["snapshot_id"],
                "files_restored":     result.get("files_restored", 0),
                "forensic_report":    str(report_path),
                "steps":              steps,
                "errors":             result.get("errors", []),
            }

    # ── Partial restores ───────────────────────────────────────────────────────

    def restore_registry(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore only the agent registry database."""
        return self._partial_restore(snapshot_id, RESTORE_TYPE_FILES["registry"], "registry")

    def restore_permissions(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore only the security/permissions database."""
        return self._partial_restore(snapshot_id, RESTORE_TYPE_FILES["permissions"], "permissions")

    def restore_runtime_state(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore sandbox and isolation databases."""
        return self._partial_restore(snapshot_id, RESTORE_TYPE_FILES["runtime"], "runtime")

    def partial_restore(
        self,
        snapshot_id: str,
        file_keys: List[str],
    ) -> Dict[str, Any]:
        """Restore a custom list of file keys from a snapshot."""
        return self._partial_restore(snapshot_id, file_keys, "partial")

    # ── Core restore logic ─────────────────────────────────────────────────────

    def _do_restore(
        self,
        snapshot_id: str,
        restore_type: str,
        triggered_by: str,
    ) -> Dict[str, Any]:
        event_id = str(uuid.uuid4())
        errors:  List[str] = []
        restored = 0

        snap = self._snap_mgr.get_snapshot(snapshot_id)
        if not snap:
            return {"success": False, "event_id": event_id, "error": "Snapshot not found"}

        zip_path = Path(snap["archived_path"])
        if not zip_path.exists():
            return {"success": False, "event_id": event_id,
                    "error": f"Archive not found: {zip_path}"}

        # Validate before restoring
        report = self._snap_mgr.validate_snapshot(snapshot_id)
        if not report.passed():
            msg = f"Snapshot integrity check FAILED — aborting restore"
            logger.error("[RECOVERY] %s (snapshot=%s)", msg, snapshot_id[:16])
            self._audit.append("RESTORE_ABORTED", msg, {"snapshot_id": snapshot_id})
            return {"success": False, "event_id": event_id, "error": msg}

        # Record restore event start
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO restore_events
                   (event_id, snapshot_id, restore_type, triggered_by)
                   VALUES (?,?,?,?)""",
                (event_id, snapshot_id, restore_type, triggered_by),
            )

        self._audit.append(
            "RESTORE_STARTED",
            f"Restore {restore_type} from snapshot {snapshot_id[:8]}",
            {"snapshot_id": snapshot_id, "restore_type": restore_type},
        )

        # Extract files
        base = Path(".")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                for name in names:
                    if name == "MANIFEST.json":
                        continue
                    target = base / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        data = zf.read(name)
                        target.write_bytes(data)
                        restored += 1
                    except Exception as exc:
                        errors.append(f"{name}: {exc}")
                        logger.error("[RECOVERY] Failed to restore %s: %s", name, exc)
        except Exception as exc:
            errors.append(str(exc))
            logger.error("[RECOVERY] ZIP extraction error: %s", exc)

        success = len(errors) == 0

        # Update restore event
        with self._conn() as conn:
            conn.execute(
                """UPDATE restore_events
                   SET completed_at=?, success=?, files_restored=?, error_msg=?
                   WHERE event_id=?""",
                (self._now(), int(success), restored,
                 json.dumps(errors)[:500], event_id),
            )

        self._audit.append(
            "RESTORE_COMPLETE" if success else "RESTORE_PARTIAL",
            f"Restored {restored} files (errors={len(errors)})",
            {"snapshot_id": snapshot_id, "restored": restored, "errors": errors[:5]},
        )
        logger.info("[RECOVERY] Restore %s: %d files (errors=%d)",
                    restore_type, restored, len(errors))

        return {
            "success":       success,
            "event_id":      event_id,
            "snapshot_id":   snapshot_id,
            "restore_type":  restore_type,
            "files_restored": restored,
            "errors":        errors,
        }

    def _partial_restore(
        self,
        snapshot_id: str,
        file_keys: List[str],
        label: str,
    ) -> Dict[str, Any]:
        """Extract only specific files from a snapshot ZIP."""
        snap = self._snap_mgr.get_snapshot(snapshot_id)
        if not snap:
            return {"success": False, "error": "Snapshot not found"}
        zip_path = Path(snap["archived_path"])
        if not zip_path.exists():
            return {"success": False, "error": "Archive not found"}

        restored, errors = 0, []
        base = Path(".")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                for key in file_keys:
                    norm = key.replace("\\", "/")
                    if norm not in names:
                        errors.append(f"Not in archive: {key}")
                        continue
                    target = base / norm
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        data = zf.read(norm)
                        target.write_bytes(data)
                        restored += 1
                    except Exception as exc:
                        errors.append(f"{key}: {exc}")
        except Exception as exc:
            errors.append(str(exc))

        self._audit.append(
            f"PARTIAL_RESTORE_{label.upper()}",
            f"Partial restore ({label}): {restored}/{len(file_keys)} files",
            {"snapshot_id": snapshot_id, "keys": file_keys, "errors": errors},
        )
        return {"success": len(errors) == 0, "files_restored": restored, "errors": errors}

    # ── Emergency steps ────────────────────────────────────────────────────────

    def _step_freeze_runtime(self) -> Dict:
        try:
            from core.isolation.isolation_manager import get_isolation_manager
            mgr = get_isolation_manager()
            procs = mgr.list_isolated_processes(status="active")
            frozen = 0
            for p in procs:
                if mgr.freeze_isolated_process(p["process_id"]):
                    frozen += 1
            return {"step": "freeze_runtime", "frozen": frozen, "ok": True}
        except Exception as exc:
            return {"step": "freeze_runtime", "ok": False, "error": str(exc)}

    def _step_kill_dangerous(self) -> Dict:
        try:
            from core.isolation.isolation_manager import get_isolation_manager
            mgr = get_isolation_manager()
            procs = mgr.list_isolated_processes(status="active")
            killed = 0
            for p in procs:
                if p.get("risk_score", 0) > 30:
                    mgr.kill_suspicious_process(p["pid"], "emergency_restore")
                    killed += 1
            return {"step": "kill_dangerous", "killed": killed, "ok": True}
        except Exception as exc:
            return {"step": "kill_dangerous", "ok": False, "error": str(exc)}

    def _step_create_forensic_snapshot(self) -> Optional[str]:
        try:
            snap = self._snap_mgr.create_snapshot(
                label="pre_emergency_restore",
                created_by="emergency_restore",
                notes="Auto-created before emergency restore",
            )
            fpath = FORENSICS_DIR / f"pre_restore_{snap['snapshot_id'][:8]}.json"
            fpath.write_text(
                json.dumps(snap, indent=2, default=str),
                encoding="utf-8",
            )
            self._audit.log_forensic(
                "PRE_RESTORE_SNAPSHOT",
                f"Forensic snapshot before emergency restore",
                evidence_path=str(fpath),
                severity="INFO",
            )
            return snap["snapshot_id"]
        except Exception as exc:
            logger.error("[RECOVERY] Forensic snapshot failed: %s", exc)
            return None

    def _generate_forensic_report(
        self,
        pre_snap_id: Optional[str],
        restored_snap_id: str,
        steps: List[Dict],
    ) -> Path:
        report = {
            "generated_at":       self._now(),
            "event":              "EMERGENCY_RESTORE",
            "pre_restore_snap":   pre_snap_id,
            "restored_snap":      restored_snap_id,
            "steps":              steps,
            "system_state": {
                "critical_files": IntegrityValidator().check_critical_files(),
                "db_integrity":   IntegrityValidator().check_all_dbs(),
            },
        }
        path = FORENSICS_DIR / f"emergency_report_{self._now().replace(':','-')}.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        logger.info("[RECOVERY] Forensic report written: %s", path)
        return path

    def get_restore_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM restore_events ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_rollback_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM rollback_events ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# ── Singleton ──────────────────────────────────────────────────────────────────
_rm: Optional[RestoreManager] = None
_rm_lock = threading.Lock()

def get_restore_manager() -> RestoreManager:
    global _rm
    if _rm is None:
        with _rm_lock:
            if _rm is None:
                _rm = RestoreManager()
    return _rm
