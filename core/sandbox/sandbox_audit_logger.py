"""
SandboxAuditLogger — SQLite-backed audit storage for the Nexus BNL Sandbox System.

DB file: data/nexus_sandbox.db

Tables:
    sandboxes          — one row per sandbox instance
    sandbox_events     — all activity events within a sandbox (append-only)
    sandbox_violations — detected policy/behavior violations
    resource_snapshots — periodic CPU/RAM/FS/net snapshots per sandbox
"""

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("data/nexus_sandbox.db")

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sandboxes (
    sandbox_id      TEXT PRIMARY KEY,
    agent_id        TEXT,
    mode            TEXT NOT NULL,
    status          TEXT DEFAULT 'created',
    workspace_path  TEXT,
    risk_score      INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    started_at      TEXT,
    frozen_at       TEXT,
    quarantined_at  TEXT,
    destroyed_at    TEXT,
    pid             INTEGER,
    exit_code       INTEGER,
    metadata        TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sandbox_events (
    event_id        TEXT PRIMARY KEY,
    sandbox_id      TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    severity        TEXT DEFAULT 'INFO',
    description     TEXT DEFAULT '',
    metadata        TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS sandbox_violations (
    violation_id    TEXT PRIMARY KEY,
    sandbox_id      TEXT NOT NULL,
    violation_type  TEXT NOT NULL,
    description     TEXT DEFAULT '',
    risk_delta      INTEGER DEFAULT 10,
    details         TEXT DEFAULT '{}',
    resolved        INTEGER DEFAULT 0,
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS resource_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    sandbox_id      TEXT NOT NULL,
    cpu_percent     REAL DEFAULT 0,
    ram_mb          REAL DEFAULT 0,
    open_files      INTEGER DEFAULT 0,
    child_processes INTEGER DEFAULT 0,
    net_connections INTEGER DEFAULT 0,
    files_written   INTEGER DEFAULT 0,
    files_deleted   INTEGER DEFAULT 0,
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_se_sandbox   ON sandbox_events(sandbox_id);
CREATE INDEX IF NOT EXISTS idx_se_ts        ON sandbox_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_sv_sandbox   ON sandbox_violations(sandbox_id);
CREATE INDEX IF NOT EXISTS idx_rs_sandbox   ON resource_snapshots(sandbox_id);
CREATE INDEX IF NOT EXISTS idx_sb_status    ON sandboxes(status);
CREATE INDEX IF NOT EXISTS idx_sb_agent     ON sandboxes(agent_id);
"""


class SandboxAuditLogger:
    """Thread-safe SQLite audit logger for sandbox events."""

    _instance: Optional["SandboxAuditLogger"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SandboxAuditLogger":
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
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = str(DB_PATH)
            with sqlite3.connect(self._db) as c:
                c.executescript(_DDL)
            self._initialized = True
            logger.info("[SANDBOX] AuditLogger initialized at %s", self._db)

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

    # ── Sandbox CRUD ───────────────────────────────────────────────────────────

    def create_sandbox_record(
        self,
        sandbox_id: str,
        agent_id: Optional[str],
        mode: str,
        workspace_path: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sandboxes
                   (sandbox_id, agent_id, mode, status, workspace_path, metadata)
                   VALUES (?,?,?,?,?,?)""",
                (sandbox_id, agent_id, mode, "created",
                 workspace_path, json.dumps(metadata or {})),
            )

    def update_sandbox(self, sandbox_id: str, **fields) -> None:
        if not fields:
            return
        allowed = {
            "status", "risk_score", "pid", "exit_code",
            "started_at", "frozen_at", "quarantined_at", "destroyed_at",
        }
        safe = {k: v for k, v in fields.items() if k in allowed}
        if not safe:
            return
        parts = ", ".join(f"{k}=?" for k in safe)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE sandboxes SET {parts} WHERE sandbox_id=?",
                list(safe.values()) + [sandbox_id],
            )

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sandboxes WHERE sandbox_id=?", (sandbox_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sandboxes(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status=?"); params.append(status)
        if agent_id:
            clauses.append("agent_id=?"); params.append(agent_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM sandboxes {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ─────────────────────────────────────────────────────────────────

    def log_event(
        self,
        sandbox_id: str,
        event_type: str,
        description: str = "",
        severity: str = "INFO",
        metadata: Optional[Dict] = None,
    ) -> str:
        eid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sandbox_events
                   (event_id, sandbox_id, event_type, severity, description, metadata)
                   VALUES (?,?,?,?,?,?)""",
                (eid, sandbox_id, event_type, severity,
                 description, json.dumps(metadata or {})),
            )
        lvl = logging.CRITICAL if severity == "CRITICAL" else \
              logging.WARNING  if severity == "WARNING"  else logging.INFO
        logger.log(lvl, "[SANDBOX] [%s] %s: %s", severity, event_type, description)
        return eid

    def get_events(
        self,
        sandbox_id: str,
        severity: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses = ["sandbox_id=?"]
        params: List[Any] = [sandbox_id]
        if severity:
            clauses.append("severity=?"); params.append(severity)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM sandbox_events WHERE {' AND '.join(clauses)}"
                f" ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Violations ─────────────────────────────────────────────────────────────

    def record_violation(
        self,
        sandbox_id: str,
        violation_type: str,
        description: str = "",
        risk_delta: int = 10,
        details: Optional[Dict] = None,
    ) -> str:
        vid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sandbox_violations
                   (violation_id, sandbox_id, violation_type, description, risk_delta, details)
                   VALUES (?,?,?,?,?,?)""",
                (vid, sandbox_id, violation_type, description,
                 risk_delta, json.dumps(details or {})),
            )
            conn.execute(
                "UPDATE sandboxes SET risk_score = MIN(100, risk_score + ?) WHERE sandbox_id=?",
                (risk_delta, sandbox_id),
            )
        logger.warning("[SANDBOX_ALERT] VIOLATION %s in %s: %s", violation_type, sandbox_id, description)
        return vid

    def get_violations(self, sandbox_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sandbox_violations WHERE sandbox_id=? ORDER BY timestamp DESC",
                (sandbox_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Resource snapshots ─────────────────────────────────────────────────────

    def record_snapshot(
        self,
        sandbox_id: str,
        cpu_percent: float = 0,
        ram_mb: float = 0,
        open_files: int = 0,
        child_processes: int = 0,
        net_connections: int = 0,
        files_written: int = 0,
        files_deleted: int = 0,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_snapshots
                   (snapshot_id, sandbox_id, cpu_percent, ram_mb, open_files,
                    child_processes, net_connections, files_written, files_deleted)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), sandbox_id, cpu_percent, ram_mb,
                 open_files, child_processes, net_connections, files_written, files_deleted),
            )

    def get_snapshots(self, sandbox_id: str, limit: int = 60) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM resource_snapshots WHERE sandbox_id=? ORDER BY timestamp DESC LIMIT ?",
                (sandbox_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_snapshot(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        snaps = self.get_snapshots(sandbox_id, limit=1)
        return snaps[0] if snaps else None

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total      = conn.execute("SELECT COUNT(*) FROM sandboxes").fetchone()[0]
            active     = conn.execute("SELECT COUNT(*) FROM sandboxes WHERE status IN ('running','frozen')").fetchone()[0]
            quarantine = conn.execute("SELECT COUNT(*) FROM sandboxes WHERE status='quarantined'").fetchone()[0]
            completed  = conn.execute("SELECT COUNT(*) FROM sandboxes WHERE status='completed'").fetchone()[0]
            destroyed  = conn.execute("SELECT COUNT(*) FROM sandboxes WHERE status='destroyed'").fetchone()[0]
            violations = conn.execute("SELECT COUNT(*) FROM sandbox_violations WHERE resolved=0").fetchone()[0]
            events     = conn.execute("SELECT COUNT(*) FROM sandbox_events").fetchone()[0]
            critical   = conn.execute("SELECT COUNT(*) FROM sandbox_events WHERE severity='CRITICAL'").fetchone()[0]
        return {
            "total_sandboxes":    total,
            "active_sandboxes":   active,
            "quarantined":        quarantine,
            "completed":          completed,
            "destroyed":          destroyed,
            "open_violations":    violations,
            "total_events":       events,
            "critical_events":    critical,
        }

    def export_sandbox_logs(self, sandbox_id: str) -> Dict[str, Any]:
        """Full export of all data for a sandbox — used for post-mortem analysis."""
        return {
            "sandbox":    self.get_sandbox(sandbox_id),
            "events":     self.get_events(sandbox_id, limit=1000),
            "violations": self.get_violations(sandbox_id),
            "snapshots":  self.get_snapshots(sandbox_id, limit=1000),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_logger_inst: Optional[SandboxAuditLogger] = None
_logger_lock = threading.Lock()


def get_audit_logger() -> SandboxAuditLogger:
    global _logger_inst
    if _logger_inst is None:
        with _logger_lock:
            if _logger_inst is None:
                _logger_inst = SandboxAuditLogger()
    return _logger_inst
