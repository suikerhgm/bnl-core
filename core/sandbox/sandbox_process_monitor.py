"""
SandboxProcessMonitor — psutil-based runtime monitoring and threat detection engine.

Runs as a background daemon thread for each active sandbox.
Polls the target process every `interval_sec` seconds and:
  1. Records CPU/RAM/child-process snapshots
  2. Detects anomalous behavior patterns
  3. Accumulates risk_score and triggers auto-quarantine via callback

Detection patterns:
  CPU_SPIKE         — CPU > max_cpu_pct for > SPIKE_SUSTAINED_SEC seconds
  FORK_BOMB         — >N child processes spawned in T seconds
  INFINITE_LOOP     — CPU > 90% sustained for >LOOP_SUSTAINED_SEC seconds
  SUBPROCESS_ABUSE  — dangerous command patterns in child process cmdlines
  MEMORY_LEAK       — RAM growing >50% over 30 snapshot window
  PROCESS_ESCAPE    — child process working directory outside sandbox workspace

Suspicious subprocess command patterns (Windows + Linux):
  - powershell.exe -enc / -e (encoded commands)
  - cmd.exe /c
  - rm -rf, del /f /s /q
  - format, fdisk, mkfs
  - net user, net localgroup (privilege escalation)
  - curl/wget with -o pointing outside workspace
  - python -c / python3 -c with base64 content
"""

import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.sandbox.sandbox_audit_logger import SandboxAuditLogger, get_audit_logger
from core.sandbox.sandbox_network_guard import SandboxNetworkGuard, _collect_process_tree

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────

FORK_BOMB_WINDOW_SEC  = 5
FORK_BOMB_THRESHOLD   = 12     # >12 child procs in 5s
SPIKE_SUSTAINED_SEC   = 10     # sustained high CPU before firing alert
LOOP_SUSTAINED_SEC    = 30     # very long CPU spike = infinite loop
MEMORY_LEAK_WINDOW    = 30     # snapshot count to check RAM growth over
MEMORY_LEAK_THRESHOLD = 0.50   # 50% RAM growth ratio

# ── Dangerous subprocess patterns ─────────────────────────────────────────────

_DANGEROUS_CMDS = [
    re.compile(r"(?i)powershell.*(-enc|-e\s+[A-Za-z0-9+/]{20,})"),
    re.compile(r"(?i)cmd(?:\.exe)?.*\/c"),
    re.compile(r"(?i)rm\s+-rf?\s*[/\\]"),
    re.compile(r"(?i)del\s+/[fsq]"),
    re.compile(r"(?i)(format|mkfs|fdisk)\s"),
    re.compile(r"(?i)net\s+(user|localgroup|accounts)"),
    re.compile(r"(?i)reg\s+(add|delete|import)"),
    re.compile(r"(?i)(curl|wget).*-[oO]\s*[^\"' ]{1,}"),
    re.compile(r"(?i)python3?\s+-c.*(?:base64|exec|eval|__import__)"),
    re.compile(r"(?i)(attrib\s+[+-][rsh]|icacls.*\/grant|cacls)"),
    re.compile(r"(?i)(shutdown|taskkill)\s+/[fa]"),
    re.compile(r"(?i)(certutil|bitsadmin)\s+.*-decode"),
    re.compile(r"(?i)sc\s+(create|config|start|stop)"),
    re.compile(r"(?i)schtasks\s+(/create|/change)"),
]

_OBFUSCATION_PATTERNS = [
    re.compile(r"(?i)[A-Za-z0-9+/]{80,}={0,2}"),   # long base64
    re.compile(r"(?i)\\x[0-9a-fA-F]{2}(\\x[0-9a-fA-F]{2}){10,}"),  # hex-encoded
    re.compile(r"(?i)chr\(\d+\)(\+chr\(\d+\)){5,}"),  # chr() concat
]


class SandboxProcessMonitor:
    """
    Background monitoring thread for one sandbox execution.
    Attach to a PID, start the thread, and it will automatically:
      - record resource snapshots
      - fire violation callbacks
      - call quarantine_callback() when risk threshold is exceeded
    """

    def __init__(
        self,
        sandbox_id: str,
        workspace_path: str,
        max_cpu_pct: float = 80,
        max_ram_mb: float = 512,
        max_duration_sec: float = 120,
        auto_quarantine_score: int = 60,
        interval_sec: float = 1.0,
        quarantine_callback: Optional[Callable[[str, str], None]] = None,
        net_guard: Optional[SandboxNetworkGuard] = None,
        audit: Optional[SandboxAuditLogger] = None,
    ) -> None:
        self.sandbox_id            = sandbox_id
        self.workspace_path        = workspace_path
        self.max_cpu_pct           = max_cpu_pct
        self.max_ram_mb            = max_ram_mb
        self.max_duration_sec      = max_duration_sec
        self.auto_quarantine_score = auto_quarantine_score
        self.interval_sec          = interval_sec
        self._quarantine_cb        = quarantine_callback
        self._net_guard            = net_guard
        self._audit                = audit or get_audit_logger()

        self._pid: Optional[int]   = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event           = threading.Event()

        # State
        self.risk_score            = 0
        self._cpu_spike_start: Optional[float] = None
        self._ram_history: deque   = deque(maxlen=MEMORY_LEAK_WINDOW)
        self._child_spawn_times: deque = deque()
        self._seen_child_pids: set = set()
        self._start_time: Optional[float] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, pid: int) -> None:
        self._pid = pid
        self._start_time = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=f"sbx-monitor-{self.sandbox_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[SANDBOX] Monitor started for sandbox=%s pid=%d", self.sandbox_id, pid)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    # ── Monitor loop ───────────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                logger.debug("[SANDBOX] Monitor tick error for %s: %s", self.sandbox_id, exc)
            time.sleep(self.interval_sec)

    def _tick(self) -> None:
        if self._pid is None or not _PSUTIL:
            return

        # Duration guard
        elapsed = time.monotonic() - self._start_time
        if elapsed > self.max_duration_sec:
            self._fire_quarantine(
                f"Execution timeout: {elapsed:.0f}s > {self.max_duration_sec}s"
            )
            return

        try:
            proc = psutil.Process(self._pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                self._stop_event.set()
                return
        except psutil.NoSuchProcess:
            self._stop_event.set()
            return

        # Collect metrics
        tree = _collect_process_tree(self._pid)
        cpu   = self._get_tree_cpu(tree)
        ram   = self._get_tree_ram(tree)
        files = self._get_open_files(proc)
        conns = len(proc.connections(kind="inet")) if _PSUTIL else 0

        # Child process tracking
        child_pids = {p.pid for p in tree if p.pid != self._pid}
        new_children = child_pids - self._seen_child_pids
        self._seen_child_pids.update(new_children)

        # Record snapshot
        self._audit.record_snapshot(
            self.sandbox_id,
            cpu_percent=cpu,
            ram_mb=ram,
            open_files=files,
            child_processes=len(child_pids),
            net_connections=conns,
        )

        # Network inspection
        if self._net_guard:
            self._net_guard.inspect_process(self._pid)

        # Detections
        self._detect_cpu_spike(cpu)
        self._detect_fork_bomb(new_children, tree)
        self._detect_memory_leak(ram)
        self._detect_subprocess_abuse(new_children)
        self._detect_process_escape(tree)

        # RAM hard limit
        if ram > self.max_ram_mb:
            self._add_risk(20, "MEMORY_LIMIT_EXCEEDED",
                           f"RAM {ram:.0f}MB exceeds limit {self.max_ram_mb}MB",
                           risk_delta=20)

        # Auto-quarantine check
        db_row = self._audit.get_sandbox(self.sandbox_id)
        current_score = db_row.get("risk_score", 0) if db_row else self.risk_score
        if current_score >= self.auto_quarantine_score:
            self._fire_quarantine(
                f"Risk score {current_score} exceeded threshold {self.auto_quarantine_score}"
            )

    # ── Detection methods ──────────────────────────────────────────────────────

    def _detect_cpu_spike(self, cpu: float) -> None:
        now = time.monotonic()
        if cpu > self.max_cpu_pct:
            if self._cpu_spike_start is None:
                self._cpu_spike_start = now
            sustained = now - self._cpu_spike_start
            if sustained > LOOP_SUSTAINED_SEC:
                self._add_risk(30, "INFINITE_LOOP",
                               f"CPU {cpu:.0f}% sustained {sustained:.0f}s — possible infinite loop")
            elif sustained > SPIKE_SUSTAINED_SEC:
                self._add_risk(15, "CPU_SPIKE",
                               f"CPU {cpu:.0f}% sustained {sustained:.0f}s")
        else:
            self._cpu_spike_start = None

    def _detect_fork_bomb(self, new_children: set, tree: List) -> None:
        now = time.monotonic()
        for _ in new_children:
            self._child_spawn_times.append(now)
        while self._child_spawn_times and (now - self._child_spawn_times[0]) > FORK_BOMB_WINDOW_SEC:
            self._child_spawn_times.popleft()

        count = len(self._child_spawn_times)
        if count >= FORK_BOMB_THRESHOLD:
            self._add_risk(40, "FORK_BOMB",
                           f"Fork bomb detected: {count} processes spawned in {FORK_BOMB_WINDOW_SEC}s",
                           risk_delta=40)
            self._fire_quarantine(f"Fork bomb: {count} children in {FORK_BOMB_WINDOW_SEC}s")

    def _detect_memory_leak(self, ram_mb: float) -> None:
        self._ram_history.append(ram_mb)
        if len(self._ram_history) >= MEMORY_LEAK_WINDOW:
            first = self._ram_history[0]
            if first > 0:
                growth = (ram_mb - first) / first
                if growth > MEMORY_LEAK_THRESHOLD:
                    self._add_risk(15, "MEMORY_LEAK",
                                   f"RAM grew {growth*100:.0f}% over {MEMORY_LEAK_WINDOW} snapshots")

    def _detect_subprocess_abuse(self, new_pids: set) -> None:
        if not _PSUTIL or not new_pids:
            return
        for pid in new_pids:
            try:
                p = psutil.Process(pid)
                cmdline = " ".join(p.cmdline())
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

            for pat in _DANGEROUS_CMDS:
                if pat.search(cmdline):
                    self._add_risk(35, "SUBPROCESS_ABUSE",
                                   f"Dangerous command detected: {cmdline[:120]}",
                                   risk_delta=35)
                    break

            for pat in _OBFUSCATION_PATTERNS:
                if pat.search(cmdline):
                    self._add_risk(25, "OBFUSCATED_CODE",
                                   f"Obfuscated subprocess detected: {cmdline[:80]}",
                                   risk_delta=25)
                    break

    def _detect_process_escape(self, tree: List) -> None:
        if not _PSUTIL:
            return
        workspace = os.path.realpath(os.path.abspath(self.workspace_path))
        for proc in tree[1:]:  # skip root process
            try:
                cwd = proc.cwd()
                abs_cwd = os.path.realpath(os.path.abspath(cwd))
                if not abs_cwd.startswith(workspace):
                    self._add_risk(30, "PROCESS_ESCAPE",
                                   f"Child process cwd outside workspace: {cwd[:80]}",
                                   risk_delta=30)
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, NotADirectoryError):
                pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _add_risk(
        self,
        delta: int,
        violation_type: str,
        description: str,
        risk_delta: Optional[int] = None,
    ) -> None:
        self.risk_score = min(100, self.risk_score + delta)
        self._audit.record_violation(
            self.sandbox_id,
            violation_type,
            description,
            risk_delta=risk_delta or delta,
        )
        severity = "CRITICAL" if delta >= 30 else "WARNING"
        self._audit.log_event(
            self.sandbox_id,
            violation_type,
            description,
            severity=severity,
        )

    def _fire_quarantine(self, reason: str) -> None:
        self._stop_event.set()
        logger.critical("[SANDBOX] Auto-quarantine triggered: sandbox=%s reason=%s",
                        self.sandbox_id, reason)
        self._audit.log_event(
            self.sandbox_id,
            "AUTO_QUARANTINE",
            f"[SANDBOX_ESCAPE_ATT] Auto-quarantine: {reason}",
            severity="CRITICAL",
        )
        if self._quarantine_cb:
            try:
                self._quarantine_cb(self.sandbox_id, reason)
            except Exception as exc:
                logger.error("[SANDBOX] quarantine_callback error: %s", exc)

    @staticmethod
    def _get_tree_cpu(tree: List) -> float:
        total = 0.0
        for p in tree:
            try:
                total += p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total

    @staticmethod
    def _get_tree_ram(tree: List) -> float:
        total = 0.0
        for p in tree:
            try:
                total += p.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total

    @staticmethod
    def _get_open_files(proc) -> int:
        try:
            return len(proc.open_files())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0
