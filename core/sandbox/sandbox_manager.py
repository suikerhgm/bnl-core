"""
SandboxManager — main orchestrator for the Nexus BNL Sandbox System.

This is the single public entry point. All external code should use this class
rather than instantiating the sub-components directly.

Lifecycle:
    create_sandbox()       → CREATED
    execute_in_sandbox()   → RUNNING  (starts process + monitoring)
    freeze_sandbox()       → FROZEN   (process suspended)
    quarantine_sandbox()   → QUARANTINED (killed + preserved for forensics)
    destroy_sandbox()      → DESTROYED  (killed + workspace cleaned)
    export_sandbox_logs()  → dict of all audit data

Integration:
    - Permission System: checks sandbox.scan / sandbox.approve / sandbox.reject
    - Security Policy Engine: reports isolation events
    - Agent Registry: links sandboxes to agent_id
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.sandbox.sandbox_audit_logger import SandboxAuditLogger, get_audit_logger
from core.sandbox.sandbox_environment import (
    SandboxEnvironment,
    SandboxMode,
    SandboxStatus,
    create_environment,
)
from core.sandbox.sandbox_filesystem_guard import SandboxFilesystemGuard
from core.sandbox.sandbox_network_guard import SandboxNetworkGuard
from core.sandbox.sandbox_process_monitor import SandboxProcessMonitor

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"


class SandboxManager:
    """
    Thread-safe singleton that manages the full lifecycle of all sandboxes.

    Usage:
        mgr = get_sandbox_manager()
        result = mgr.execute_in_sandbox(
            command=["python", "script.py"],
            mode="RESTRICTED_EXECUTION",
            agent_id="agent_001",
        )
    """

    _instance: Optional["SandboxManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SandboxManager":
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
            self._audit = get_audit_logger()
            # In-memory registry of active environments
            self._envs: Dict[str, SandboxEnvironment]        = {}
            self._monitors: Dict[str, SandboxProcessMonitor] = {}
            self._procs: Dict[str, Any]                      = {}  # sandbox_id → subprocess.Popen
            self._env_lock = threading.Lock()
            self._initialized = True
            logger.info("[SANDBOX] SandboxManager initialized")

    # ── Create ─────────────────────────────────────────────────────────────────

    def create_sandbox(
        self,
        agent_id: Optional[str] = None,
        mode: str = "RESTRICTED_EXECUTION",
        sandbox_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> SandboxEnvironment:
        """
        Create a new sandbox environment. Does NOT execute anything yet.
        Returns the SandboxEnvironment.
        """
        env = create_environment(agent_id=agent_id, mode=mode, sandbox_id=sandbox_id)
        self._audit.create_sandbox_record(
            sandbox_id=env.sandbox_id,
            agent_id=agent_id,
            mode=mode,
            workspace_path=str(env.workspace_path),
            metadata=metadata,
        )
        self._audit.log_event(
            env.sandbox_id, "SANDBOX_CREATED",
            f"Sandbox created in mode {mode}", severity="INFO",
            metadata={"agent_id": agent_id, "mode": mode},
        )
        with self._env_lock:
            self._envs[env.sandbox_id] = env
        logger.info("[SANDBOX] Created sandbox=%s mode=%s agent=%s",
                    env.sandbox_id, mode, agent_id)
        return env

    # ── Execute ────────────────────────────────────────────────────────────────

    def execute_in_sandbox(
        self,
        command: List[str],
        mode: str = "RESTRICTED_EXECUTION",
        agent_id: Optional[str] = None,
        sandbox_id: Optional[str] = None,
        input_files: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a command inside a fresh sandbox and return the result.

        Returns:
            {
                "sandbox_id": str,
                "success":    bool,
                "stdout":     str,
                "stderr":     str,
                "exit_code":  int | None,
                "risk_score": int,
                "quarantined": bool,
                "violations": list,
                "duration_sec": float,
            }
        """
        env = self.create_sandbox(agent_id=agent_id, mode=mode, sandbox_id=sandbox_id)
        cfg = env.config

        # Write any input files into the workspace
        if input_files:
            for fname, content in input_files.items():
                env.add_input_file(fname, content)

        # Build guards
        fs_guard = SandboxFilesystemGuard(
            sandbox_id=env.sandbox_id,
            workspace_path=str(env.workspace_path),
            allow_write=cfg["allow_fs_write"],
        )
        net_guard = SandboxNetworkGuard(
            sandbox_id=env.sandbox_id,
            allow_network=cfg["allow_network"],
            local_only=not cfg["allow_network"],
        )

        # If mode is STATIC_ANALYSIS — no execution
        if env.mode == SandboxMode.STATIC_ANALYSIS:
            return self._static_analysis(env, command, input_files or {})

        # Build monitored subprocess
        actual_timeout = timeout or cfg["max_duration_sec"]

        self._audit.log_event(
            env.sandbox_id, "SANDBOX_EXEC_START",
            f"Executing: {' '.join(command[:3])}…", severity="INFO",
        )
        self._audit.update_sandbox(env.sandbox_id, status="running",
                                   started_at=_now())
        env.status = SandboxStatus.RUNNING
        env.started_at = _now()

        # Prepare subprocess environment (stripped to minimum)
        proc_env = self._build_safe_env(str(env.workspace_path), env_vars)

        import time as _time
        t0 = _time.monotonic()
        stdout_data = b""
        stderr_data = b""
        exit_code   = None

        try:
            proc = subprocess.Popen(
                command,
                cwd=str(env.workspace_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WINDOWS else 0,
            )
            env.pid = proc.pid
            self._audit.update_sandbox(env.sandbox_id, pid=proc.pid)

            with self._env_lock:
                self._procs[env.sandbox_id] = proc

            # Start process monitor
            monitor = SandboxProcessMonitor(
                sandbox_id=env.sandbox_id,
                workspace_path=str(env.workspace_path),
                max_cpu_pct=cfg["max_cpu_pct"],
                max_ram_mb=cfg["max_ram_mb"],
                max_duration_sec=actual_timeout,
                auto_quarantine_score=cfg["auto_quarantine_score"],
                interval_sec=cfg["monitor_interval_sec"],
                quarantine_callback=self._auto_quarantine_callback,
                net_guard=net_guard,
            )
            monitor.start(proc.pid)
            with self._env_lock:
                self._monitors[env.sandbox_id] = monitor

            try:
                stdout_data, stderr_data = proc.communicate(timeout=actual_timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                self._kill_process(proc)
                stdout_data, stderr_data = proc.communicate()
                exit_code = -1
                self._audit.record_violation(
                    env.sandbox_id, "EXECUTION_TIMEOUT",
                    f"Process exceeded timeout {actual_timeout}s", risk_delta=15,
                )

            monitor.stop()

        except FileNotFoundError:
            self._audit.log_event(
                env.sandbox_id, "EXEC_ERROR",
                f"Command not found: {command[0]}", severity="WARNING",
            )
            exit_code = -2
        except Exception as exc:
            logger.error("[SANDBOX] execute error sandbox=%s: %s", env.sandbox_id, exc)
            exit_code = -3

        duration = _time.monotonic() - t0

        # Determine final status
        db = self._audit.get_sandbox(env.sandbox_id)
        risk = db.get("risk_score", 0) if db else 0
        quarantined = db.get("status") == "quarantined" if db else False

        if not quarantined:
            final_status = "completed"
            self._audit.update_sandbox(env.sandbox_id, status="completed", exit_code=exit_code)
            env.status = SandboxStatus.COMPLETED

        violations = self._audit.get_violations(env.sandbox_id)

        self._audit.log_event(
            env.sandbox_id, "SANDBOX_EXEC_END",
            f"Execution finished: exit={exit_code} risk={risk} dur={duration:.1f}s",
            severity="INFO" if risk < 30 else "WARNING",
        )

        result = {
            "sandbox_id":   env.sandbox_id,
            "success":      exit_code == 0,
            "stdout":       stdout_data.decode("utf-8", errors="replace") if stdout_data else "",
            "stderr":       stderr_data.decode("utf-8", errors="replace") if stderr_data else "",
            "exit_code":    exit_code,
            "risk_score":   risk,
            "quarantined":  quarantined,
            "violations":   violations,
            "duration_sec": round(duration, 2),
            "workspace":    str(env.workspace_path),
        }

        # Cleanup (unless quarantined — preserve for forensics)
        if not quarantined:
            self.destroy_sandbox(env.sandbox_id)

        return result

    # ── Static analysis ────────────────────────────────────────────────────────

    def _static_analysis(
        self,
        env: SandboxEnvironment,
        command: List[str],
        input_files: Dict[str, str],
    ) -> Dict[str, Any]:
        """Analyze code without executing it. Scans for dangerous patterns."""
        from core.sandbox.sandbox_process_monitor import _DANGEROUS_CMDS, _OBFUSCATION_PATTERNS

        findings: List[str] = []
        risk = 0

        for fname, content in input_files.items():
            for pat in _DANGEROUS_CMDS:
                if pat.search(content):
                    findings.append(f"dangerous_pattern in {fname}: {pat.pattern[:40]}")
                    risk += 15
            for pat in _OBFUSCATION_PATTERNS:
                if pat.search(content):
                    findings.append(f"obfuscation in {fname}")
                    risk += 20

        risk = min(100, risk)
        self._audit.update_sandbox(env.sandbox_id, status="completed", risk_score=risk)
        self._audit.log_event(
            env.sandbox_id, "STATIC_ANALYSIS_DONE",
            f"Static analysis: {len(findings)} findings, risk={risk}",
            severity="WARNING" if findings else "INFO",
        )
        self.destroy_sandbox(env.sandbox_id)

        return {
            "sandbox_id":  env.sandbox_id,
            "mode":        "STATIC_ANALYSIS",
            "success":     True,
            "findings":    findings,
            "risk_score":  risk,
            "quarantined": False,
            "stdout": "", "stderr": "", "exit_code": None,
            "violations": [], "duration_sec": 0,
        }

    # ── Lifecycle control ──────────────────────────────────────────────────────

    def freeze_sandbox(self, sandbox_id: str) -> bool:
        """Suspend the sandbox process (SIGSTOP on Linux, NtSuspendProcess on Windows)."""
        proc = self._procs.get(sandbox_id)
        env  = self._envs.get(sandbox_id)
        if not proc or not env:
            return False
        try:
            if _IS_WINDOWS and _PSUTIL:
                ps_proc = psutil.Process(proc.pid)
                ps_proc.suspend()
            elif not _IS_WINDOWS:
                os.kill(proc.pid, signal.SIGSTOP)
            env.status = SandboxStatus.FROZEN
            env.frozen_at = _now()
            self._audit.update_sandbox(sandbox_id, status="frozen", frozen_at=env.frozen_at)
            self._audit.log_event(sandbox_id, "SANDBOX_FROZEN", "Sandbox frozen", severity="INFO")
            logger.info("[SANDBOX] Frozen: %s", sandbox_id)
            return True
        except Exception as exc:
            logger.warning("[SANDBOX] freeze failed %s: %s", sandbox_id, exc)
            return False

    def quarantine_sandbox(self, sandbox_id: str, reason: str = "manual") -> bool:
        """
        Quarantine: kill the process, preserve workspace, mark status.
        The workspace is kept for forensic investigation.
        """
        env  = self._envs.get(sandbox_id)
        proc = self._procs.get(sandbox_id)
        mon  = self._monitors.get(sandbox_id)

        if mon:
            mon.stop()

        if proc:
            self._kill_process(proc)

        if env:
            env.status         = SandboxStatus.QUARANTINED
            env.quarantined_at = _now()
            env.preserve_on_exit = True

        self._audit.update_sandbox(sandbox_id, status="quarantined",
                                   quarantined_at=_now())
        self._audit.log_event(
            sandbox_id, "SANDBOX_QUARANTINED",
            f"Quarantined: {reason}", severity="CRITICAL",
        )
        logger.critical("[SANDBOX] Quarantined sandbox=%s reason=%s", sandbox_id, reason)

        # Notify security policy engine
        try:
            from core.security.policy_engine import get_policy_engine
            get_policy_engine().detect_policy_violation(
                agent_id=env.agent_id if env else "unknown",
                event_type="SANDBOX_QUARANTINE",
                permission_id="sandbox.approve",
                context={"sandbox_id": sandbox_id, "reason": reason},
            )
        except Exception:
            pass

        return True

    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """Destroy sandbox: kill process, clean workspace, remove from memory."""
        env  = self._envs.get(sandbox_id)
        proc = self._procs.get(sandbox_id)
        mon  = self._monitors.get(sandbox_id)

        if mon:
            mon.stop()
        if proc and proc.poll() is None:
            self._kill_process(proc)
        if env:
            env.teardown_workspace()
            env.status       = SandboxStatus.DESTROYED
            env.destroyed_at = _now()

        self._audit.update_sandbox(sandbox_id, status="destroyed", destroyed_at=_now())
        self._audit.log_event(sandbox_id, "SANDBOX_DESTROYED",
                              "Sandbox destroyed", severity="INFO")

        with self._env_lock:
            self._envs.pop(sandbox_id, None)
            self._procs.pop(sandbox_id, None)
            self._monitors.pop(sandbox_id, None)

        logger.info("[SANDBOX] Destroyed: %s", sandbox_id)
        return True

    def monitor_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Return current live status + latest resource snapshot."""
        env  = self._envs.get(sandbox_id)
        snap = self._audit.get_latest_snapshot(sandbox_id)
        db   = self._audit.get_sandbox(sandbox_id)
        if not db:
            return None
        return {
            "sandbox": db,
            "latest_snapshot": snap,
            "in_memory": env is not None,
        }

    def export_sandbox_logs(self, sandbox_id: str) -> Dict[str, Any]:
        """Full forensic export of all sandbox audit data."""
        return self._audit.export_sandbox_logs(sandbox_id)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _auto_quarantine_callback(self, sandbox_id: str, reason: str) -> None:
        """Called by SandboxProcessMonitor when the risk threshold is exceeded."""
        self.quarantine_sandbox(sandbox_id, reason=f"auto: {reason}")

    def _kill_process(self, proc: subprocess.Popen) -> None:
        try:
            if _IS_WINDOWS:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _build_safe_env(cwd: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build a stripped environment for the sandbox process."""
        safe = {
            "PATH":     os.environ.get("PATH", ""),
            "TEMP":     cwd,
            "TMP":      cwd,
            "HOME":     cwd,
            "USERPROFILE": cwd,
            "SANDBOX":  "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if extra:
            for k, v in extra.items():
                if k not in ("SYSTEMROOT", "WINDIR"):  # never override OS paths
                    safe[k] = v
        # Always include SYSTEMROOT on Windows (needed for basic process startup)
        if _IS_WINDOWS:
            for key in ("SYSTEMROOT", "WINDIR", "COMSPEC"):
                if key in os.environ:
                    safe[key] = os.environ[key]
        return safe

    # ── Queries ────────────────────────────────────────────────────────────────

    def list_sandboxes(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._audit.list_sandboxes(status=status, agent_id=agent_id, limit=limit)

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        return self._audit.get_sandbox(sandbox_id)

    def get_stats(self) -> Dict[str, Any]:
        return self._audit.get_stats()


# ── Helper ─────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Singleton ──────────────────────────────────────────────────────────────────

_manager: Optional[SandboxManager] = None
_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SandboxManager()
    return _manager
