"""
SandboxNetworkGuard — network connection monitoring and restriction for sandbox environments.

Uses psutil to inspect active connections belonging to a monitored process tree.

Restriction modes:
  BLOCKED      — no network at all (FULL_QUARANTINE, RESTRICTED_EXECUTION, STATIC_ANALYSIS)
  LOCAL_ONLY   — localhost/127.0.0.1 and LAN only, no external internet
  MONITORED    — all network allowed but every connection is logged (OBSERVATION_MODE)

Detection patterns:
  EXTERNAL_CONNECTION   — outbound to public IP when not allowed
  HIDDEN_NETWORK_CALL   — connection detected with no matching permission grant
  SUSPICIOUS_PORT       — connections to well-known C2/exfil ports
  HIGH_CONN_RATE        — >20 new connections in 30s
"""

import logging
import re
import socket
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.sandbox.sandbox_audit_logger import SandboxAuditLogger, get_audit_logger

logger = logging.getLogger(__name__)

# Suspicious port list (C2, exfil, common malware ports)
_SUSPICIOUS_PORTS: Set[int] = {
    4444, 4445, 4446,            # Metasploit default
    31337, 1337,                 # classic backdoor ports
    6667, 6668, 6669,            # IRC (often used by botnets)
    8080, 8443, 9090,            # alt HTTP — flag for untrusted code
    1080,                        # SOCKS proxy
    3128,                        # Squid proxy
}

_HIGH_CONN_WINDOW    = 30   # seconds
_HIGH_CONN_THRESHOLD = 20   # connections


def _is_local_address(ip: str) -> bool:
    """Return True if the IP is localhost or private/link-local."""
    if not ip:
        return True
    try:
        addr = socket.inet_aton(ip)
    except OSError:
        return False
    # 127.x.x.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x
    private_prefixes = (
        b"\x7f",          # 127.0.0.0/8  localhost
        b"\x0a",          # 10.0.0.0/8
        b"\xac\x10",      # 172.16.0.0/12
        b"\xac\x11",
        b"\xac\x1f",
        b"\xc0\xa8",      # 192.168.0.0/16
        b"\xa9\xfe",      # 169.254.0.0/16
        b"\x00\x00\x00\x00",  # 0.0.0.0
    )
    for prefix in private_prefixes:
        if addr[:len(prefix)] == prefix:
            return True
    return False


class SandboxNetworkGuard:
    """Per-sandbox network monitor. Inspects the process's live connections via psutil."""

    def __init__(
        self,
        sandbox_id: str,
        allow_network: bool = False,
        local_only: bool = True,
        audit: Optional[SandboxAuditLogger] = None,
    ) -> None:
        self.sandbox_id    = sandbox_id
        self.allow_network = allow_network
        self.local_only    = local_only
        self._audit        = audit or get_audit_logger()

        self._seen_connections: Set[Tuple] = set()
        self._conn_times: deque = deque()
        self.total_connections = 0
        self.blocked_connections = 0

    # ── Snapshot inspection ────────────────────────────────────────────────────

    def inspect_process(self, pid: int) -> List[Dict[str, Any]]:
        """
        Inspect all network connections for a PID and its children.
        Returns list of violation dicts for any suspicious connections.
        Logs every new connection detected.
        """
        if not _PSUTIL or pid is None:
            return []

        violations: List[Dict[str, Any]] = []

        try:
            procs = _collect_process_tree(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

        now = time.monotonic()
        new_conns = 0

        for proc in procs:
            try:
                conns = proc.connections(kind="inet")
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

            for conn in conns:
                raddr = conn.raddr
                if not raddr:
                    continue

                key = (raddr.ip, raddr.port, conn.status)
                if key in self._seen_connections:
                    continue

                self._seen_connections.add(key)
                self._conn_times.append(now)
                self.total_connections += 1
                new_conns += 1

                # Trim sliding window
                while self._conn_times and (now - self._conn_times[0]) > _HIGH_CONN_WINDOW:
                    self._conn_times.popleft()

                viol = self._evaluate_connection(raddr.ip, raddr.port, conn.status)
                if viol:
                    violations.append(viol)

        # High connection rate check
        if len(self._conn_times) >= _HIGH_CONN_THRESHOLD:
            self._audit.record_violation(
                self.sandbox_id,
                "HIGH_CONN_RATE",
                f"High connection rate: {len(self._conn_times)} conns in {_HIGH_CONN_WINDOW}s",
                risk_delta=20,
                details={"count": len(self._conn_times)},
            )

        return violations

    def _evaluate_connection(
        self, ip: str, port: int, status: str
    ) -> Optional[Dict[str, Any]]:
        is_local = _is_local_address(ip)

        # No network allowed at all
        if not self.allow_network:
            self.blocked_connections += 1
            risk = 25
            vtype = "HIDDEN_NETWORK_CALL"
            desc  = f"Network call detected in no-network mode: {ip}:{port}"
            self._audit.record_violation(
                self.sandbox_id, vtype, desc, risk_delta=risk,
                details={"ip": ip, "port": port, "status": status},
            )
            self._audit.log_event(
                self.sandbox_id, vtype, desc, severity="CRITICAL",
            )
            return {"type": vtype, "ip": ip, "port": port}

        # Local-only restriction
        if self.local_only and not is_local:
            self.blocked_connections += 1
            vtype = "EXTERNAL_CONNECTION"
            desc  = f"External network blocked: {ip}:{port}"
            self._audit.record_violation(
                self.sandbox_id, vtype, desc, risk_delta=20,
                details={"ip": ip, "port": port},
            )
            return {"type": vtype, "ip": ip, "port": port}

        # Suspicious port (even if network is allowed)
        if port in _SUSPICIOUS_PORTS:
            vtype = "SUSPICIOUS_PORT"
            desc  = f"Connection to suspicious port: {ip}:{port}"
            self._audit.record_violation(
                self.sandbox_id, vtype, desc, risk_delta=30,
                details={"ip": ip, "port": port},
            )
            self._audit.log_event(
                self.sandbox_id, vtype, desc, severity="WARNING",
            )
            return {"type": vtype, "ip": ip, "port": port}

        # Allowed — log in observation mode
        self._audit.log_event(
            self.sandbox_id,
            "NETWORK_CONNECTION",
            f"Connection: {ip}:{port} [{status}]",
            severity="INFO",
        )
        return None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_connections":   self.total_connections,
            "blocked_connections": self.blocked_connections,
            "seen_unique":         len(self._seen_connections),
            "allow_network":       self.allow_network,
            "local_only":          self.local_only,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _collect_process_tree(pid: int) -> List[Any]:
    """Collect a process and all its descendants."""
    try:
        root = psutil.Process(pid)
        children = root.children(recursive=True)
        return [root] + list(children)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []
