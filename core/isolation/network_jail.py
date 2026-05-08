"""
NetworkJail — connection monitoring and blocking policy for isolated processes.

Policy per isolation level:
    SOFT        — monitor all, log only
    RESTRICTED  — block external (non-LAN) IPs, warn on suspicious ports
    HARD        — localhost only, trigger violation on any external attempt
    QUARANTINE  — no network at all, immediate kill on any connection
    LOCKDOWN    — no network, immediate system-wide alert

Tracking:
    - All new connections detected via psutil.Process.connections()
    - Sliding window for high-rate detection
    - Known C2/suspicious port flagging
    - External IP detection

Note: NetworkJail cannot actually block connections (no kernel hooks in pure Python).
It detects and reports violations, which the RuntimeGuardian acts on.
"""

import logging
import socket
import time
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core.isolation.resource_limiter import IsolationLevel

logger = logging.getLogger(__name__)

_SUSPICIOUS_PORTS: Set[int] = {
    4444, 4445, 1337, 31337,           # reverse shells
    6667, 6668, 6669,                   # IRC / botnets
    9001, 9030,                         # Tor
    1080,                               # SOCKS
    8080, 8443,                         # alt HTTP
    3128,                               # Squid
    23,                                 # Telnet
    513, 514,                           # rsh/rlogin/syslog
}

_HIGH_CONN_WINDOW     = 30
_HIGH_CONN_THRESHOLD  = 15

LEVEL_POLICY: Dict[IsolationLevel, Dict] = {
    IsolationLevel.SOFT:       {"allow_external": True,  "allow_local": True,  "allow_none": False, "kill_on_detect": False},
    IsolationLevel.RESTRICTED: {"allow_external": False, "allow_local": True,  "allow_none": False, "kill_on_detect": False},
    IsolationLevel.HARD:       {"allow_external": False, "allow_local": True,  "allow_none": False, "kill_on_detect": True},
    IsolationLevel.QUARANTINE: {"allow_external": False, "allow_local": False, "allow_none": True,  "kill_on_detect": True},
    IsolationLevel.LOCKDOWN:   {"allow_external": False, "allow_local": False, "allow_none": True,  "kill_on_detect": True},
}


def _is_local(ip: str) -> bool:
    if not ip:
        return True
    local_prefixes = ("127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.",
                      "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                      "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                      "172.29.", "172.30.", "172.31.", "169.254.", "::1", "0.0.0.0")
    return any(ip.startswith(p) for p in local_prefixes)


class NetworkJail:
    """
    Per-isolation network watcher. Call inspect(pid) on each monitor tick.
    """

    def __init__(
        self,
        process_id: str,
        level: IsolationLevel,
    ) -> None:
        self.process_id = process_id
        self.level      = level
        self.policy     = LEVEL_POLICY[level]

        self._seen:      Set[Tuple] = set()
        self._conn_times: deque    = deque()

        self.total_connections   = 0
        self.blocked_connections = 0
        self.suspicious_count    = 0

    def inspect(self, pid: int) -> List[Dict]:
        """
        Inspect all connections for pid and its tree.
        Returns list of violations.
        """
        if not _PSUTIL:
            return []

        violations = []
        now = time.monotonic()

        try:
            root = psutil.Process(pid)
            tree = [root] + root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

        for proc in tree:
            try:
                conns = proc.connections(kind="inet")
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

            for conn in conns:
                if not conn.raddr:
                    continue
                key = (conn.raddr.ip, conn.raddr.port, conn.status)
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.total_connections += 1
                self._conn_times.append(now)

                while self._conn_times and (now - self._conn_times[0]) > _HIGH_CONN_WINDOW:
                    self._conn_times.popleft()

                v = self._evaluate(conn.raddr.ip, conn.raddr.port)
                if v:
                    violations.append(v)

        # High connection rate
        if len(self._conn_times) >= _HIGH_CONN_THRESHOLD:
            violations.append({
                "type": "HIGH_CONNECTION_RATE",
                "description": f"{len(self._conn_times)} connections in {_HIGH_CONN_WINDOW}s",
                "risk_delta": 20,
                "kill": self.policy["kill_on_detect"],
            })

        return violations

    def _evaluate(self, ip: str, port: int) -> Optional[Dict]:
        is_local  = _is_local(ip)
        policy    = self.policy

        # No network allowed at all
        if policy["allow_none"]:
            self.blocked_connections += 1
            return {
                "type": "NETWORK_BLOCKED",
                "description": f"Connection detected in no-network mode: {ip}:{port}",
                "risk_delta": 35,
                "kill": True,
            }

        # External blocked
        if not is_local and not policy["allow_external"]:
            self.blocked_connections += 1
            vtype = "EXTERNAL_CONNECTION_BLOCKED"
            return {
                "type": vtype,
                "description": f"External connection blocked: {ip}:{port}",
                "risk_delta": 20,
                "kill": policy["kill_on_detect"],
            }

        # Suspicious port
        if port in _SUSPICIOUS_PORTS:
            self.suspicious_count += 1
            return {
                "type": "SUSPICIOUS_PORT",
                "description": f"Connection to suspicious port {ip}:{port}",
                "risk_delta": 30,
                "kill": policy["kill_on_detect"],
            }

        logger.debug("[ISOLATION] [NET] %s:%d allowed (%s)", ip, port, self.level.value)
        return None

    def get_stats(self) -> Dict:
        return {
            "total_connections":   self.total_connections,
            "blocked_connections": self.blocked_connections,
            "suspicious_count":    self.suspicious_count,
            "policy":              self.policy,
            "level":               self.level.value,
        }
