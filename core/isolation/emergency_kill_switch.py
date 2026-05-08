"""
EmergencyKillSwitch — escalation ladder and emergency response for Nexus BNL.

Escalation ladder (each step is more aggressive than the last):
    1. WARN       — log warning, no action
    2. FREEZE     — suspend process tree (psutil.suspend)
    3. KILL       — SIGKILL the process tree
    4. QUARANTINE — kill + preserve workspace + revoke agent permissions
    5. LOCKDOWN   — quarantine + broadcast system-wide emergency + halt new executions

Emergency actions:
    kill_suspicious_process(pid)   — immediate SIGKILL for a specific PID
    emergency_shutdown(reason)     — LOCKDOWN: freeze all isolations, log EMERGENCY event
    freeze_process(pid)            — SIGSTOP / psutil.suspend
    unfreeze_process(pid)          — SIGCONT / psutil.resume

Integration:
    - Calls SecurityPolicyEngine to isolate the associated agent
    - Calls SandboxManager.quarantine_sandbox() if a sandbox_id is known
    - Persists emergency events to the IsolationManager DB
"""

import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"


class EmergencyKillSwitch:
    """
    Stateless response executor. All state lives in IsolationManager.
    Call freeze/kill/quarantine/lockdown with a process_id + pid.
    Callbacks wire back to the manager for DB updates and cross-system integration.
    """

    def __init__(
        self,
        on_quarantine: Optional[Callable[[str, str], None]] = None,
        on_lockdown:   Optional[Callable[[str], None]] = None,
        on_event:      Optional[Callable[[str, str, str, str], None]] = None,
    ) -> None:
        """
        Args:
            on_quarantine: (process_id, reason) → called on QUARANTINE action
            on_lockdown:   (reason,) → called on LOCKDOWN action
            on_event:      (process_id, action, description, severity) → DB logger
        """
        self._on_quarantine = on_quarantine
        self._on_lockdown   = on_lockdown
        self._on_event      = on_event
        self._lock          = threading.Lock()
        self._lockdown_active = False

    # ── Escalation entry point ─────────────────────────────────────────────────

    def respond(
        self,
        process_id: str,
        pid: Optional[int],
        risk_score: int,
        agent_id: Optional[str] = None,
        reason: str = "threshold_exceeded",
    ) -> str:
        """
        Choose and execute the appropriate response based on risk_score.
        Returns the action taken: WARN / FREEZE / KILL / QUARANTINE / LOCKDOWN
        """
        if risk_score < 20:
            return self._warn(process_id, reason)
        if risk_score < 40:
            return self._freeze(process_id, pid, reason)
        if risk_score < 60:
            return self._kill(process_id, pid, reason)
        if risk_score < 80:
            return self._quarantine(process_id, pid, agent_id, reason)
        return self._lockdown(process_id, pid, agent_id, reason)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _warn(self, process_id: str, reason: str) -> str:
        msg = f"[ISOLATION] WARN process={process_id}: {reason}"
        logger.warning(msg)
        self._emit(process_id, "WARN", reason, "WARNING")
        return "WARN"

    def _freeze(self, process_id: str, pid: Optional[int], reason: str) -> str:
        logger.warning("[ISOLATION] FREEZE process=%s pid=%s: %s", process_id, pid, reason)
        if pid:
            self.freeze_process(pid)
        self._emit(process_id, "FREEZE", f"Process frozen: {reason}", "WARNING")
        return "FREEZE"

    def _kill(self, process_id: str, pid: Optional[int], reason: str) -> str:
        logger.error("[ISOLATION] KILL process=%s pid=%s: %s", process_id, pid, reason)
        if pid:
            self.kill_process_tree(pid, reason)
        self._emit(process_id, "KILL", f"Process killed: {reason}", "CRITICAL")
        return "KILL"

    def _quarantine(
        self,
        process_id: str,
        pid: Optional[int],
        agent_id: Optional[str],
        reason: str,
    ) -> str:
        logger.critical("[ISOLATION] QUARANTINE process=%s pid=%s agent=%s: %s",
                        process_id, pid, agent_id, reason)
        if pid:
            self.kill_process_tree(pid, reason)

        # Revoke agent permissions via Security system
        if agent_id:
            self._revoke_agent_permissions(agent_id, reason)

        self._emit(process_id, "QUARANTINE", f"Quarantined: {reason}", "CRITICAL")
        if self._on_quarantine:
            try:
                self._on_quarantine(process_id, reason)
            except Exception as exc:
                logger.error("[EMERGENCY] on_quarantine callback error: %s", exc)
        return "QUARANTINE"

    def _lockdown(
        self,
        process_id: str,
        pid: Optional[int],
        agent_id: Optional[str],
        reason: str,
    ) -> str:
        with self._lock:
            if self._lockdown_active:
                logger.warning("[EMERGENCY] Lockdown already active — re-triggering kill only")
                if pid:
                    self.kill_process_tree(pid, reason)
                return "LOCKDOWN"
            self._lockdown_active = True

        logger.critical("[EMERGENCY] LOCKDOWN TRIGGERED — process=%s reason=%s", process_id, reason)
        if pid:
            self.kill_process_tree(pid, reason)
        if agent_id:
            self._revoke_agent_permissions(agent_id, reason)

        self._emit(process_id, "LOCKDOWN", f"SYSTEM LOCKDOWN: {reason}", "CRITICAL")
        if self._on_lockdown:
            try:
                self._on_lockdown(reason)
            except Exception as exc:
                logger.error("[EMERGENCY] on_lockdown callback error: %s", exc)
        return "LOCKDOWN"

    # ── Process control ────────────────────────────────────────────────────────

    def kill_suspicious_process(self, pid: int, reason: str = "suspicious_behavior") -> bool:
        """Immediately SIGKILL a specific process. Logs [EMERGENCY]."""
        logger.critical("[EMERGENCY] kill_suspicious_process pid=%d reason=%s", pid, reason)
        return self.kill_process_tree(pid, reason)

    def kill_process_tree(self, pid: int, reason: str = "") -> bool:
        """Kill a process and all its descendants."""
        if not _PSUTIL:
            return _raw_kill(pid)

        killed = 0
        try:
            root = psutil.Process(pid)
            children = root.children(recursive=True)
            all_procs = [root] + list(children)

            for p in reversed(all_procs):
                try:
                    p.kill()
                    killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            logger.info("[EMERGENCY] Killed %d processes (root pid=%d)", killed, pid)
            return killed > 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return _raw_kill(pid)

    def freeze_process(self, pid: int) -> bool:
        """Suspend all processes in tree."""
        if not _PSUTIL:
            return False
        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
            for p in tree:
                try:
                    p.suspend()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            logger.info("[ISOLATION] Frozen %d processes (root pid=%d)", len(tree), pid)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def unfreeze_process(self, pid: int) -> bool:
        """Resume suspended processes."""
        if not _PSUTIL:
            return False
        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
            for p in tree:
                try:
                    p.resume()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            logger.info("[ISOLATION] Resumed %d processes (root pid=%d)", len(tree), pid)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def emergency_shutdown(self, reason: str) -> None:
        """
        Broadcast LOCKDOWN to all registered components.
        Does NOT exit the Python process — only stops new executions
        and fires the lockdown callback.
        """
        logger.critical("[EMERGENCY] EMERGENCY SHUTDOWN: %s", reason)
        self._emit("SYSTEM", "EMERGENCY_SHUTDOWN", reason, "CRITICAL")
        if self._on_lockdown:
            try:
                self._on_lockdown(reason)
            except Exception:
                pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _revoke_agent_permissions(agent_id: str, reason: str) -> None:
        try:
            from core.security.capability_guard import get_guard
            guard = get_guard()
            guard.isolate(agent_id, reason=f"[ISOLATION] {reason}", by="emergency_kill_switch")
            logger.info("[ISOLATION] Agent %s isolated in security system", agent_id)
        except Exception as exc:
            logger.warning("[ISOLATION] Could not isolate agent %s: %s", agent_id, exc)

    def _emit(
        self,
        process_id: str,
        action: str,
        description: str,
        severity: str,
    ) -> None:
        logger.log(
            logging.CRITICAL if severity == "CRITICAL" else logging.WARNING,
            "[RUNTIME_GUARD] [%s] %s: %s", severity, action, description,
        )
        if self._on_event:
            try:
                self._on_event(process_id, action, description, severity)
            except Exception as exc:
                logger.error("[EMERGENCY] _emit callback error: %s", exc)

    @property
    def lockdown_active(self) -> bool:
        return self._lockdown_active

    def release_lockdown(self) -> None:
        with self._lock:
            self._lockdown_active = False
        logger.info("[EMERGENCY] Lockdown released by admin")


# ── Utility ────────────────────────────────────────────────────────────────────

def _raw_kill(pid: int) -> bool:
    """Fallback kill without psutil."""
    try:
        if _IS_WINDOWS:
            import subprocess
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
        return True
    except Exception as exc:
        logger.error("[EMERGENCY] _raw_kill(%d) failed: %s", pid, exc)
        return False
