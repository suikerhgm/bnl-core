"""
FilesystemJail — path enforcement and file-operation rate tracking for isolated processes.

Distinct from sandbox_filesystem_guard (which operates inside a temp workspace):
  - FilesystemJail watches *running* Nexus agent processes
  - Tracks open file handles via psutil
  - Detects attempts to access paths outside the allowed workspace root
  - Detects suspicious file patterns (registry, credentials, system dirs)
  - Rate-limits file write/delete bursts per isolation level

Integration: used by RuntimeGuardian during each monitoring tick.
"""

import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

logger = logging.getLogger(__name__)

# ── Suspicious path patterns ───────────────────────────────────────────────────

_SYSTEM_PATH_PATTERNS = [
    re.compile(r"(?i)(windows[/\\]system32|windows[/\\]syswow64)"),
    re.compile(r"(?i)(program\s*files[/\\])"),
    re.compile(r"(?i)(appdata[/\\](roaming|local)[/\\])"),
    re.compile(r"(?i)(\\.env$|\\.ssh[/\\]|credentials|secrets?[/\\])"),
    re.compile(r"(?i)(ntds\.dit|sam|security\.hive|system\.hive)"),
    re.compile(r"(?i)(/etc/(passwd|shadow|sudoers|hosts)|/proc/|/sys/)"),
    re.compile(r"(?i)(autorun\.inf|\.lnk$|startup[/\\])"),
]

_WRITE_BURST_WINDOW   = 10   # seconds
_WRITE_BURST_THRESHOLD = 50  # files
_DEL_BURST_WINDOW      = 5
_DEL_BURST_THRESHOLD   = 10


class FilesystemJail:
    """
    Per-isolation-context filesystem watcher.
    Inspects open file handles for a process tree via psutil on each tick.
    """

    def __init__(
        self,
        process_id: str,
        workspace_root: str,
        max_file_writes: int = 200,
    ) -> None:
        self.process_id     = process_id
        self.workspace_root = Path(os.path.realpath(os.path.abspath(workspace_root)))
        self.max_file_writes = max_file_writes

        self._seen_paths:   Set[str] = set()
        self._write_times:  deque   = deque()
        self._delete_times: deque   = deque()

        self.total_file_accesses  = 0
        self.escape_attempts      = 0
        self.suspicious_paths     = 0

    def inspect(self, pid: int) -> List[Dict]:
        """
        Scan open file handles for pid and its tree.
        Returns list of violations: [{type, path, description, risk_delta}]
        """
        if not _PSUTIL:
            return []

        violations = []
        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

        for proc in tree:
            try:
                for f in proc.open_files():
                    path = f.path if hasattr(f, "path") else str(f)
                    if not path or path in self._seen_paths:
                        continue
                    self._seen_paths.add(path)
                    self.total_file_accesses += 1
                    v = self._evaluate_path(path)
                    if v:
                        violations.append(v)
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

        return violations

    def record_write(self, path: str = "") -> Optional[Dict]:
        """Called when a file write is detected. Returns violation or None."""
        now = time.monotonic()
        self._write_times.append(now)
        while self._write_times and (now - self._write_times[0]) > _WRITE_BURST_WINDOW:
            self._write_times.popleft()
        if len(self._write_times) >= _WRITE_BURST_THRESHOLD:
            return {
                "type": "MASS_FILE_WRITE",
                "path": path,
                "description": f"Mass write: {len(self._write_times)} files in {_WRITE_BURST_WINDOW}s",
                "risk_delta": 25,
            }
        return None

    def record_delete(self, path: str = "") -> Optional[Dict]:
        """Called when a file delete is detected. Returns violation or None."""
        now = time.monotonic()
        self._delete_times.append(now)
        while self._delete_times and (now - self._delete_times[0]) > _DEL_BURST_WINDOW:
            self._delete_times.popleft()
        if len(self._delete_times) >= _DEL_BURST_THRESHOLD:
            return {
                "type": "MASS_FILE_DELETE",
                "path": path,
                "description": f"Mass delete: {len(self._delete_times)} files in {_DEL_BURST_WINDOW}s",
                "risk_delta": 35,
            }
        return None

    def validate_path(self, path: str) -> Tuple[bool, str]:
        """
        Synchronous path check usable outside the monitor tick.
        Returns (allowed, reason).
        """
        try:
            abs_path = Path(os.path.realpath(os.path.abspath(path)))
            within   = str(abs_path).startswith(str(self.workspace_root))
        except Exception:
            return False, "path_error"

        if not within:
            self.escape_attempts += 1
            logger.warning("[PROCESS_JAIL] Workspace escape: %s", path[:80])
            return False, "workspace_escape"

        for pat in _SYSTEM_PATH_PATTERNS:
            if pat.search(str(abs_path)):
                self.suspicious_paths += 1
                return False, f"sensitive_path"

        return True, "ok"

    # ── Internal ───────────────────────────────────────────────────────────────

    def _evaluate_path(self, path: str) -> Optional[Dict]:
        allowed, reason = self.validate_path(path)
        if allowed:
            return None

        if reason == "workspace_escape":
            return {
                "type": "WORKSPACE_ESCAPE",
                "path": path,
                "description": f"File access outside workspace: {path[:100]}",
                "risk_delta": 30,
            }
        if "sensitive" in reason:
            return {
                "type": "SENSITIVE_PATH_ACCESS",
                "path": path,
                "description": f"Sensitive path accessed: {path[:100]}",
                "risk_delta": 20,
            }
        return None
