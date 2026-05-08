"""
Permission catalog for Nexus BNL — all permission identifiers, levels, and seed data.

Levels (ascending trust):
    READ_ONLY  (0) — absolute minimum, new agents start here (zero-trust)
    LIMITED    (1) — local network + basic write
    STANDARD   (2) — normal operations, DB write, sandbox scan
    ELEVATED   (3) — subprocess, external network, memory modify
    ADMIN      (4) — agent lifecycle, sandbox approve, runtime restart
    ROOT       (5) — runtime shutdown + all ops (reserved for The Architect)

Zero-trust rule: every new agent starts with READ_ONLY.
Permissions are only granted explicitly — never inherited or assumed.
"""

from enum import IntEnum
from typing import Dict, List


# ── Trust Levels ───────────────────────────────────────────────────────────────

class TrustLevel(IntEnum):
    READ_ONLY = 0
    LIMITED   = 1
    STANDARD  = 2
    ELEVATED  = 3
    ADMIN     = 4
    ROOT      = 5

    @classmethod
    def from_string(cls, s: str) -> "TrustLevel":
        try:
            return cls[s.upper()]
        except KeyError:
            return cls.READ_ONLY

    @classmethod
    def names(cls) -> List[str]:
        return [m.name for m in cls]


# ── Permission IDs ─────────────────────────────────────────────────────────────

class Perm:
    """Namespace of all permission ID strings used across the system."""

    # Filesystem
    FS_READ      = "filesystem.read"
    FS_WRITE     = "filesystem.write"
    FS_DELETE    = "filesystem.delete"

    # Network
    NET_LOCAL    = "network.local"
    NET_EXTERNAL = "network.external"

    # Subprocess
    PROC_SPAWN   = "subprocess.spawn"
    PROC_KILL    = "subprocess.kill"

    # Database
    DB_READ      = "database.read"
    DB_WRITE     = "database.write"

    # Memory
    MEM_READ     = "memory.read"
    MEM_MODIFY   = "memory.modify"

    # Agent lifecycle
    AGENT_REGISTER  = "agent.register"
    AGENT_HIRE      = "agent.hire"
    AGENT_TERMINATE = "agent.terminate"

    # Runtime
    RT_RESTART   = "runtime.restart"
    RT_SHUTDOWN  = "runtime.shutdown"

    # Sandbox
    SB_SCAN      = "sandbox.scan"
    SB_APPROVE   = "sandbox.approve"
    SB_REJECT    = "sandbox.reject"

    @classmethod
    def all_ids(cls) -> List[str]:
        return [v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str)]


# ── Permission catalog ─────────────────────────────────────────────────────────
# min_level: minimum TrustLevel required to be granted this permission
# risk_score: 1–10 (used to compute agent risk score)

PERMISSION_CATALOG: List[Dict] = [
    # Filesystem
    {
        "permission_id": Perm.FS_READ,
        "category": "filesystem",
        "name": "Filesystem Read",
        "description": "Read files within the workspace",
        "min_level": TrustLevel.READ_ONLY,
        "risk_score": 1,
    },
    {
        "permission_id": Perm.FS_WRITE,
        "category": "filesystem",
        "name": "Filesystem Write",
        "description": "Create and overwrite files within the workspace",
        "min_level": TrustLevel.STANDARD,
        "risk_score": 3,
    },
    {
        "permission_id": Perm.FS_DELETE,
        "category": "filesystem",
        "name": "Filesystem Delete",
        "description": "Delete files within the workspace",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 6,
    },
    # Network
    {
        "permission_id": Perm.NET_LOCAL,
        "category": "network",
        "name": "Local Network",
        "description": "Connect to localhost and LAN services",
        "min_level": TrustLevel.LIMITED,
        "risk_score": 2,
    },
    {
        "permission_id": Perm.NET_EXTERNAL,
        "category": "network",
        "name": "External Network",
        "description": "Make outbound requests to external internet endpoints",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 7,
    },
    # Subprocess
    {
        "permission_id": Perm.PROC_SPAWN,
        "category": "subprocess",
        "name": "Spawn Subprocess",
        "description": "Start child processes or shell commands",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 8,
    },
    {
        "permission_id": Perm.PROC_KILL,
        "category": "subprocess",
        "name": "Kill Subprocess",
        "description": "Terminate running child processes",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 7,
    },
    # Database
    {
        "permission_id": Perm.DB_READ,
        "category": "database",
        "name": "Database Read",
        "description": "Execute SELECT queries on internal databases",
        "min_level": TrustLevel.READ_ONLY,
        "risk_score": 1,
    },
    {
        "permission_id": Perm.DB_WRITE,
        "category": "database",
        "name": "Database Write",
        "description": "Execute INSERT/UPDATE/DELETE on internal databases",
        "min_level": TrustLevel.STANDARD,
        "risk_score": 4,
    },
    # Memory
    {
        "permission_id": Perm.MEM_READ,
        "category": "memory",
        "name": "Memory Read",
        "description": "Read agent memory stores and decision history",
        "min_level": TrustLevel.READ_ONLY,
        "risk_score": 1,
    },
    {
        "permission_id": Perm.MEM_MODIFY,
        "category": "memory",
        "name": "Memory Modify",
        "description": "Write to agent memory stores and adaptive layers",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 7,
    },
    # Agent lifecycle
    {
        "permission_id": Perm.AGENT_REGISTER,
        "category": "agent",
        "name": "Agent Register",
        "description": "Register new permanent agents in the registry",
        "min_level": TrustLevel.ADMIN,
        "risk_score": 8,
    },
    {
        "permission_id": Perm.AGENT_HIRE,
        "category": "agent",
        "name": "Agent Hire",
        "description": "Hire temporary agents for specific tasks",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 5,
    },
    {
        "permission_id": Perm.AGENT_TERMINATE,
        "category": "agent",
        "name": "Agent Terminate",
        "description": "Terminate and deactivate agents",
        "min_level": TrustLevel.ADMIN,
        "risk_score": 9,
    },
    # Runtime
    {
        "permission_id": Perm.RT_RESTART,
        "category": "runtime",
        "name": "Runtime Restart",
        "description": "Restart running project processes",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 6,
    },
    {
        "permission_id": Perm.RT_SHUTDOWN,
        "category": "runtime",
        "name": "Runtime Shutdown",
        "description": "Shut down the Nexus runtime entirely",
        "min_level": TrustLevel.ROOT,
        "risk_score": 10,
    },
    # Sandbox
    {
        "permission_id": Perm.SB_SCAN,
        "category": "sandbox",
        "name": "Sandbox Scan",
        "description": "Trigger security scans on generated code",
        "min_level": TrustLevel.STANDARD,
        "risk_score": 2,
    },
    {
        "permission_id": Perm.SB_APPROVE,
        "category": "sandbox",
        "name": "Sandbox Approve",
        "description": "Approve code for deployment after scanning",
        "min_level": TrustLevel.ADMIN,
        "risk_score": 8,
    },
    {
        "permission_id": Perm.SB_REJECT,
        "category": "sandbox",
        "name": "Sandbox Reject",
        "description": "Reject and quarantine unsafe code",
        "min_level": TrustLevel.ELEVATED,
        "risk_score": 4,
    },
]

# Map permission_id → catalog entry for O(1) lookups
PERM_BY_ID: Dict[str, Dict] = {p["permission_id"]: p for p in PERMISSION_CATALOG}

# Zero-trust default: permissions auto-granted to every new agent
ZERO_TRUST_DEFAULTS: List[str] = [
    Perm.FS_READ,
    Perm.DB_READ,
    Perm.MEM_READ,
]

# Permissions granted by trust level automatically (additive per level)
LEVEL_GRANTS: Dict[TrustLevel, List[str]] = {
    TrustLevel.READ_ONLY: ZERO_TRUST_DEFAULTS,
    TrustLevel.LIMITED: [Perm.NET_LOCAL],
    TrustLevel.STANDARD: [Perm.FS_WRITE, Perm.DB_WRITE, Perm.SB_SCAN],
    TrustLevel.ELEVATED: [
        Perm.FS_DELETE, Perm.NET_EXTERNAL, Perm.PROC_SPAWN, Perm.PROC_KILL,
        Perm.MEM_MODIFY, Perm.AGENT_HIRE, Perm.RT_RESTART, Perm.SB_REJECT,
    ],
    TrustLevel.ADMIN: [Perm.AGENT_REGISTER, Perm.AGENT_TERMINATE, Perm.SB_APPROVE],
    TrustLevel.ROOT: [Perm.RT_SHUTDOWN],
}


def get_permissions_for_level(level: TrustLevel) -> List[str]:
    """Return the cumulative set of permissions for a given trust level."""
    perms: List[str] = []
    for lvl in TrustLevel:
        if lvl <= level:
            perms.extend(LEVEL_GRANTS.get(lvl, []))
    return list(set(perms))
