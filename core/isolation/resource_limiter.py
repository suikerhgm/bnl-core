"""
ResourceLimiter — psutil-based runtime resource monitor for isolated processes.

Tracks per-process (and full process-tree) resource consumption against
configured thresholds, accumulates a risk score, and fires callbacks
when limits are breached.

Isolation levels and their default limits:
    SOFT        monitor only — no enforcement, no auto-response
    RESTRICTED  warn at 80% of limits, kill at 100%
    HARD        kill immediately at limit, no grace period
    QUARANTINE  kill + preserve + notify security
    LOCKDOWN    freeze system, emergency shutdown sequence

Metrics tracked:
    cpu_percent      — rolling average over a configurable window
    memory_mb        — RSS of the entire process tree
    subprocesses     — count of all descendants
    file_handles     — open file handles
    net_connections  — live TCP/UDP connections
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

logger = logging.getLogger(__name__)

# ── Isolation levels ───────────────────────────────────────────────────────────

class IsolationLevel(str, Enum):
    SOFT        = "SOFT"
    RESTRICTED  = "RESTRICTED"
    HARD        = "HARD"
    QUARANTINE  = "QUARANTINE"
    LOCKDOWN    = "LOCKDOWN"

    @classmethod
    def from_string(cls, s: str) -> "IsolationLevel":
        try:
            return cls(s.upper())
        except ValueError:
            return cls.RESTRICTED


# ── Default limit profiles ─────────────────────────────────────────────────────

LEVEL_LIMITS: Dict[IsolationLevel, Dict[str, Any]] = {
    IsolationLevel.SOFT: {
        "cpu_limit_percent":      95,
        "memory_limit_mb":       1024,
        "max_subprocesses":        50,
        "max_file_writes":        500,
        "max_net_connections":     50,
        "cpu_window_sec":          30,
        "cpu_kill_sustained_sec":  60,
        "auto_kill":             False,
        "auto_quarantine":       False,
        "monitor_interval_sec":    2.0,
    },
    IsolationLevel.RESTRICTED: {
        "cpu_limit_percent":      80,
        "memory_limit_mb":        512,
        "max_subprocesses":        16,
        "max_file_writes":        200,
        "max_net_connections":     20,
        "cpu_window_sec":          15,
        "cpu_kill_sustained_sec":  20,
        "auto_kill":             True,
        "auto_quarantine":       True,
        "monitor_interval_sec":    1.0,
    },
    IsolationLevel.HARD: {
        "cpu_limit_percent":      70,
        "memory_limit_mb":        256,
        "max_subprocesses":         8,
        "max_file_writes":        100,
        "max_net_connections":     10,
        "cpu_window_sec":           5,
        "cpu_kill_sustained_sec":   8,
        "auto_kill":             True,
        "auto_quarantine":       True,
        "monitor_interval_sec":    0.5,
    },
    IsolationLevel.QUARANTINE: {
        "cpu_limit_percent":      50,
        "memory_limit_mb":        128,
        "max_subprocesses":         4,
        "max_file_writes":         20,
        "max_net_connections":      2,
        "cpu_window_sec":           5,
        "cpu_kill_sustained_sec":   5,
        "auto_kill":             True,
        "auto_quarantine":       True,
        "monitor_interval_sec":    0.5,
    },
    IsolationLevel.LOCKDOWN: {
        "cpu_limit_percent":      10,
        "memory_limit_mb":         64,
        "max_subprocesses":         2,
        "max_file_writes":          5,
        "max_net_connections":      0,
        "cpu_window_sec":           3,
        "cpu_kill_sustained_sec":   3,
        "auto_kill":             True,
        "auto_quarantine":       True,
        "monitor_interval_sec":    0.25,
    },
}


# ── Snapshot dataclass ─────────────────────────────────────────────────────────

@dataclass
class ResourceSnapshot:
    cpu_percent:     float = 0.0
    memory_mb:       float = 0.0
    subprocesses:    int   = 0
    file_handles:    int   = 0
    net_connections: int   = 0
    timestamp:       float = field(default_factory=time.monotonic)


# ── Limiter ────────────────────────────────────────────────────────────────────

class ResourceLimiter:
    """
    Monitors one process tree against configured limits.
    Call snapshot() periodically; it returns a list of breach events.
    Does NOT run its own thread — thread control is in RuntimeGuardian.
    """

    def __init__(
        self,
        process_id: str,
        pid: int,
        level: IsolationLevel,
        limits: Optional[Dict[str, Any]] = None,
        on_breach: Optional[Callable[[str, str, Dict], None]] = None,
    ) -> None:
        self.process_id = process_id
        self.pid        = pid
        self.level      = level
        self.limits     = {**LEVEL_LIMITS[level], **(limits or {})}
        self.on_breach  = on_breach

        # Rolling CPU window
        self._cpu_samples:    deque = deque()
        self._cpu_high_start: Optional[float] = None

        # Counters
        self.total_file_writes  = 0
        self.peak_memory_mb     = 0.0
        self.risk_score         = 0

        # History for dashboard charts
        self.history: deque = deque(maxlen=120)

    def snapshot(self) -> List[Dict[str, Any]]:
        """
        Collect current metrics, check limits, return list of breach events.
        Each event: {"type": str, "metric": str, "value": float, "limit": float, "risk_delta": int}
        """
        if not _PSUTIL:
            return []

        metrics = self._collect(self.pid)
        self.history.append(metrics)

        breaches = []
        lim = self.limits
        now = time.monotonic()

        # CPU — rolling average
        self._cpu_samples.append((now, metrics.cpu_percent))
        window = lim["cpu_window_sec"]
        while self._cpu_samples and (now - self._cpu_samples[0][0]) > window:
            self._cpu_samples.popleft()
        avg_cpu = (
            sum(v for _, v in self._cpu_samples) / len(self._cpu_samples)
            if self._cpu_samples else 0
        )
        cpu_limit = lim["cpu_limit_percent"]

        if avg_cpu > cpu_limit:
            if self._cpu_high_start is None:
                self._cpu_high_start = now
            sustained = now - self._cpu_high_start
            kill_sec  = lim["cpu_kill_sustained_sec"]
            if sustained >= kill_sec:
                breaches.append(self._breach(
                    "CPU_SUSTAINED_HIGH", "cpu_percent", avg_cpu, cpu_limit, 25,
                    extra={"sustained_sec": round(sustained, 1)},
                ))
        else:
            self._cpu_high_start = None

        # Memory
        mem_limit = lim["memory_limit_mb"]
        if metrics.memory_mb > mem_limit:
            breaches.append(self._breach(
                "MEMORY_EXCEEDED", "memory_mb", metrics.memory_mb, mem_limit, 30,
            ))
        self.peak_memory_mb = max(self.peak_memory_mb, metrics.memory_mb)

        # Subprocesses
        proc_limit = lim["max_subprocesses"]
        if metrics.subprocesses > proc_limit:
            breaches.append(self._breach(
                "SUBPROCESS_LIMIT", "subprocesses", metrics.subprocesses, proc_limit, 20,
            ))

        # Network connections
        net_limit = lim["max_net_connections"]
        if metrics.net_connections > net_limit:
            breaches.append(self._breach(
                "NET_CONNECTION_LIMIT", "net_connections",
                metrics.net_connections, net_limit, 15,
            ))

        # Fire callbacks
        for breach in breaches:
            self.risk_score = min(100, self.risk_score + breach["risk_delta"])
            logger.warning(
                "[ISOLATION] [%s] breach=%s pid=%d val=%.1f limit=%.1f risk=%d",
                self.level.value, breach["type"], self.pid,
                breach["value"], breach["limit"], self.risk_score,
            )
            if self.on_breach:
                try:
                    self.on_breach(self.process_id, breach["type"], breach)
                except Exception as exc:
                    logger.error("[ISOLATION] on_breach callback error: %s", exc)

        return breaches

    def get_latest(self) -> Optional[ResourceSnapshot]:
        return self.history[-1] if self.history else None

    def get_history_dicts(self) -> List[Dict]:
        return [
            {
                "cpu_percent":     h.cpu_percent,
                "memory_mb":       h.memory_mb,
                "subprocesses":    h.subprocesses,
                "file_handles":    h.file_handles,
                "net_connections": h.net_connections,
                "timestamp":       h.timestamp,
            }
            for h in self.history
        ]

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _collect(pid: int) -> ResourceSnapshot:
        snap = ResourceSnapshot()
        if not _PSUTIL:
            return snap
        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return snap

        for p in tree:
            try:
                snap.cpu_percent  += p.cpu_percent(interval=None)
                snap.memory_mb    += p.memory_info().rss / (1024 * 1024)
                snap.file_handles += len(p.open_files())
                snap.net_connections += len(p.connections(kind="inet"))
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass

        snap.subprocesses = max(0, len(tree) - 1)
        return snap

    @staticmethod
    def _breach(
        btype: str,
        metric: str,
        value: float,
        limit: float,
        risk_delta: int,
        extra: Optional[Dict] = None,
    ) -> Dict:
        d = {
            "type":       btype,
            "metric":     metric,
            "value":      round(value, 2),
            "limit":      limit,
            "risk_delta": risk_delta,
        }
        if extra:
            d.update(extra)
        return d
