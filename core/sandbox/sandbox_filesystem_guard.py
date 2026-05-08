"""
SandboxFilesystemGuard — filesystem restriction and monitoring for sandbox environments.

Responsibilities:
  - Enforce that all file I/O stays within the sandbox workspace directory
  - Detect and report suspicious filesystem activity
  - Track file write/delete counts to detect mass operations
  - Provide path validation for any operation that touches the filesystem

Detection patterns:
  WORKSPACE_ESCAPE   — any path outside the sandbox workspace root
  MASS_FILE_WRITE    — >50 files written in <10 seconds
  MASS_FILE_DELETE   — >10 files deleted in <5 seconds
  SENSITIVE_PATH     — access to system paths (Windows registry, /etc, etc.)
  HIDDEN_FILE_WRITE  — writing files with leading dots or system-hidden names
"""

import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.sandbox.sandbox_audit_logger import SandboxAuditLogger, get_audit_logger

logger = logging.getLogger(__name__)

# Suspicious path patterns (cross-platform)
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(windows[/\\]system32)"),
    re.compile(r"(?i)(program\s*files)"),
    re.compile(r"(?i)(/etc/passwd|/etc/shadow|/etc/hosts)"),
    re.compile(r"(?i)(appdata[/\\](roaming|local))"),
    re.compile(r"(?i)(\\.env$|credentials|secret|token|api_key)"),
    re.compile(r"(?i)(registry|regedit|\.reg$)"),
    re.compile(r"(?i)(/proc/|/sys/|/dev/)"),
]

_MASS_WRITE_WINDOW    = 10   # seconds
_MASS_WRITE_THRESHOLD = 50   # files
_MASS_DELETE_WINDOW   = 5    # seconds
_MASS_DELETE_THRESHOLD = 10  # files


class SandboxFilesystemGuard:
    """
    Per-sandbox filesystem guard. One instance per SandboxEnvironment.
    Validates paths and tracks operation rates.
    """

    def __init__(
        self,
        sandbox_id: str,
        workspace_path: str,
        allow_write: bool = True,
        audit: Optional[SandboxAuditLogger] = None,
    ) -> None:
        self.sandbox_id    = sandbox_id
        self.workspace_root = Path(workspace_path).resolve()
        self.allow_write   = allow_write
        self._audit        = audit or get_audit_logger()

        # Sliding windows for rate detection
        self._write_times:  deque = deque()
        self._delete_times: deque = deque()

        # Counters (lifetime totals for the sandbox)
        self.files_written = 0
        self.files_deleted = 0

    # ── Path validation ────────────────────────────────────────────────────────

    def validate_path(self, path: str, operation: str = "access") -> Tuple[bool, str]:
        """
        Validate that a path is within the sandbox workspace.
        Returns (allowed, reason).
        Log violations if the path escapes the workspace.
        """
        try:
            abs_path = Path(os.path.realpath(os.path.abspath(path)))
            within   = str(abs_path).startswith(str(self.workspace_root))
        except Exception:
            return False, "path_resolution_error"

        if not within:
            self._report_escape(path, operation)
            return False, "workspace_escape"

        # Sensitive path check even within workspace (e.g. symlinks)
        reason = self._check_sensitive(str(abs_path))
        if reason:
            self._audit.record_violation(
                self.sandbox_id,
                "SENSITIVE_PATH",
                f"Sensitive path accessed: {path[:120]}",
                risk_delta=15,
                details={"path": path, "operation": operation, "reason": reason},
            )
            return False, f"sensitive_path:{reason}"

        # Write restriction
        if operation in ("write", "delete") and not self.allow_write:
            return False, "write_not_allowed_in_mode"

        return True, "ok"

    def _check_sensitive(self, path_str: str) -> Optional[str]:
        for pat in _SENSITIVE_PATTERNS:
            if pat.search(path_str):
                return pat.pattern
        return None

    def _report_escape(self, path: str, operation: str) -> None:
        self._audit.record_violation(
            self.sandbox_id,
            "WORKSPACE_ESCAPE",
            f"Filesystem escape attempt: {operation} on {path[:120]}",
            risk_delta=30,
            details={"path": path, "operation": operation, "workspace": str(self.workspace_root)},
        )
        self._audit.log_event(
            self.sandbox_id,
            "SANDBOX_ESCAPE_ATTEMPT",
            f"[SANDBOX_ESCAPE_ATT] {operation} outside workspace: {path[:80]}",
            severity="CRITICAL",
        )

    # ── Operation tracking ─────────────────────────────────────────────────────

    def record_write(self, path: str) -> bool:
        """Call this whenever a file write is detected. Returns False on mass-write alert."""
        allowed, reason = self.validate_path(path, "write")
        if not allowed:
            return False

        now = time.monotonic()
        self._write_times.append(now)
        while self._write_times and (now - self._write_times[0]) > _MASS_WRITE_WINDOW:
            self._write_times.popleft()

        self.files_written += 1

        if len(self._write_times) >= _MASS_WRITE_THRESHOLD:
            self._audit.record_violation(
                self.sandbox_id,
                "MASS_FILE_WRITE",
                f"Mass file write: {len(self._write_times)} files in {_MASS_WRITE_WINDOW}s",
                risk_delta=25,
                details={"count": len(self._write_times), "window_sec": _MASS_WRITE_WINDOW},
            )
            return False

        return True

    def record_delete(self, path: str) -> bool:
        """Call this whenever a file delete is detected. Returns False on mass-delete alert."""
        allowed, reason = self.validate_path(path, "delete")
        if not allowed:
            return False

        now = time.monotonic()
        self._delete_times.append(now)
        while self._delete_times and (now - self._delete_times[0]) > _MASS_DELETE_WINDOW:
            self._delete_times.popleft()

        self.files_deleted += 1

        if len(self._delete_times) >= _MASS_DELETE_THRESHOLD:
            self._audit.record_violation(
                self.sandbox_id,
                "MASS_FILE_DELETE",
                f"Mass file delete: {len(self._delete_times)} files in {_MASS_DELETE_WINDOW}s",
                risk_delta=35,
                details={"count": len(self._delete_times), "window_sec": _MASS_DELETE_WINDOW},
            )
            return False

        return True

    # ── Directory scan ─────────────────────────────────────────────────────────

    def scan_workspace(self) -> Dict:
        """Scan the sandbox workspace and return file inventory with anomaly flags."""
        if not self.workspace_root.exists():
            return {"files": [], "anomalies": [], "count": 0}

        files: List[Dict] = []
        anomalies: List[str] = []

        for f in self.workspace_root.rglob("*"):
            if not f.is_file() or f.name == ".sandbox_manifest.json":
                continue
            rel = str(f.relative_to(self.workspace_root))
            size = 0
            try:
                size = f.stat().st_size
            except OSError:
                pass
            entry = {"path": rel, "size_bytes": size}

            # Flag hidden files
            if f.name.startswith(".") and f.name != ".sandbox_manifest.json":
                anomalies.append(f"hidden_file:{rel}")
                entry["anomaly"] = "hidden"

            # Flag very large files
            if size > 10 * 1024 * 1024:  # 10 MB
                anomalies.append(f"large_file:{rel}:{size}")
                entry["anomaly"] = "large"

            # Flag executables
            if f.suffix.lower() in (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".sh"):
                anomalies.append(f"executable:{rel}")
                entry["anomaly"] = "executable"

            files.append(entry)

        return {"files": files, "anomalies": anomalies, "count": len(files)}
