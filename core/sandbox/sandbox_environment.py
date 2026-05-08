"""
SandboxEnvironment — isolated temporary workspace for a single sandbox instance.

Each SandboxEnvironment owns:
  - A unique sandbox_id (UUID)
  - A private temp directory under sandboxes/<sandbox_id>/
  - An optional agent_id for registry linkage
  - A mode: STATIC_ANALYSIS | RESTRICTED_EXECUTION | FULL_QUARANTINE | OBSERVATION_MODE
  - Lifecycle state: created → running → (frozen|quarantined) → completed|destroyed

The temp directory is fully cleaned up on destroy() unless preserve_on_exit=True
(set automatically when the sandbox is quarantined for forensic analysis).
"""

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Root directory for all sandbox workspaces
SANDBOX_ROOT = Path("sandboxes")


# ── Modes ──────────────────────────────────────────────────────────────────────

class SandboxMode(str, Enum):
    STATIC_ANALYSIS     = "STATIC_ANALYSIS"
    RESTRICTED_EXECUTION = "RESTRICTED_EXECUTION"
    FULL_QUARANTINE     = "FULL_QUARANTINE"
    OBSERVATION_MODE    = "OBSERVATION_MODE"

    @classmethod
    def from_string(cls, s: str) -> "SandboxMode":
        try:
            return cls(s.upper())
        except ValueError:
            return cls.RESTRICTED_EXECUTION


class SandboxStatus(str, Enum):
    CREATED     = "created"
    RUNNING     = "running"
    FROZEN      = "frozen"
    QUARANTINED = "quarantined"
    COMPLETED   = "completed"
    DESTROYED   = "destroyed"


# ── Mode configuration ─────────────────────────────────────────────────────────

MODE_CONFIG: Dict[SandboxMode, Dict[str, Any]] = {
    SandboxMode.STATIC_ANALYSIS: {
        "allow_exec":       False,   # no execution — code analysis only
        "allow_network":    False,
        "allow_fs_write":   False,
        "max_cpu_pct":      0,
        "max_ram_mb":       256,
        "max_duration_sec": 30,
        "auto_quarantine_score": 50,
        "monitor_interval_sec": 1,
    },
    SandboxMode.RESTRICTED_EXECUTION: {
        "allow_exec":       True,
        "allow_network":    False,   # localhost only
        "allow_fs_write":   True,    # within sandbox dir only
        "max_cpu_pct":      80,
        "max_ram_mb":       512,
        "max_duration_sec": 120,
        "auto_quarantine_score": 60,
        "monitor_interval_sec": 1,
    },
    SandboxMode.FULL_QUARANTINE: {
        "allow_exec":       True,    # execute to observe behavior
        "allow_network":    False,
        "allow_fs_write":   True,
        "max_cpu_pct":      60,
        "max_ram_mb":       256,
        "max_duration_sec": 60,
        "auto_quarantine_score": 40,  # lower threshold — stricter
        "monitor_interval_sec": 0.5,
    },
    SandboxMode.OBSERVATION_MODE: {
        "allow_exec":       True,
        "allow_network":    True,    # allowed but monitored
        "allow_fs_write":   True,
        "max_cpu_pct":      95,
        "max_ram_mb":       1024,
        "max_duration_sec": 300,
        "auto_quarantine_score": 80,
        "monitor_interval_sec": 2,
    },
}


# ── Environment ────────────────────────────────────────────────────────────────

@dataclass
class SandboxEnvironment:
    """
    Represents one isolated sandbox instance.
    Manages its workspace directory and lifecycle state.
    """
    sandbox_id:          str
    agent_id:            Optional[str]
    mode:                SandboxMode
    status:              SandboxStatus = SandboxStatus.CREATED
    workspace_path:      Path          = field(default_factory=Path)
    risk_score:          int           = 0
    preserve_on_exit:    bool          = False
    pid:                 Optional[int] = None
    exit_code:           Optional[int] = None
    created_at:          str           = field(default_factory=lambda: _now())
    started_at:          Optional[str] = None
    frozen_at:           Optional[str] = None
    quarantined_at:      Optional[str] = None
    destroyed_at:        Optional[str] = None
    # runtime metadata
    files_written:       int = 0
    files_deleted:       int = 0
    subprocess_spawned:  int = 0

    def __post_init__(self) -> None:
        if not self.workspace_path or self.workspace_path == Path():
            self.workspace_path = SANDBOX_ROOT / self.sandbox_id

    @property
    def config(self) -> Dict[str, Any]:
        return MODE_CONFIG[self.mode]

    @property
    def is_active(self) -> bool:
        return self.status in (SandboxStatus.RUNNING, SandboxStatus.FROZEN)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            SandboxStatus.QUARANTINED,
            SandboxStatus.COMPLETED,
            SandboxStatus.DESTROYED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sandbox_id":      self.sandbox_id,
            "agent_id":        self.agent_id,
            "mode":            self.mode.value,
            "status":          self.status.value,
            "workspace_path":  str(self.workspace_path),
            "risk_score":      self.risk_score,
            "pid":             self.pid,
            "exit_code":       self.exit_code,
            "created_at":      self.created_at,
            "started_at":      self.started_at,
            "frozen_at":       self.frozen_at,
            "quarantined_at":  self.quarantined_at,
            "destroyed_at":    self.destroyed_at,
            "files_written":   self.files_written,
            "files_deleted":   self.files_deleted,
            "subprocess_spawned": self.subprocess_spawned,
        }

    # ── Workspace lifecycle ────────────────────────────────────────────────────

    def setup_workspace(self) -> Path:
        """Create the isolated temp directory. Returns the workspace path."""
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        # Write a sandbox manifest
        manifest = {
            "sandbox_id":  self.sandbox_id,
            "agent_id":    self.agent_id,
            "mode":        self.mode.value,
            "created_at":  self.created_at,
        }
        import json
        (self.workspace_path / ".sandbox_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        logger.info("[SANDBOX] Workspace created: %s (mode=%s)", self.workspace_path, self.mode.value)
        return self.workspace_path

    def teardown_workspace(self) -> bool:
        """
        Remove the workspace directory.
        Skipped if preserve_on_exit=True (set on quarantine for forensics).
        """
        if self.preserve_on_exit:
            logger.info("[SANDBOX] Workspace preserved for forensics: %s", self.workspace_path)
            return False
        if self.workspace_path.exists():
            shutil.rmtree(self.workspace_path, ignore_errors=True)
            logger.info("[SANDBOX] Workspace removed: %s", self.workspace_path)
        return True

    def add_input_file(self, filename: str, content: str) -> Path:
        """Write an input file into the sandbox workspace (before execution)."""
        path = self.workspace_path / filename
        path.write_text(content, encoding="utf-8")
        return path

    def read_output_file(self, filename: str) -> Optional[str]:
        """Read a file produced by sandbox execution."""
        path = self.workspace_path / filename
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def list_workspace_files(self) -> List[str]:
        """List all files inside the workspace (relative paths)."""
        if not self.workspace_path.exists():
            return []
        return [
            str(f.relative_to(self.workspace_path))
            for f in self.workspace_path.rglob("*")
            if f.is_file() and f.name != ".sandbox_manifest.json"
        ]


# ── Factory ────────────────────────────────────────────────────────────────────

def create_environment(
    agent_id: Optional[str] = None,
    mode: str = "RESTRICTED_EXECUTION",
    sandbox_id: Optional[str] = None,
) -> SandboxEnvironment:
    """Create a new SandboxEnvironment and set up its workspace."""
    sid = sandbox_id or str(uuid.uuid4())
    env = SandboxEnvironment(
        sandbox_id=sid,
        agent_id=agent_id,
        mode=SandboxMode.from_string(mode),
    )
    env.setup_workspace()
    return env


# ── Helper ─────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
