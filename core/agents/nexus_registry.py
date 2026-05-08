"""
NexusAgentRegistry — SQLite-backed organizational registry for all agents in Nexus BNL.

Architecture metaphor:
    Nexus      = edificio principal (the system)
    Architect  = orchestrador maestro
    Department = specialized area (engineering, security, etc.)
    Agent      = permanent specialist worker
    SubAgent   = subordinate specialist under a parent agent
    Temporary  = hired only for a single task (contract-based)

Tables:
    departments         — organizational units
    capabilities        — skills/abilities that agents can hold
    agents              — the full agent roster
    agent_capabilities  — many-to-many link between agents and capabilities
    agent_relationships — explicit parent/child edges (supplements parent_agent column)
    temporary_contracts — lifecycle records for temporary agents

Usage:
    from core.agents.nexus_registry import get_registry
    reg = get_registry()
    reg.register_agent(name="ForjadorAgent", role="code_builder", department="engineering", ...)
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

# ── Constants ──────────────────────────────────────────────────────────────────

DB_PATH = Path("data/nexus_agents.db")

# Pre-seeded departments
SEED_DEPARTMENTS = [
    {"department_id": "engineering",  "name": "Engineering",  "description": "Core code generation and software building"},
    {"department_id": "frontend",     "name": "Frontend",     "description": "UI/UX and client-side specialization"},
    {"department_id": "security",     "name": "Security",     "description": "Security analysis, auditing, and hardening"},
    {"department_id": "runtime",      "name": "Runtime",      "description": "Process management, port allocation, execution"},
    {"department_id": "repairs",      "name": "Repairs",      "description": "Error diagnosis, auto-repair, and recovery"},
    {"department_id": "research",     "name": "Research",     "description": "Information gathering and deep analysis"},
    {"department_id": "media",        "name": "Media",        "description": "Image, audio, video, and content generation"},
    {"department_id": "gaming",       "name": "Gaming",       "description": "Game development and interactive experiences"},
]

# Pre-seeded capabilities
SEED_CAPABILITIES = [
    {"capability_id": "database_optimization", "name": "Database Optimization",  "category": "data"},
    {"capability_id": "frontend_ui",           "name": "Frontend UI",            "category": "frontend"},
    {"capability_id": "security_analysis",     "name": "Security Analysis",      "category": "security"},
    {"capability_id": "debugging",             "name": "Debugging",              "category": "engineering"},
    {"capability_id": "deployment",            "name": "Deployment",             "category": "devops"},
    {"capability_id": "memory_repair",         "name": "Memory Repair",          "category": "repairs"},
    {"capability_id": "code_generation",       "name": "Code Generation",        "category": "engineering"},
    {"capability_id": "api_design",            "name": "API Design",             "category": "engineering"},
    {"capability_id": "process_management",    "name": "Process Management",     "category": "runtime"},
    {"capability_id": "error_classification",  "name": "Error Classification",   "category": "repairs"},
    {"capability_id": "blueprint_planning",    "name": "Blueprint Planning",     "category": "engineering"},
    {"capability_id": "web_scraping",          "name": "Web Scraping",           "category": "research"},
    {"capability_id": "image_generation",      "name": "Image Generation",       "category": "media"},
    {"capability_id": "game_scripting",        "name": "Game Scripting",         "category": "gaming"},
    {"capability_id": "threat_modeling",       "name": "Threat Modeling",        "category": "security"},
    {"capability_id": "test_automation",       "name": "Test Automation",        "category": "engineering"},
    {"capability_id": "data_pipeline",         "name": "Data Pipeline",          "category": "data"},
    {"capability_id": "notion_integration",    "name": "Notion Integration",     "category": "research"},
]


# ── DDL ────────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS departments (
    department_id  TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT DEFAULT '',
    created_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id  TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT DEFAULT '',
    category       TEXT DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id       TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    department     TEXT REFERENCES departments(department_id) ON DELETE SET NULL,
    parent_agent   TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
    permissions    TEXT DEFAULT '[]',
    trust_level    INTEGER DEFAULT 50,
    source         TEXT DEFAULT 'system',
    temporary      INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_active    TEXT,
    status         TEXT DEFAULT 'inactive'
);

CREATE TABLE IF NOT EXISTS agent_capabilities (
    agent_id       TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    capability_id  TEXT NOT NULL REFERENCES capabilities(capability_id) ON DELETE CASCADE,
    PRIMARY KEY (agent_id, capability_id)
);

CREATE TABLE IF NOT EXISTS agent_relationships (
    parent_id         TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    child_id          TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    relationship_type TEXT DEFAULT 'parent_child',
    created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (parent_id, child_id)
);

CREATE TABLE IF NOT EXISTS temporary_contracts (
    contract_id      TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_description TEXT DEFAULT '',
    hired_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at       TEXT,
    terminated_at    TEXT,
    status           TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_agents_department  ON agents(department);
CREATE INDEX IF NOT EXISTS idx_agents_status      ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_temporary   ON agents(temporary);
CREATE INDEX IF NOT EXISTS idx_agents_parent      ON agents(parent_agent);
CREATE INDEX IF NOT EXISTS idx_ac_capability      ON agent_capabilities(capability_id);
CREATE INDEX IF NOT EXISTS idx_contracts_agent    ON temporary_contracts(agent_id);
CREATE INDEX IF NOT EXISTS idx_contracts_status   ON temporary_contracts(status);
"""


# ── Registry ───────────────────────────────────────────────────────────────────

class NexusAgentRegistry:
    """
    Singleton SQLite-backed registry for all Nexus BNL agents.
    Thread-safe via a module-level lock and WAL journal mode.
    """

    _instance: Optional["NexusAgentRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "NexusAgentRegistry":
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
            self._seed()
            self._initialized = True
            logger.info("[AGENT_REGISTRY] Initialized at %s", self._db_path)

    # ── DB helpers ─────────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
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

    def _seed(self) -> None:
        with self._conn() as conn:
            for dept in SEED_DEPARTMENTS:
                conn.execute(
                    "INSERT OR IGNORE INTO departments (department_id, name, description) VALUES (?,?,?)",
                    (dept["department_id"], dept["name"], dept["description"]),
                )
            for cap in SEED_CAPABILITIES:
                conn.execute(
                    "INSERT OR IGNORE INTO capabilities (capability_id, name, category) VALUES (?,?,?)",
                    (cap["capability_id"], cap["name"], cap["category"]),
                )
        logger.info("[AGENT_REGISTRY] Seed complete — %d departments, %d capabilities",
                    len(SEED_DEPARTMENTS), len(SEED_CAPABILITIES))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        if row is None:
            return {}
        d = dict(row)
        for key in ("permissions",):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        d["temporary"] = bool(d.get("temporary", 0))
        return d

    # ── Core CRUD ──────────────────────────────────────────────────────────────

    def register_agent(
        self,
        name: str,
        role: str,
        department: Optional[str] = None,
        parent_agent: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        trust_level: int = 50,
        source: str = "system",
        temporary: bool = False,
        agent_id: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """Register a new agent in the registry. Returns the created agent record."""
        aid = agent_id or str(uuid.uuid4())
        perms_json = json.dumps(permissions or [])

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO agents
                   (agent_id, name, role, department, parent_agent, permissions,
                    trust_level, source, temporary, status, last_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, name, role, department, parent_agent, perms_json,
                 trust_level, source, int(temporary), status, self._now()),
            )
            if capabilities:
                for cap in capabilities:
                    conn.execute(
                        "INSERT OR IGNORE INTO agent_capabilities (agent_id, capability_id) VALUES (?,?)",
                        (aid, cap),
                    )
            if parent_agent:
                conn.execute(
                    "INSERT OR IGNORE INTO agent_relationships (parent_id, child_id) VALUES (?,?)",
                    (parent_agent, aid),
                )

        logger.info("[AGENT_HIRE] Agent '%s' (%s) registered — dept=%s temp=%s",
                    name, aid, department, temporary)
        return self.get_agent(aid)

    def remove_agent(self, agent_id: str) -> bool:
        """Permanently remove an agent and all its relationships."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
            removed = cur.rowcount > 0
        if removed:
            logger.info("[AGENT_REGISTRY] Agent %s removed", agent_id)
        return removed

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single agent record with its capabilities list."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
            ).fetchone()
            if row is None:
                return None
            agent = self._row_to_dict(row)
            caps = conn.execute(
                "SELECT capability_id FROM agent_capabilities WHERE agent_id=?", (agent_id,)
            ).fetchall()
            agent["capabilities"] = [r["capability_id"] for r in caps]
        return agent

    def list_agents(
        self,
        department: Optional[str] = None,
        status: Optional[str] = None,
        temporary: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """List agents with optional filters."""
        clauses, params = [], []
        if department:
            clauses.append("department=?")
            params.append(department)
        if status:
            clauses.append("status=?")
            params.append(status)
        if temporary is not None:
            clauses.append("temporary=?")
            params.append(int(temporary))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM agents {where} ORDER BY created_at DESC", params
            ).fetchall()
            agents = []
            for row in rows:
                agent = self._row_to_dict(row)
                caps = conn.execute(
                    "SELECT capability_id FROM agent_capabilities WHERE agent_id=?",
                    (agent["agent_id"],),
                ).fetchall()
                agent["capabilities"] = [r["capability_id"] for r in caps]
                agents.append(agent)
        return agents

    def assign_to_department(self, agent_id: str, department_id: str) -> bool:
        """Move an agent to a department."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE agents SET department=? WHERE agent_id=?",
                (department_id, agent_id),
            )
            ok = cur.rowcount > 0
        if ok:
            logger.info("[AGENT_ASSIGNMENT] Agent %s → department %s", agent_id, department_id)
        return ok

    def assign_parent_agent(self, child_id: str, parent_id: str) -> bool:
        """Set the parent (supervisor) of an agent and register the relationship edge."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE agents SET parent_agent=? WHERE agent_id=?", (parent_id, child_id)
            )
            conn.execute(
                "INSERT OR IGNORE INTO agent_relationships (parent_id, child_id) VALUES (?,?)",
                (parent_id, child_id),
            )
        logger.info("[AGENT_ASSIGNMENT] Parent %s → child %s", parent_id, child_id)
        return True

    def find_agents_by_capability(self, capability_id: str) -> List[Dict[str, Any]]:
        """Return all active agents that have the given capability."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT a.* FROM agents a
                   JOIN agent_capabilities ac ON a.agent_id = ac.agent_id
                   WHERE ac.capability_id=? AND a.status != 'terminated'
                   ORDER BY a.trust_level DESC""",
                (capability_id,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    # ── Temporary agents ───────────────────────────────────────────────────────

    def hire_temporary_agent(
        self,
        name: str,
        role: str,
        task_description: str,
        department: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
        parent_agent: Optional[str] = None,
        trust_level: int = 30,
    ) -> Dict[str, Any]:
        """
        Register a temporary agent and create a contract record.
        Returns {'agent': {...}, 'contract': {...}}.
        """
        agent = self.register_agent(
            name=name,
            role=role,
            department=department,
            capabilities=capabilities,
            trust_level=trust_level,
            source="temporary_hire",
            temporary=True,
            parent_agent=parent_agent,
            status="active",
        )
        contract_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO temporary_contracts
                   (contract_id, agent_id, task_description, expires_at)
                   VALUES (?,?,?,?)""",
                (contract_id, agent["agent_id"], task_description, expires_at),
            )
        logger.info("[AGENT_HIRE] Temporary agent '%s' hired — task: %s",
                    name, task_description[:60])
        return {
            "agent": agent,
            "contract": {
                "contract_id": contract_id,
                "task_description": task_description,
                "expires_at": expires_at,
                "status": "active",
            },
        }

    def terminate_temporary_agent(self, agent_id: str) -> bool:
        """
        Mark the agent as terminated and close its active contract.
        Does not delete the record — preserves audit history.
        """
        with self._conn() as conn:
            conn.execute(
                "UPDATE agents SET status='terminated', last_active=? WHERE agent_id=?",
                (self._now(), agent_id),
            )
            conn.execute(
                """UPDATE temporary_contracts
                   SET status='terminated', terminated_at=?
                   WHERE agent_id=? AND status='active'""",
                (self._now(), agent_id),
            )
        logger.info("[AGENT_REGISTRY] Temporary agent %s terminated", agent_id)
        return True

    def update_agent_status(self, agent_id: str, status: str) -> bool:
        """Update status and touch last_active timestamp."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE agents SET status=?, last_active=? WHERE agent_id=?",
                (status, self._now(), agent_id),
            )
        return cur.rowcount > 0

    # ── Departments & capabilities ─────────────────────────────────────────────

    def list_departments(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
            depts = [dict(r) for r in rows]
            for dept in depts:
                count = conn.execute(
                    "SELECT COUNT(*) FROM agents WHERE department=? AND status != 'terminated'",
                    (dept["department_id"],),
                ).fetchone()[0]
                dept["agent_count"] = count
        return depts

    def list_capabilities(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM capabilities ORDER BY category, name").fetchall()
            return [dict(r) for r in rows]

    def get_hierarchy(self, root_agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return parent→children tree. If root_agent_id is None, returns all top-level agents."""
        with self._conn() as conn:
            if root_agent_id:
                rows = conn.execute(
                    "SELECT * FROM agent_relationships WHERE parent_id=?", (root_agent_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT a.agent_id as child_id, a.parent_agent as parent_id
                       FROM agents a WHERE a.parent_agent IS NULL
                       AND a.status != 'terminated'"""
                ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics for the registry."""
        with self._conn() as conn:
            total       = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            active      = conn.execute("SELECT COUNT(*) FROM agents WHERE status='active'").fetchone()[0]
            inactive    = conn.execute("SELECT COUNT(*) FROM agents WHERE status='inactive'").fetchone()[0]
            terminated  = conn.execute("SELECT COUNT(*) FROM agents WHERE status='terminated'").fetchone()[0]
            temporary   = conn.execute("SELECT COUNT(*) FROM agents WHERE temporary=1 AND status='active'").fetchone()[0]
            departments = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
            capabilities= conn.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
            contracts   = conn.execute("SELECT COUNT(*) FROM temporary_contracts WHERE status='active'").fetchone()[0]
        return {
            "total_agents":      total,
            "active_agents":     active,
            "inactive_agents":   inactive,
            "terminated_agents": terminated,
            "active_temporary":  temporary,
            "departments":       departments,
            "capabilities":      capabilities,
            "active_contracts":  contracts,
        }


# ── Module-level singleton accessor ───────────────────────────────────────────

_registry: Optional[NexusAgentRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> NexusAgentRegistry:
    """Return the module-level NexusAgentRegistry singleton, initializing on first call."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = NexusAgentRegistry()
    return _registry
