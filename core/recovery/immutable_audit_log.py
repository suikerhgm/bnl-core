"""
ImmutableAuditLog — tamper-evident, append-only audit trail for Nexus BNL recovery events.

Uses a chained hash scheme: each row stores the SHA256 of the previous row's hash,
creating a blockchain-like chain. Tampering with any past row breaks the chain.

DB: data/nexus_recovery.db
Tables: recovery_audit (chained log), forensic_events (preserved evidence)

Usage:
    log = get_audit_log()
    log.append("SNAPSHOT_CREATED", "snapshot_id=abc", metadata={...})
    ok, broken_at = log.verify_chain()
"""

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/nexus_recovery.db")

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    label             TEXT DEFAULT '',
    status            TEXT DEFAULT 'pending',
    checkpoint_level  TEXT DEFAULT 'NONE',
    sha256_manifest   TEXT DEFAULT '',
    archived_path     TEXT DEFAULT '',
    files_count       INTEGER DEFAULT 0,
    size_bytes        INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by        TEXT DEFAULT 'system',
    notes             TEXT DEFAULT '',
    validated_at      TEXT,
    signed_at         TEXT
);

CREATE TABLE IF NOT EXISTS restore_events (
    event_id          TEXT PRIMARY KEY,
    snapshot_id       TEXT NOT NULL,
    restore_type      TEXT NOT NULL,
    triggered_by      TEXT DEFAULT 'system',
    started_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at      TEXT,
    success           INTEGER DEFAULT 0,
    files_restored    INTEGER DEFAULT 0,
    error_msg         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rollback_events (
    event_id          TEXT PRIMARY KEY,
    trigger_reason    TEXT NOT NULL,
    from_state        TEXT DEFAULT '',
    to_snapshot_id    TEXT,
    started_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at      TEXT,
    success           INTEGER DEFAULT 0,
    error_msg         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS integrity_checks (
    check_id          TEXT PRIMARY KEY,
    snapshot_id       TEXT NOT NULL,
    checked_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    files_checked     INTEGER DEFAULT 0,
    files_ok          INTEGER DEFAULT 0,
    files_corrupted   INTEGER DEFAULT 0,
    files_missing     INTEGER DEFAULT 0,
    result            TEXT DEFAULT 'UNKNOWN',
    details           TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS forensic_events (
    event_id          TEXT PRIMARY KEY,
    event_type        TEXT NOT NULL,
    description       TEXT DEFAULT '',
    evidence_path     TEXT DEFAULT '',
    severity          TEXT DEFAULT 'INFO',
    metadata          TEXT DEFAULT '{}',
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS recovery_audit (
    seq               INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id          TEXT UNIQUE NOT NULL,
    event_type        TEXT NOT NULL,
    description       TEXT DEFAULT '',
    metadata          TEXT DEFAULT '{}',
    row_hash          TEXT NOT NULL,
    prev_hash         TEXT DEFAULT '',
    timestamp         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_snap_status   ON snapshots(status);
CREATE INDEX IF NOT EXISTS idx_snap_level    ON snapshots(checkpoint_level);
CREATE INDEX IF NOT EXISTS idx_re_snapshot   ON restore_events(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_ic_snapshot   ON integrity_checks(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_ra_type       ON recovery_audit(event_type);
"""

_GENESIS_HASH = "0" * 64  # chain starts here


class ImmutableAuditLog:
    """Thread-safe, append-only, chained-hash audit log."""

    _instance: Optional["ImmutableAuditLog"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ImmutableAuditLog":
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
            logger.info("[RECOVERY] ImmutableAuditLog initialized at %s", self._db)

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

    # ── Append (immutable) ─────────────────────────────────────────────────────

    def append(
        self,
        event_type: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append an immutable entry. Returns entry_id."""
        with self._lock:
            entry_id = str(uuid.uuid4())
            meta_json = json.dumps(metadata or {}, sort_keys=True)
            ts = self._now()

            with self._conn() as conn:
                # Get previous hash
                prev = conn.execute(
                    "SELECT row_hash FROM recovery_audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev_hash = prev["row_hash"] if prev else _GENESIS_HASH

                # Compute this row's hash
                payload = f"{entry_id}|{event_type}|{description}|{meta_json}|{ts}|{prev_hash}"
                row_hash = hashlib.sha256(payload.encode()).hexdigest()

                conn.execute(
                    """INSERT INTO recovery_audit
                       (entry_id, event_type, description, metadata, row_hash, prev_hash, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (entry_id, event_type, description, meta_json, row_hash, prev_hash, ts),
                )

        logger.debug("[RECOVERY] Audit appended: %s — %s", event_type, description[:60])
        return entry_id

    # ── Chain verification ─────────────────────────────────────────────────────

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """
        Verify the entire audit chain.
        Returns (ok, broken_at_seq) where broken_at_seq is None if intact.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT seq, entry_id, event_type, description, metadata, row_hash, prev_hash, timestamp "
                "FROM recovery_audit ORDER BY seq ASC"
            ).fetchall()

        if not rows:
            return True, None

        expected_prev = _GENESIS_HASH
        for row in rows:
            payload = (
                f"{row['entry_id']}|{row['event_type']}|{row['description']}|"
                f"{row['metadata']}|{row['timestamp']}|{row['prev_hash']}"
            )
            computed = hashlib.sha256(payload.encode()).hexdigest()
            if computed != row["row_hash"]:
                logger.error("[RECOVERY] Chain broken at seq=%d", row["seq"])
                return False, row["seq"]
            if row["prev_hash"] != expected_prev:
                logger.error("[RECOVERY] Chain link broken at seq=%d", row["seq"])
                return False, row["seq"]
            expected_prev = row["row_hash"]

        return True, None

    def get_audit_tail(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM recovery_audit ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Forensic events ────────────────────────────────────────────────────────

    def log_forensic(
        self,
        event_type: str,
        description: str,
        evidence_path: str = "",
        severity: str = "INFO",
        metadata: Optional[Dict] = None,
    ) -> str:
        eid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO forensic_events
                   (event_id, event_type, description, evidence_path, severity, metadata)
                   VALUES (?,?,?,?,?,?)""",
                (eid, event_type, description, evidence_path,
                 severity, json.dumps(metadata or {})),
            )
        self.append(f"FORENSIC:{event_type}", description, {"evidence_path": evidence_path})
        return eid

    def list_forensic_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM forensic_events ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            audit_rows  = conn.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0]
            snapshots   = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            safe_snaps  = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE checkpoint_level IN ('SAFE','STABLE','TRUSTED')"
            ).fetchone()[0]
            restores    = conn.execute("SELECT COUNT(*) FROM restore_events").fetchone()[0]
            rollbacks   = conn.execute("SELECT COUNT(*) FROM rollback_events").fetchone()[0]
            forensic    = conn.execute("SELECT COUNT(*) FROM forensic_events").fetchone()[0]
        chain_ok, broken_at = self.verify_chain()
        return {
            "audit_entries":   audit_rows,
            "snapshots":       snapshots,
            "safe_snapshots":  safe_snaps,
            "restore_events":  restores,
            "rollback_events": rollbacks,
            "forensic_events": forensic,
            "chain_intact":    chain_ok,
            "chain_broken_at": broken_at,
        }


# ── DB helpers shared across recovery modules ──────────────────────────────────

def get_recovery_db_conn():
    """Raw connection for use by other recovery modules."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Singleton ──────────────────────────────────────────────────────────────────

_log: Optional[ImmutableAuditLog] = None
_log_lock = threading.Lock()


def get_audit_log() -> ImmutableAuditLog:
    global _log
    if _log is None:
        with _log_lock:
            if _log is None:
                _log = ImmutableAuditLog()
    return _log
