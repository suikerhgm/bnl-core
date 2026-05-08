"""
core/runtime/process_manager.py
================================
Global singleton that tracks all live processes spawned by CommandAction.
Provides: register, log streaming, port detection, stop, get, restart data.
"""
import asyncio
import re
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.persistence import (
    load_process_history,
    load_process_states,
    save_process_history_entry,
    save_process_state,
)

logger = logging.getLogger(__name__)

# Ordered by specificity — first match wins
_PORT_PATTERNS = [
    re.compile(r"(?:localhost|127\.0\.0\.1):(\d{4,5})"),
    re.compile(r"(?:port|PORT)[:\s=]+(\d{4,5})"),
    re.compile(r"listening[^\d]+(\d{4,5})", re.IGNORECASE),
    re.compile(r"started[^\d]+:(\d{4,5})", re.IGNORECASE),
    re.compile(r"running\s+on\s+.*:(\d{4,5})", re.IGNORECASE),
    re.compile(r":(\d{4,5})(?:\s|/|$)"),
]

MAX_LOG_LINES = 500
MAX_HISTORY   = 100


def extract_port(line: str) -> Optional[str]:
    """Parse a log line for a port number (1024–65535)."""
    for pat in _PORT_PATTERNS:
        m = pat.search(line)
        if m:
            port = m.group(1)
            if 1024 <= int(port) <= 65535:
                return port
    return None


class ProcessManager:
    """In-memory registry of running child processes."""

    def __init__(self) -> None:
        self._processes: Dict[str, dict] = {}
        self._history:   List[dict]      = []
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Restore persisted process state and history on startup.

        Status is loaded as-is from the DB so that processes launched by
        *other* instances of the app (e.g. the backend while the dashboard
        is reading) are shown with their real status ("running") rather than
        always being overridden to "stopped".

        The ``process`` handle is always ``None`` because a Popen object
        cannot survive serialisation — control actions on remote processes
        are no-ops that fail gracefully.
        """
        try:
            states = load_process_states()
            for s in states:
                self._processes[s["project_id"]] = {
                    "process": None,
                    "status":  s["status"],   # real DB status, not always "stopped"
                    "logs":    deque(maxlen=MAX_LOG_LINES),
                    "port":    s["port"],
                    "command": s["command"],
                    "cwd":     s["cwd"],
                }
            if states:
                logger.info(
                    "📋 ProcessManager: restored %d process record(s) from DB",
                    len(states),
                )
        except Exception as exc:
            logger.warning("⚠️ ProcessManager: failed to restore process states: %s", exc)

        try:
            # DB returns newest-first; _history is oldest-first (reversed on get_history())
            history_rows = load_process_history()
            self._history = list(reversed(history_rows))
            if self._history:
                logger.info(
                    "📜 ProcessManager: restored %d history entries from DB",
                    len(self._history),
                )
        except Exception as exc:
            logger.warning("⚠️ ProcessManager: failed to restore history: %s", exc)

    def sync_from_db(self) -> None:
        """
        Re-read DB state and merge it into memory.

        Processes that THIS instance owns (``process`` is not None) are left
        untouched — their in-memory state is authoritative.  Processes that
        this instance does not own (``process`` is None, i.e. launched by
        another server instance) are refreshed from the DB so the dashboard
        always shows their current status and port.
        """
        try:
            for s in load_process_states():
                pid = s["project_id"]
                if pid in self._processes:
                    entry = self._processes[pid]
                    if entry["process"] is None:
                        # Remote process — update mutable fields from DB
                        entry["status"] = s["status"]
                        if s["port"] and entry["port"] is None:
                            entry["port"] = s["port"]
                else:
                    # New process started by another instance after our startup
                    self._processes[pid] = {
                        "process": None,
                        "status":  s["status"],
                        "logs":    deque(maxlen=MAX_LOG_LINES),
                        "port":    s["port"],
                        "command": s["command"],
                        "cwd":     s["cwd"],
                    }
        except Exception as exc:
            logger.warning("⚠️ ProcessManager: sync_from_db failed: %s", exc)

    # ── Write ──────────────────────────────────────────────────────────

    def register(
        self,
        project_id: str,
        process: asyncio.subprocess.Process,
        command: Any,   # List[str] from CommandAction
        cwd: str,
    ) -> None:
        self._processes[project_id] = {
            "process": process,
            "status": "running",
            "logs": deque(maxlen=MAX_LOG_LINES),
            "port": None,
            "command": command,
            "cwd": cwd,
        }
        logger.info("📋 ProcessManager: registered '%s' pid=%s", project_id, process.pid)
        save_process_state(project_id, "running", None, command, cwd)

    def update_log(self, project_id: str, line: str) -> None:
        entry = self._processes.get(project_id)
        if entry is None:
            return
        if len(line) > 500:
            line = line[:500]
        entry["logs"].append(line)  # deque(maxlen=500) caps total count

    def set_status(self, project_id: str, status: str) -> None:
        entry = self._processes.get(project_id)
        if entry is None:
            return
        entry["status"] = status
        logger.info("📋 ProcessManager: '%s' → %s", project_id, status)
        # Persist updated status (covers both running→stopped and running→failed)
        save_process_state(project_id, status, entry["port"], entry["command"], entry["cwd"])
        # Archive terminal transitions to in-memory history and DB
        if status in ("stopped", "failed"):
            record = {
                "project_id":  project_id,
                "status":      status,
                "port":        entry["port"],
                "command":     entry["command"],
                "logs":        list(entry["logs"])[-50:],
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._history.append(record)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]
            save_process_history_entry(record)
            logger.info("📜 History: archived '%s' (%s)", project_id, status)

    def set_port(self, project_id: str, port: str) -> None:
        entry = self._processes.get(project_id)
        if entry is not None and entry["port"] is None:
            entry["port"] = port
            logger.info("🔌 ProcessManager: '%s' port detected → %s", project_id, port)
            save_process_state(project_id, entry["status"], port, entry["command"], entry["cwd"])

    # ── Control ────────────────────────────────────────────────────────

    def stop(self, project_id: str) -> bool:
        entry = self._processes.get(project_id)
        if entry is None:
            return False
        proc = entry.get("process")
        if proc and entry["status"] == "running":
            try:
                proc.terminate()
            except Exception:
                pass
            entry["status"] = "stopped"
            # Persist immediately so other processes see the updated status
            save_process_state(
                project_id, "stopped", entry["port"], entry["command"], entry["cwd"]
            )
            logger.info("🛑 ProcessManager: stopped '%s'", project_id)
            return True
        return False

    # ── Read ───────────────────────────────────────────────────────────

    def get(self, project_id: str) -> Optional[dict]:
        """Return a safe (no Process object) snapshot.

        is_local — True when this instance owns the live process handle,
                   False for processes restored from DB or started by another server.
        """
        entry = self._processes.get(project_id)
        if entry is None:
            return None
        proc = entry.get("process")
        pid = None
        try:
            pid = proc.pid if proc is not None else None
        except Exception:
            pass
        return {
            "status":   entry.get("status", "unknown"),
            "logs":     list(entry.get("logs", [])),
            "port":     entry.get("port"),
            "command":  entry.get("command"),
            "cwd":      entry.get("cwd", ""),
            "pid":      pid,
            "is_local": proc is not None,   # streaming hint — never exposes the Process object
        }

    def get_raw(self, project_id: str) -> Optional[dict]:
        """Return the internal entry (includes Process object, needed for restart)."""
        return self._processes.get(project_id)

    def list_ids(self) -> List[str]:
        return list(self._processes.keys())

    def stop_all(self) -> int:
        """Terminate every registered process. Returns the count of processes stopped."""
        count = 0
        for pid in list(self._processes.keys()):
            if self.stop(pid):
                count += 1
        logger.info("🛑 ProcessManager: stop_all — %d process(es) terminated", count)
        return count

    def get_history(self) -> List[dict]:
        """Return all archived executions, newest first."""
        return list(reversed(self._history))

    def list_all(self) -> List[dict]:
        """Return a summary of every registered process (safe — no Process objects)."""
        result = []
        for project_id, data in self._processes.items():
            proc = data.get("process")
            pid = proc.pid if proc is not None else None
            result.append({
                "project_id": project_id,
                "status":     data["status"],
                "port":       data["port"],
                "command":    data["command"],
                "pid":        pid,
            })
        return result


# ── Module-level singleton ─────────────────────────────────────────────────

_instance: Optional[ProcessManager] = None


def get_manager() -> ProcessManager:
    global _instance
    if _instance is None:
        _instance = ProcessManager()
    return _instance
