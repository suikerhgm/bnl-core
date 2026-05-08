"""
IsolationManager — main public API and SQLite storage for the Nexus BNL Runtime Isolation System.

This is the single entry point for all isolation operations.
Orchestrates: ProcessJail + ResourceLimiter + FilesystemJail + NetworkJail
             + EmergencyKillSwitch + RuntimeGuardian

Usage:
    mgr = get_isolation_manager()
    ctx = mgr.isolate_process(
        pid=proc.pid,
        agent_id="agent_001",
        level="HARD",
        workspace_root="/path/to/workspace",
    )
    # The RuntimeGuardian monitors ctx in the background.
    mgr.destroy_isolation_environment(ctx.process_id)

DB: data/nexus_isolation.db
Tables:
    isolated_processes  — one row per isolation context
    runtime_violations  — all violations detected during monitoring
    resource_usage      — periodic CPU/RAM/process snapshots
    emergency_events    — FREEZE / KILL / QUARANTINE / LOCKDOWN events
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

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.isolation.resource_limiter import IsolationLevel, ResourceLimiter, LEVEL_LIMITS
from core.isolation.filesystem_jail import FilesystemJail
from core.isolation.network_jail import NetworkJail
from core.isolation.process_jail import ProcessJail
from core.isolation.emergency_kill_switch import EmergencyKillSwitch
from core.isolation.runtime_guardian import (
    IsolationContext, RuntimeGuardian, get_guardian,
)

logger = logging.getLogger(__name__)

DB_PATH = Path("data/nexus_isolation.db")

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS isolated_processes (
    process_id      TEXT PRIMARY KEY,
    agent_id        TEXT,
    pid             INTEGER,
    level           TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    workspace_root  TEXT DEFAULT '',
    risk_score      INTEGER DEFAULT 0,
    cpu_limit       REAL DEFAULT 0,
    memory_limit    REAL DEFAULT 0,
    max_subprocesses INTEGER DEFAULT 0,
    max_file_writes  INTEGER DEFAULT 0,
    max_net_conns    INTEGER DEFAULT 0,
    jail_active     INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    frozen_at       TEXT,
    quarantined_at  TEXT,
    terminated_at   TEXT
);

CREATE TABLE IF NOT EXISTS runtime_violations (
    violation_id    TEXT PRIMARY KEY,
    process_id      TEXT NOT NULL,
    agent_id        TEXT,
    violation_type  TEXT NOT NULL,
    description     TEXT DEFAULT '',
    risk_delta      INTEGER DEFAULT 10,
    details         TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS resource_usage (
    usage_id        TEXT PRIMARY KEY,
    process_id      TEXT NOT NULL,
    cpu_percent     REAL DEFAULT 0,
    memory_mb       REAL DEFAULT 0,
    subprocesses    INTEGER DEFAULT 0,
    file_handles    INTEGER DEFAULT 0,
    net_connections INTEGER DEFAULT 0,
    risk_score      INTEGER DEFAULT 0,
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS emergency_events (
    event_id        TEXT PRIMARY KEY,
    process_id      TEXT,
    agent_id        TEXT,
    action          TEXT NOT NULL,
    description     TEXT DEFAULT '',
    severity        TEXT DEFAULT 'INFO',
    resolved        INTEGER DEFAULT 0,
    timestamp       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_ip_status    ON isolated_processes(status);
CREATE INDEX IF NOT EXISTS idx_ip_agent     ON isolated_processes(agent_id);
CREATE INDEX IF NOT EXISTS idx_rv_process   ON runtime_violations(process_id);
CREATE INDEX IF NOT EXISTS idx_rv_ts        ON runtime_violations(timestamp);
CREATE INDEX IF NOT EXISTS idx_ru_process   ON resource_usage(process_id);
CREATE INDEX IF NOT EXISTS idx_ee_process   ON emergency_events(process_id);
CREATE INDEX IF NOT EXISTS idx_ee_severity  ON emergency_events(severity);
"""


class IsolationManager:
    """
    Singleton orchestrator for the full isolation system.
    Creates and manages isolation contexts, drives the RuntimeGuardian daemon.
    """

    _instance: Optional["IsolationManager"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "IsolationManager":
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
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = str(DB_PATH)
            with sqlite3.connect(self._db) as c:
                c.executescript(_DDL)

            # Build kill switch with callbacks wired to our DB
            self._kill_switch = EmergencyKillSwitch(
                on_quarantine=self._handle_quarantine,
                on_lockdown=self._handle_lockdown,
                on_event=self._persist_emergency_event,
            )

            # Configure and start guardian
            self._guardian = get_guardian()
            self._guardian.configure(
                kill_switch=self._kill_switch,
                on_violation=self._persist_violation,
                on_event=self._persist_emergency_event,
            )
            self._guardian.start()

            # Active jails (process_id → ProcessJail)
            self._jails: Dict[str, ProcessJail] = {}
            self._jail_lock = threading.Lock()

            self._lockdown_active = False
            self._initialized = True
            logger.info("[ISOLATION] IsolationManager initialized")

    # ── DB helpers ─────────────────────────────────────────────────────────────

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

    # ── Core API ───────────────────────────────────────────────────────────────

    def create_isolated_workspace(
        self,
        agent_id: Optional[str] = None,
        base_dir: str = "isolated_workspaces",
    ) -> str:
        """Create an isolated temp directory and return its path."""
        ws_path = Path(base_dir) / str(uuid.uuid4())
        ws_path.mkdir(parents=True, exist_ok=True)
        logger.info("[ISOLATION] Workspace created: %s (agent=%s)", ws_path, agent_id)
        return str(ws_path)

    def isolate_process(
        self,
        pid: int,
        agent_id: Optional[str] = None,
        level: str = "RESTRICTED",
        workspace_root: str = ".",
        custom_limits: Optional[Dict[str, Any]] = None,
        process_id: Optional[str] = None,
        use_job_object: bool = True,
    ) -> IsolationContext:
        """
        Register a running PID in the isolation system.
        Applies OS-level limits (Job Object on Windows, rlimits on Linux)
        and starts guardian monitoring.

        Returns the IsolationContext.
        """
        if self._lockdown_active:
            raise RuntimeError("[ISOLATION] System in LOCKDOWN — no new isolations allowed")

        pid_str = process_id or str(uuid.uuid4())
        iso_level = IsolationLevel.from_string(level)
        limits = {**LEVEL_LIMITS[iso_level], **(custom_limits or {})}

        # Apply OS-level process jail
        jail = None
        if use_job_object:
            jail = ProcessJail.create(
                max_memory_mb=int(limits["memory_limit_mb"]),
                max_processes=int(limits["max_subprocesses"]),
                kill_on_close=True,
            )
            assigned = jail.assign(pid)
            jail.set_priority_low(pid)
            if assigned:
                with self._jail_lock:
                    self._jails[pid_str] = jail

        # Build sub-components
        limiter = ResourceLimiter(
            process_id=pid_str,
            pid=pid,
            level=iso_level,
            limits=limits,
            on_breach=self._on_resource_breach,
        )
        fs_jail  = FilesystemJail(pid_str, workspace_root, int(limits["max_file_writes"]))
        net_jail = NetworkJail(pid_str, iso_level)

        # Build context
        auto_score = {
            IsolationLevel.SOFT:       95,
            IsolationLevel.RESTRICTED: 60,
            IsolationLevel.HARD:       40,
            IsolationLevel.QUARANTINE: 25,
            IsolationLevel.LOCKDOWN:   10,
        }[iso_level]

        ctx = IsolationContext(
            process_id=pid_str,
            pid=pid,
            agent_id=agent_id,
            level=iso_level,
            workspace_root=workspace_root,
            limiter=limiter,
            fs_jail=fs_jail,
            net_jail=net_jail,
            auto_respond_score=auto_score,
        )

        # Persist to DB
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO isolated_processes
                   (process_id, agent_id, pid, level, workspace_root,
                    cpu_limit, memory_limit, max_subprocesses, max_file_writes,
                    max_net_conns, jail_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pid_str, agent_id, pid, iso_level.value, workspace_root,
                 limits["cpu_limit_percent"], limits["memory_limit_mb"],
                 limits["max_subprocesses"], limits["max_file_writes"],
                 limits["max_net_connections"], int(jail is not None and jail._job is not None)),
            )

        # Register with guardian
        self._guardian.register(ctx)

        logger.info("[ISOLATION] Isolated pid=%d level=%s process_id=%s agent=%s",
                    pid, iso_level.value, pid_str, agent_id)
        return ctx

    def restrict_filesystem_access(self, process_id: str, workspace_root: str) -> bool:
        """Update the workspace root for an active isolation context."""
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        ctx.fs_jail = FilesystemJail(process_id, workspace_root, ctx.fs_jail.max_file_writes)
        ctx.workspace_root = workspace_root
        logger.info("[ISOLATION] FS restriction updated for %s → %s", process_id, workspace_root)
        return True

    def restrict_network_access(
        self,
        process_id: str,
        new_level: str,
    ) -> bool:
        """Upgrade the network policy for an active context (can only become stricter)."""
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        lvl = IsolationLevel.from_string(new_level)
        ctx.net_jail = NetworkJail(process_id, lvl)
        logger.info("[ISOLATION] Network policy for %s → %s", process_id, lvl.value)
        return True

    def limit_cpu_usage(self, process_id: str, cpu_percent: float) -> bool:
        """Dynamically lower the CPU threshold for an active context."""
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        ctx.limiter.limits["cpu_limit_percent"] = cpu_percent
        logger.info("[ISOLATION] CPU limit for %s → %.0f%%", process_id, cpu_percent)
        return True

    def limit_memory_usage(self, process_id: str, memory_mb: float) -> bool:
        """Dynamically lower the memory threshold for an active context."""
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        ctx.limiter.limits["memory_limit_mb"] = memory_mb
        logger.info("[ISOLATION] Memory limit for %s → %.0fMB", process_id, memory_mb)
        return True

    def monitor_runtime_behavior(self, process_id: str) -> Optional[Dict[str, Any]]:
        """Return the current live status of an isolated process."""
        ctx = self._guardian.get_context(process_id)
        db  = self._get_db_process(process_id)
        if not db:
            return None
        snap = ctx.limiter.get_latest() if ctx else None
        return {
            "process": db,
            "live_status": ctx.status if ctx else "unknown",
            "risk_score":  ctx.risk_score if ctx else db.get("risk_score", 0),
            "latest_snapshot": {
                "cpu_percent":     snap.cpu_percent     if snap else None,
                "memory_mb":       snap.memory_mb       if snap else None,
                "subprocesses":    snap.subprocesses    if snap else None,
                "net_connections": snap.net_connections if snap else None,
            } if snap else None,
        }

    def kill_suspicious_process(self, pid: int, reason: str = "manual") -> bool:
        """Immediately kill a process tree. Logs [EMERGENCY]."""
        return self._kill_switch.kill_suspicious_process(pid, reason)

    def emergency_shutdown(self, reason: str) -> None:
        """Activate LOCKDOWN: prevent new isolations, freeze all, broadcast alert."""
        self._lockdown_active = True
        self._guardian.activate_lockdown()
        self._kill_switch.emergency_shutdown(reason)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO emergency_events
                   (event_id, process_id, action, description, severity)
                   VALUES (?,?,?,?,?)""",
                (str(uuid.uuid4()), "SYSTEM", "EMERGENCY_SHUTDOWN", reason, "CRITICAL"),
            )
        logger.critical("[EMERGENCY] SYSTEM EMERGENCY SHUTDOWN: %s", reason)

    def destroy_isolation_environment(self, process_id: str) -> bool:
        """Destroy isolation context: close jail, unregister, update DB."""
        ctx = self._guardian.get_context(process_id)
        if ctx and ctx.pid:
            # Graceful — don't kill if process is not running
            try:
                if _PSUTIL:
                    p = psutil.Process(ctx.pid)
                    if p.is_running():
                        self._kill_switch.kill_process_tree(ctx.pid, "isolation_destroyed")
            except Exception:
                pass

        with self._jail_lock:
            jail = self._jails.pop(process_id, None)
        if jail:
            jail.close()

        self._guardian.unregister(process_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE isolated_processes SET status='destroyed', updated_at=? WHERE process_id=?",
                (self._now(), process_id),
            )
        logger.info("[ISOLATION] Destroyed isolation environment: %s", process_id)
        return True

    def freeze_isolated_process(self, process_id: str) -> bool:
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        ok = self._kill_switch.freeze_process(ctx.pid)
        if ok:
            ctx.status = "frozen"
            with self._conn() as conn:
                conn.execute(
                    "UPDATE isolated_processes SET status='frozen', frozen_at=?, updated_at=? WHERE process_id=?",
                    (self._now(), self._now(), process_id),
                )
        return ok

    def unfreeze_isolated_process(self, process_id: str) -> bool:
        ctx = self._guardian.get_context(process_id)
        if not ctx:
            return False
        ok = self._kill_switch.unfreeze_process(ctx.pid)
        if ok:
            ctx.status = "active"
            with self._conn() as conn:
                conn.execute(
                    "UPDATE isolated_processes SET status='active', updated_at=? WHERE process_id=?",
                    (self._now(), process_id),
                )
        return ok

    # ── Query API ──────────────────────────────────────────────────────────────

    def list_isolated_processes(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clause = "WHERE status=?" if status else ""
        params = [status] if status else []
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM isolated_processes {clause} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def list_violations(
        self,
        process_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clause = "WHERE process_id=?" if process_id else ""
        params = [process_id] if process_id else []
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM runtime_violations {clause} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def list_emergency_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM emergency_events ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_resource_history(self, process_id: str, limit: int = 60) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM resource_usage WHERE process_id=? ORDER BY timestamp DESC LIMIT ?",
                (process_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total   = conn.execute("SELECT COUNT(*) FROM isolated_processes").fetchone()[0]
            active  = conn.execute("SELECT COUNT(*) FROM isolated_processes WHERE status='active'").fetchone()[0]
            frozen  = conn.execute("SELECT COUNT(*) FROM isolated_processes WHERE status='frozen'").fetchone()[0]
            quar    = conn.execute("SELECT COUNT(*) FROM isolated_processes WHERE status='quarantined'").fetchone()[0]
            viols   = conn.execute("SELECT COUNT(*) FROM runtime_violations").fetchone()[0]
            emerg   = conn.execute("SELECT COUNT(*) FROM emergency_events WHERE severity='CRITICAL'").fetchone()[0]
        return {
            "total_isolated":     total,
            "active":             active,
            "frozen":             frozen,
            "quarantined":        quar,
            "total_violations":   viols,
            "critical_events":    emerg,
            "lockdown_active":    self._lockdown_active,
            "guardian_active":    self._guardian._thread is not None and self._guardian._thread.is_alive(),
            "monitored_contexts": self._guardian.active_count,
        }

    # ── Internal callbacks ─────────────────────────────────────────────────────

    def _on_resource_breach(
        self,
        process_id: str,
        breach_type: str,
        details: Dict,
    ) -> None:
        """Called by ResourceLimiter on each breach."""
        ctx = self._guardian.get_context(process_id)
        self._persist_violation(
            process_id,
            breach_type,
            details.get("description", breach_type),
            details.get("risk_delta", 10),
            details,
        )
        # Persist snapshot
        snap = ctx.limiter.get_latest() if ctx else None
        if snap:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO resource_usage
                       (usage_id, process_id, cpu_percent, memory_mb, subprocesses,
                        file_handles, net_connections, risk_score)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), process_id,
                     snap.cpu_percent, snap.memory_mb, snap.subprocesses,
                     snap.file_handles, snap.net_connections,
                     ctx.risk_score if ctx else 0),
                )

    def _persist_violation(
        self,
        process_id: str,
        violation_type: str,
        description: str,
        risk_delta: int,
        details: Dict,
    ) -> None:
        ctx = self._guardian.get_context(process_id)
        agent_id = ctx.agent_id if ctx else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runtime_violations
                   (violation_id, process_id, agent_id, violation_type, description, risk_delta, details)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), process_id, agent_id,
                 violation_type, description, risk_delta, json.dumps(details)),
            )
            conn.execute(
                "UPDATE isolated_processes SET risk_score=MIN(100, risk_score+?), updated_at=? WHERE process_id=?",
                (risk_delta, self._now(), process_id),
            )

    def _persist_emergency_event(
        self,
        process_id: str,
        action: str,
        description: str,
        severity: str,
    ) -> None:
        ctx = self._guardian.get_context(process_id)
        agent_id = ctx.agent_id if ctx else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO emergency_events
                   (event_id, process_id, agent_id, action, description, severity)
                   VALUES (?,?,?,?,?,?)""",
                (str(uuid.uuid4()), process_id, agent_id, action, description, severity),
            )
        if severity == "CRITICAL":
            logger.critical("[EMERGENCY] [%s] %s: %s", process_id, action, description)

    def _handle_quarantine(self, process_id: str, reason: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE isolated_processes SET status='quarantined', quarantined_at=?, updated_at=? WHERE process_id=?",
                (self._now(), self._now(), process_id),
            )

    def _handle_lockdown(self, reason: str) -> None:
        self._lockdown_active = True
        self._guardian.activate_lockdown()

    def _get_db_process(self, process_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM isolated_processes WHERE process_id=?", (process_id,)
            ).fetchone()
        return dict(row) if row else None


# ── Singleton ──────────────────────────────────────────────────────────────────

_manager: Optional[IsolationManager] = None
_manager_lock = threading.Lock()


def get_isolation_manager() -> IsolationManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = IsolationManager()
    return _manager
