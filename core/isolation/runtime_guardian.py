"""
RuntimeGuardian — background monitoring daemon for all active isolation contexts.

Single daemon thread that polls every registered IsolationContext in a round-robin.
Uses variable poll intervals per isolation level (LOCKDOWN fastest, SOFT slowest).

Per-tick pipeline for each context:
    1. ResourceLimiter.snapshot()    → detect CPU/RAM/subprocess/net breaches
    2. FilesystemJail.inspect()      → detect workspace escapes and file pattern violations
    3. NetworkJail.inspect()         → detect forbidden connections
    4. Aggregate risk from all sources
    5. EmergencyKillSwitch.respond() if risk crosses the auto-respond threshold

Suspicious behavior detection:
    - Fork bomb            (ResourceLimiter: SUBPROCESS_LIMIT rapid growth)
    - Infinite loop        (ResourceLimiter: CPU_SUSTAINED_HIGH)
    - Runaway memory       (ResourceLimiter: MEMORY_EXCEEDED)
    - Subprocess abuse     (EmergencyKillSwitch via process cmdline scan)
    - Workspace escape     (FilesystemJail: WORKSPACE_ESCAPE)
    - Network abuse        (NetworkJail: HIGH_CONNECTION_RATE / SUSPICIOUS_PORT)
    - Privilege escalation (FilesystemJail: SENSITIVE_PATH_ACCESS)
    - Suspicious persistence (FilesystemJail: autorun / startup folder writes)

All events flow to IsolationManager for DB persistence.
"""

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.isolation.resource_limiter import IsolationLevel, ResourceLimiter
from core.isolation.filesystem_jail import FilesystemJail
from core.isolation.network_jail import NetworkJail
from core.isolation.emergency_kill_switch import EmergencyKillSwitch

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Suspicious subprocess cmdline patterns (same as SandboxProcessMonitor, unified here)
import re
_SUSPICIOUS_CMD = [
    re.compile(r"(?i)powershell.*(-enc|-e\s+[A-Za-z0-9+/]{20,})"),
    re.compile(r"(?i)cmd(?:\.exe)?.*\/c"),
    re.compile(r"(?i)rm\s+-rf?\s*/"),
    re.compile(r"(?i)del\s+/[fsq]"),
    re.compile(r"(?i)(format|mkfs|fdisk)\s"),
    re.compile(r"(?i)net\s+(user|localgroup|accounts)"),
    re.compile(r"(?i)reg\s+(add|delete|import)"),
    re.compile(r"(?i)(certutil|bitsadmin).*-decode"),
    re.compile(r"(?i)schtasks\s+/create"),
    re.compile(r"(?i)sc\s+(create|config)\s"),
]


class IsolationContext:
    """All state for one active isolation instance."""

    def __init__(
        self,
        process_id: str,
        pid: int,
        agent_id: Optional[str],
        level: IsolationLevel,
        workspace_root: str,
        limiter: ResourceLimiter,
        fs_jail: FilesystemJail,
        net_jail: NetworkJail,
        auto_respond_score: int = 50,
    ) -> None:
        self.process_id         = process_id
        self.pid                = pid
        self.agent_id           = agent_id
        self.level              = level
        self.workspace_root     = workspace_root
        self.limiter            = limiter
        self.fs_jail            = fs_jail
        self.net_jail           = net_jail
        self.auto_respond_score = auto_respond_score
        self.status             = "active"   # active | frozen | quarantined | terminated
        self.risk_score         = 0
        self.created_at         = _now()
        self._seen_child_pids: Set[int] = set()


class RuntimeGuardian:
    """
    Singleton background daemon. Owns the monitoring loop for all active contexts.
    Register contexts via register(); they are polled until unregistered or process dies.
    """

    _instance: Optional["RuntimeGuardian"] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> "RuntimeGuardian":
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
            self._contexts:  Dict[str, IsolationContext] = {}
            self._ctx_lock   = threading.Lock()
            self._stop_event = threading.Event()
            self._thread: Optional[threading.Thread] = None
            self._kill_switch: Optional[EmergencyKillSwitch] = None
            # Callback wired by IsolationManager
            self._on_violation: Optional[Callable[[str, str, str, int, Dict], None]] = None
            self._on_event:     Optional[Callable[[str, str, str, str], None]] = None
            self._lockdown_active = False
            self._initialized = True
            logger.info("[RUNTIME_GUARD] RuntimeGuardian initialized")

    # ── Configuration ──────────────────────────────────────────────────────────

    def configure(
        self,
        kill_switch: EmergencyKillSwitch,
        on_violation: Optional[Callable] = None,
        on_event: Optional[Callable] = None,
    ) -> None:
        self._kill_switch  = kill_switch
        self._on_violation = on_violation
        self._on_event     = on_event

    # ── Daemon lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._guardian_loop,
            name="nexus-runtime-guardian",
            daemon=True,
        )
        self._thread.start()
        logger.info("[RUNTIME_GUARD] Guardian daemon started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[RUNTIME_GUARD] Guardian daemon stopped")

    # ── Registration ───────────────────────────────────────────────────────────

    def register(self, ctx: IsolationContext) -> None:
        with self._ctx_lock:
            self._contexts[ctx.process_id] = ctx
        logger.info("[RUNTIME_GUARD] Registered process_id=%s pid=%d level=%s",
                    ctx.process_id, ctx.pid, ctx.level.value)

    def unregister(self, process_id: str) -> None:
        with self._ctx_lock:
            self._contexts.pop(process_id, None)
        logger.info("[RUNTIME_GUARD] Unregistered process_id=%s", process_id)

    def get_context(self, process_id: str) -> Optional[IsolationContext]:
        return self._contexts.get(process_id)

    def list_contexts(self) -> Dict[str, IsolationContext]:
        with self._ctx_lock:
            return dict(self._contexts)

    # ── Main loop ──────────────────────────────────────────────────────────────

    def _guardian_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._lockdown_active:
                time.sleep(0.5)
                continue

            with self._ctx_lock:
                contexts = list(self._contexts.values())

            for ctx in contexts:
                try:
                    self._tick(ctx)
                except Exception as exc:
                    logger.debug("[RUNTIME_GUARD] tick error for %s: %s", ctx.process_id, exc)

            # Sleep based on the fastest (most restrictive) active level
            interval = self._compute_interval(contexts)
            time.sleep(interval)

    def _tick(self, ctx: IsolationContext) -> None:
        if ctx.status in ("quarantined", "terminated"):
            return

        pid = ctx.pid
        if not _PSUTIL:
            return

        # Check process still alive
        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                ctx.status = "terminated"
                self.unregister(ctx.process_id)
                return
        except psutil.NoSuchProcess:
            ctx.status = "terminated"
            self.unregister(ctx.process_id)
            return

        # 1. Resource limits
        resource_breaches = ctx.limiter.snapshot()

        # 2. Filesystem inspection
        fs_violations = ctx.fs_jail.inspect(pid)

        # 3. Network inspection
        net_violations = ctx.net_jail.inspect(pid)

        # 4. Subprocess abuse scan
        cmd_violations = self._scan_subprocess_commands(ctx, pid)

        all_violations = resource_breaches + fs_violations + net_violations + cmd_violations

        # Accumulate risk
        delta = sum(v.get("risk_delta", 10) for v in all_violations)
        ctx.risk_score = min(100, ctx.risk_score + delta)

        # Persist violations
        for v in all_violations:
            self._emit_violation(ctx, v)

        # Snapshot to DB
        snap = ctx.limiter.get_latest()
        if snap and self._on_event:
            pass  # snapshots persisted by IsolationManager on each tick callback

        # Auto-respond
        if ctx.risk_score >= ctx.auto_respond_score and self._kill_switch:
            if ctx.status == "active":
                ctx.status = "responding"
                action = self._kill_switch.respond(
                    process_id=ctx.process_id,
                    pid=pid,
                    risk_score=ctx.risk_score,
                    agent_id=ctx.agent_id,
                    reason=f"risk_score={ctx.risk_score}",
                )
                ctx.status = "quarantined" if action in ("QUARANTINE", "LOCKDOWN") else "terminated"
                self._emit_event(ctx.process_id, action,
                                 f"Auto-response: {action} (risk={ctx.risk_score})", "CRITICAL")
                if action in ("QUARANTINE", "LOCKDOWN"):
                    self.unregister(ctx.process_id)

    # ── Subprocess command scan ────────────────────────────────────────────────

    def _scan_subprocess_commands(
        self, ctx: IsolationContext, pid: int
    ) -> list:
        violations = []
        if not _PSUTIL:
            return violations
        try:
            root = psutil.Process(pid)
            children = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return violations

        new_pids = {c.pid for c in children} - ctx._seen_child_pids
        ctx._seen_child_pids.update(new_pids)

        for pid_child in new_pids:
            try:
                p = psutil.Process(pid_child)
                cmdline = " ".join(p.cmdline())
                for pat in _SUSPICIOUS_CMD:
                    if pat.search(cmdline):
                        violations.append({
                            "type": "SUBPROCESS_ABUSE",
                            "description": f"Suspicious subprocess: {cmdline[:120]}",
                            "risk_delta": 35,
                            "kill": ctx.level in (IsolationLevel.HARD,
                                                   IsolationLevel.QUARANTINE,
                                                   IsolationLevel.LOCKDOWN),
                        })
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass

        return violations

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _emit_violation(self, ctx: IsolationContext, v: Dict) -> None:
        if self._on_violation:
            try:
                self._on_violation(
                    ctx.process_id,
                    v.get("type", "UNKNOWN"),
                    v.get("description", ""),
                    v.get("risk_delta", 10),
                    {k: val for k, val in v.items()
                     if k not in ("type", "description", "risk_delta")},
                )
            except Exception as exc:
                logger.debug("[RUNTIME_GUARD] _emit_violation error: %s", exc)

    def _emit_event(
        self,
        process_id: str,
        event_type: str,
        description: str,
        severity: str,
    ) -> None:
        if self._on_event:
            try:
                self._on_event(process_id, event_type, description, severity)
            except Exception as exc:
                logger.debug("[RUNTIME_GUARD] _emit_event error: %s", exc)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_interval(contexts: list) -> float:
        if not contexts:
            return 2.0
        fastest = min(
            ctx.limiter.limits.get("monitor_interval_sec", 1.0)
            for ctx in contexts
            if ctx.status == "active"
        ) if contexts else 1.0
        return max(0.25, fastest)

    def activate_lockdown(self) -> None:
        self._lockdown_active = True
        logger.critical("[RUNTIME_GUARD] LOCKDOWN ACTIVE — monitoring paused, all responses halted")

    def release_lockdown(self) -> None:
        self._lockdown_active = False
        logger.info("[RUNTIME_GUARD] Lockdown released")

    @property
    def active_count(self) -> int:
        return sum(1 for c in self._contexts.values() if c.status == "active")


# ── Singleton accessor ─────────────────────────────────────────────────────────

_guardian: Optional[RuntimeGuardian] = None
_guardian_lock = threading.Lock()


def get_guardian() -> RuntimeGuardian:
    global _guardian
    if _guardian is None:
        with _guardian_lock:
            if _guardian is None:
                _guardian = RuntimeGuardian()
    return _guardian


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
