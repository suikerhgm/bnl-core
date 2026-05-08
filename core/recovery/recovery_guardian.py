"""
RecoveryGuardian — background daemon for continuous system health monitoring.

Runs periodic health checks and triggers automatic rollback when needed.

Check schedule (configurable):
    db_integrity_interval_sec   = 300   (5 min)
    critical_files_interval_sec = 600   (10 min)
    rollback_check_interval_sec = 60    (1 min)
    auto_snapshot_interval_sec  = 3600  (1 hr)

Triggers auto-rollback on:
    - DB corruption
    - Missing critical files
    - Quarantine escalation
    - Security compromise

Triggers auto-snapshot on schedule.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.recovery.immutable_audit_log import get_audit_log
from core.recovery.integrity_validator import IntegrityValidator
from core.recovery.rollback_engine import get_rollback_engine

logger = logging.getLogger(__name__)

_DB_CHECK_INTERVAL    = 300
_FILES_CHECK_INTERVAL = 600
_ROLLBACK_INTERVAL    = 60
_AUTO_SNAP_INTERVAL   = 3600


class RecoveryGuardian:
    """Background daemon that continuously monitors system health."""

    _instance: Optional["RecoveryGuardian"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "RecoveryGuardian":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._class_lock:
            if self._initialized:
                return
            self._audit     = get_audit_log()
            self._val       = IntegrityValidator()
            self._rollback  = get_rollback_engine()
            self._stop      = threading.Event()
            self._thread: Optional[threading.Thread] = None
            self._last_db_check    = 0.0
            self._last_file_check  = 0.0
            self._last_rollback_ck = 0.0
            self._last_auto_snap   = 0.0
            self.health_status: Dict[str, Any] = {"status": "not_started"}
            self._initialized = True
            logger.info("[RUNTIME_GUARD] RecoveryGuardian initialized")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="nexus-recovery-guardian",
            daemon=True,
        )
        self._thread.start()
        logger.info("[RUNTIME_GUARD] RecoveryGuardian started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now - self._last_db_check >= _DB_CHECK_INTERVAL:
                    self._check_db_integrity()
                    self._last_db_check = now

                if now - self._last_file_check >= _FILES_CHECK_INTERVAL:
                    self._check_critical_files()
                    self._last_file_check = now

                if now - self._last_rollback_ck >= _ROLLBACK_INTERVAL:
                    self._check_rollback()
                    self._last_rollback_ck = now

                if now - self._last_auto_snap >= _AUTO_SNAP_INTERVAL:
                    self._auto_snapshot()
                    self._last_auto_snap = now

            except Exception as exc:
                logger.error("[RUNTIME_GUARD] Guardian loop error: %s", exc)

            self._stop.wait(timeout=10)

    def _check_db_integrity(self) -> None:
        result = self._val.check_all_dbs()
        self.health_status["db_integrity"] = result
        if not result["all_ok"]:
            bad = [k for k, v in result["databases"].items() if not v["ok"]]
            self._audit.append("DB_INTEGRITY_FAIL", f"DB integrity failed: {bad}")
            logger.critical("[RUNTIME_GUARD] DB integrity failure: %s", bad)

    def _check_critical_files(self) -> None:
        result = self._val.check_critical_files()
        self.health_status["critical_files"] = result
        if not result["healthy"]:
            self._audit.append("CRITICAL_FILES_MISSING", f"Missing: {result['missing']}")
            logger.critical("[RUNTIME_GUARD] Critical files missing: %s", result["missing"])

    def _check_rollback(self) -> None:
        result = self._rollback.check_and_rollback()
        if result:
            self.health_status["last_rollback"] = result
            logger.warning("[RUNTIME_GUARD] Auto-rollback executed: %s", result.get("trigger"))

    def _auto_snapshot(self) -> None:
        try:
            from core.recovery.snapshot_manager import get_snapshot_manager
            snap = get_snapshot_manager().create_snapshot(
                label="auto_guardian",
                created_by="recovery_guardian",
                notes="Scheduled auto-snapshot by RecoveryGuardian",
            )
            logger.info("[RUNTIME_GUARD] Auto-snapshot created: %s", snap.get("snapshot_id", "?")[:16])
            self.health_status["last_auto_snapshot"] = snap.get("snapshot_id")
        except Exception as exc:
            logger.error("[RUNTIME_GUARD] Auto-snapshot failed: %s", exc)

    def get_health(self) -> Dict[str, Any]:
        return {
            "running":       self._thread is not None and self._thread.is_alive(),
            "health_status": self.health_status,
            "last_db_check":    _ago(self._last_db_check),
            "last_file_check":  _ago(self._last_file_check),
            "last_rollback_ck": _ago(self._last_rollback_ck),
            "last_auto_snap":   _ago(self._last_auto_snap),
        }


def _ago(ts: float) -> Optional[str]:
    if ts == 0:
        return None
    sec = int(time.monotonic() - ts)
    return f"{sec}s ago"


_guardian: Optional[RecoveryGuardian] = None
_guardian_lock = threading.Lock()

def get_recovery_guardian() -> RecoveryGuardian:
    global _guardian
    if _guardian is None:
        with _guardian_lock:
            if _guardian is None:
                _guardian = RecoveryGuardian()
    return _guardian
