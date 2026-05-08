"""
PermissionManager — SQLite-backed storage engine for the Nexus BNL Permission System.

Responsibilities:
  - Persist agent permission grants in `agent_permissions`
  - Write immutable audit rows to `permission_logs`
  - Store security events in `security_events`
  - Store policy violations in `policy_violations`
  - Track isolated agents in `isolated_agents`

Zero-trust contract: every new agent starts with READ_ONLY defaults only.
All elevation requires an explicit grant via grant_permission().

DB file: data/nexus_security.db  (separate from nexus_agents.db for modularity)
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

from core.security.permissions import (
    PERM_BY_ID,
    PERMISSION_CATALOG,
    ZERO_TRUST_DEFAULTS,
    Perm,
    TrustLevel,
    get_permissions_for_level,
)

logger = logging.getLogger(__name__)

DB_PATH = Path("data/nexus_security.db")

# ── DDL ────────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS permissions_catalog (
    permission_id   TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    min_level       INTEGER DEFAULT 0,
    risk_score      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_permissions (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    permission_id   TEXT NOT NULL REFERENCES permissions_catalog(permission_id),
    granted_by      TEXT DEFAULT 'system',
    granted_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at      TEXT,
    revoked_at      TEXT,
    active          INTEGER DEFAULT 1,
    UNIQUE(agent_id, permission_id)
);

CREATE TABLE IF NOT EXISTS permission_logs (
    log_id          TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    permission_id   TEXT NOT NULL,
    action          TEXT NOT NULL,
    performed_by    TEXT DEFAULT 'system',
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    details         TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS security_events (
    event_id        TEXT PRIMARY KEY,
    agent_id        TEXT,
    event_type      TEXT NOT NULL,
    severity        TEXT DEFAULT 'INFO',
    description     TEXT DEFAULT '',
    metadata        TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS policy_violations (
    violation_id    TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    permission_id   TEXT NOT NULL,
    violation_type  TEXT NOT NULL,
    context         TEXT DEFAULT '{}',
    resolved        INTEGER DEFAULT 0,
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS isolated_agents (
    agent_id        TEXT PRIMARY KEY,
    reason          TEXT NOT NULL,
    isolated_by     TEXT DEFAULT 'system',
    isolated_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    released_at     TEXT,
    active          INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_ap_agent      ON agent_permissions(agent_id);
CREATE INDEX IF NOT EXISTS idx_ap_active     ON agent_permissions(active);
CREATE INDEX IF NOT EXISTS idx_pl_agent      ON permission_logs(agent_id);
CREATE INDEX IF NOT EXISTS idx_pl_ts         ON permission_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_se_agent      ON security_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_se_severity   ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_se_ts         ON security_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_pv_agent      ON policy_violations(agent_id);
CREATE INDEX IF NOT EXISTS idx_pv_resolved   ON policy_violations(resolved);
CREATE INDEX IF NOT EXISTS idx_ia_active     ON isolated_agents(active);
"""


# ── Manager ────────────────────────────────────────────────────────────────────

class PermissionManager:
    """
    Thread-safe singleton managing all permission storage for Nexus BNL.
    """

    _instance: Optional["PermissionManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PermissionManager":
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
            self._db_path = str(DB_PATH)
            self._apply_schema()
            self._seed_catalog()
            self._initialized = True
            logger.info("[PERMISSION] PermissionManager initialized at %s", self._db_path)

    # ── Internal helpers ───────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _apply_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_DDL)

    def _seed_catalog(self) -> None:
        with self._conn() as conn:
            for p in PERMISSION_CATALOG:
                conn.execute(
                    """INSERT OR IGNORE INTO permissions_catalog
                       (permission_id, category, name, description, min_level, risk_score)
                       VALUES (?,?,?,?,?,?)""",
                    (p["permission_id"], p["category"], p["name"],
                     p.get("description", ""), int(p["min_level"]), p["risk_score"]),
                )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Grant / revoke ─────────────────────────────────────────────────────────

    def grant_permission(
        self,
        agent_id: str,
        permission_id: str,
        granted_by: str = "system",
        expires_at: Optional[str] = None,
    ) -> bool:
        """
        Grant a permission to an agent.
        Silently succeeds if already granted (idempotent).
        Returns True on success, False if permission_id is unknown.
        """
        if permission_id not in PERM_BY_ID:
            logger.warning("[PERMISSION] Unknown permission_id '%s' — grant rejected", permission_id)
            return False

        row_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agent_permissions
                   (id, agent_id, permission_id, granted_by, expires_at, active)
                   VALUES (?,?,?,?,?,1)
                   ON CONFLICT(agent_id, permission_id) DO UPDATE SET
                     active=1, granted_by=excluded.granted_by,
                     granted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                     revoked_at=NULL, expires_at=excluded.expires_at""",
                (row_id, agent_id, permission_id, granted_by, expires_at),
            )
            self._write_log(conn, agent_id, permission_id, "GRANT", granted_by)

        logger.info("[PERMISSION] GRANT %s → %s (by %s)", permission_id, agent_id, granted_by)
        return True

    def revoke_permission(
        self,
        agent_id: str,
        permission_id: str,
        revoked_by: str = "system",
    ) -> bool:
        """Revoke an active permission. Returns True if a row was affected."""
        with self._conn() as conn:
            cur = conn.execute(
                """UPDATE agent_permissions
                   SET active=0, revoked_at=?
                   WHERE agent_id=? AND permission_id=? AND active=1""",
                (self._now(), agent_id, permission_id),
            )
            affected = cur.rowcount > 0
            if affected:
                self._write_log(conn, agent_id, permission_id, "REVOKE", revoked_by)

        if affected:
            logger.info("[PERMISSION] REVOKE %s from %s (by %s)", permission_id, agent_id, revoked_by)
        return affected

    def grant_level_permissions(
        self,
        agent_id: str,
        level: TrustLevel,
        granted_by: str = "system",
    ) -> List[str]:
        """Grant all permissions associated with a trust level (cumulative)."""
        perms = get_permissions_for_level(level)
        for p in perms:
            self.grant_permission(agent_id, p, granted_by=granted_by)
        logger.info("[PERMISSION] Level %s granted to %s (%d perms)", level.name, agent_id, len(perms))
        return perms

    def bootstrap_agent(self, agent_id: str) -> List[str]:
        """
        Apply zero-trust defaults to a brand-new agent.
        Called by the AgentCapabilityGuard whenever a new agent is registered.
        """
        for p in ZERO_TRUST_DEFAULTS:
            self.grant_permission(agent_id, p, granted_by="zero_trust_bootstrap")
        logger.info("[PERMISSION] Zero-trust bootstrap applied to %s (%d perms)",
                    agent_id, len(ZERO_TRUST_DEFAULTS))
        return ZERO_TRUST_DEFAULTS

    # ── Check ──────────────────────────────────────────────────────────────────

    def check_permission(
        self,
        agent_id: str,
        permission_id: str,
        log_check: bool = True,
    ) -> bool:
        """
        Return True if the agent currently holds an active, non-expired permission.
        Always logs CHECK_PASS / CHECK_FAIL when log_check=True.
        """
        # Isolated agents are denied everything
        if self.is_isolated(agent_id):
            if log_check:
                with self._conn() as conn:
                    self._write_log(conn, agent_id, permission_id, "CHECK_FAIL",
                                    details={"reason": "agent_isolated"})
            return False

        with self._conn() as conn:
            row = conn.execute(
                """SELECT id FROM agent_permissions
                   WHERE agent_id=? AND permission_id=? AND active=1
                   AND (expires_at IS NULL OR expires_at > ?)""",
                (agent_id, permission_id, self._now()),
            ).fetchone()
            allowed = row is not None
            if log_check:
                action = "CHECK_PASS" if allowed else "CHECK_FAIL"
                self._write_log(conn, agent_id, permission_id, action)

        return allowed

    def get_agent_permissions(self, agent_id: str) -> List[Dict[str, Any]]:
        """Return all active permissions for an agent, enriched with catalog metadata."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT ap.permission_id, ap.granted_by, ap.granted_at, ap.expires_at,
                          pc.category, pc.name, pc.risk_score, pc.min_level
                   FROM agent_permissions ap
                   LEFT JOIN permissions_catalog pc ON ap.permission_id = pc.permission_id
                   WHERE ap.agent_id=? AND ap.active=1
                   ORDER BY pc.category, ap.permission_id""",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Logging ────────────────────────────────────────────────────────────────

    @staticmethod
    def _write_log(
        conn,
        agent_id: str,
        permission_id: str,
        action: str,
        performed_by: str = "system",
        details: Optional[Dict] = None,
    ) -> None:
        conn.execute(
            """INSERT INTO permission_logs
               (log_id, agent_id, permission_id, action, performed_by, details)
               VALUES (?,?,?,?,?,?)""",
            (str(uuid.uuid4()), agent_id, permission_id,
             action, performed_by, json.dumps(details or {})),
        )

    def log_security_event(
        self,
        event_type: str,
        description: str,
        agent_id: Optional[str] = None,
        severity: str = "INFO",
        metadata: Optional[Dict] = None,
    ) -> str:
        """Write a security event. Returns the new event_id."""
        event_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO security_events
                   (event_id, agent_id, event_type, severity, description, metadata)
                   VALUES (?,?,?,?,?,?)""",
                (event_id, agent_id, event_type, severity,
                 description, json.dumps(metadata or {})),
            )
        logger.info("[SECURITY] [%s] %s | agent=%s", severity, description, agent_id)
        return event_id

    def record_violation(
        self,
        agent_id: str,
        permission_id: str,
        violation_type: str,
        context: Optional[Dict] = None,
    ) -> str:
        """Record a policy violation. Returns the new violation_id."""
        vid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO policy_violations
                   (violation_id, agent_id, permission_id, violation_type, context)
                   VALUES (?,?,?,?,?)""",
                (vid, agent_id, permission_id, violation_type, json.dumps(context or {})),
            )
        logger.warning("[VIOLATION] %s — agent=%s perm=%s", violation_type, agent_id, permission_id)
        return vid

    # ── Isolation ──────────────────────────────────────────────────────────────

    def isolate_agent(
        self,
        agent_id: str,
        reason: str,
        isolated_by: str = "policy_engine",
    ) -> bool:
        """
        Isolate an agent: mark it blocked and emit a CRITICAL security event.
        An isolated agent fails ALL permission checks regardless of grants.
        """
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO isolated_agents (agent_id, reason, isolated_by, active)
                   VALUES (?,?,?,1)
                   ON CONFLICT(agent_id) DO UPDATE SET
                     reason=excluded.reason, isolated_by=excluded.isolated_by,
                     isolated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                     released_at=NULL, active=1""",
                (agent_id, reason, isolated_by),
            )
        self.log_security_event(
            event_type="AGENT_ISOLATED",
            description=f"Agent {agent_id} isolated: {reason}",
            agent_id=agent_id,
            severity="CRITICAL",
            metadata={"reason": reason, "isolated_by": isolated_by},
        )
        logger.critical("[SECURITY] AGENT ISOLATED: %s — %s", agent_id, reason)
        return True

    def release_agent(self, agent_id: str, released_by: str = "admin") -> bool:
        """Remove isolation from an agent."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE isolated_agents SET active=0, released_at=? WHERE agent_id=? AND active=1",
                (self._now(), agent_id),
            )
            ok = cur.rowcount > 0
        if ok:
            self.log_security_event(
                event_type="AGENT_RELEASED",
                description=f"Agent {agent_id} released from isolation by {released_by}",
                agent_id=agent_id,
                severity="INFO",
            )
        return ok

    def is_isolated(self, agent_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM isolated_agents WHERE agent_id=? AND active=1", (agent_id,)
            ).fetchone()
        return row is not None

    # ── Query helpers ──────────────────────────────────────────────────────────

    def list_security_events(
        self,
        agent_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id=?"); params.append(agent_id)
        if severity:
            clauses.append("severity=?"); params.append(severity)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM security_events {where} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def list_violations(
        self,
        agent_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id=?"); params.append(agent_id)
        if resolved is not None:
            clauses.append("resolved=?"); params.append(int(resolved))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM policy_violations {where} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def list_isolated_agents(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM isolated_agents WHERE active=1 ORDER BY isolated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_permission_logs(
        self,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id=?"); params.append(agent_id)
        if action:
            clauses.append("action=?"); params.append(action)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM permission_logs {where} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total_grants  = conn.execute("SELECT COUNT(*) FROM agent_permissions WHERE active=1").fetchone()[0]
            total_revoked = conn.execute("SELECT COUNT(*) FROM agent_permissions WHERE active=0").fetchone()[0]
            total_events  = conn.execute("SELECT COUNT(*) FROM security_events").fetchone()[0]
            critical_evts = conn.execute("SELECT COUNT(*) FROM security_events WHERE severity='CRITICAL'").fetchone()[0]
            violations    = conn.execute("SELECT COUNT(*) FROM policy_violations WHERE resolved=0").fetchone()[0]
            isolated      = conn.execute("SELECT COUNT(*) FROM isolated_agents WHERE active=1").fetchone()[0]
            check_fails   = conn.execute("SELECT COUNT(*) FROM permission_logs WHERE action='CHECK_FAIL'").fetchone()[0]
            check_pass    = conn.execute("SELECT COUNT(*) FROM permission_logs WHERE action='CHECK_PASS'").fetchone()[0]
        return {
            "active_grants":    total_grants,
            "revoked_grants":   total_revoked,
            "security_events":  total_events,
            "critical_events":  critical_evts,
            "open_violations":  violations,
            "isolated_agents":  isolated,
            "check_failures":   check_fails,
            "check_passes":     check_pass,
        }

    def compute_agent_risk_score(self, agent_id: str) -> int:
        """
        Compute a 0–100 risk score for an agent based on its active permissions.
        Higher = more powerful (not necessarily dangerous, but worth monitoring).
        """
        perms = self.get_agent_permissions(agent_id)
        if not perms:
            return 0
        total = sum(p.get("risk_score", 1) for p in perms)
        # Normalize: max possible is sum of all risk scores
        max_possible = sum(p["risk_score"] for p in PERMISSION_CATALOG)
        return min(100, int((total / max_possible) * 100))


# ── Singleton accessor ─────────────────────────────────────────────────────────

_manager: Optional[PermissionManager] = None
_manager_lock = threading.Lock()


def get_permission_manager() -> PermissionManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = PermissionManager()
    return _manager
