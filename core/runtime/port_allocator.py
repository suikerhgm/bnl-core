"""
core/runtime/port_allocator.py
================================
Finds the next free TCP port for a generated project.

Strategy:
  1. Skip ports already claimed by ProcessManager (avoids in-memory double-booking).
  2. Attempt a real socket bind to confirm the OS reports it free.
  3. Return the first port that passes both checks.
"""
import socket
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_PORT_START = 8002
_PORT_END   = 8200


def find_free_port() -> Optional[int]:
    """Return the next available port in [_PORT_START, _PORT_END), or None."""
    # Import here to avoid circular dependency at module load time
    from core.runtime.process_manager import get_manager

    manager = get_manager()
    used_by_pm: set[int] = {
        int(p["port"])
        for p in manager.list_all()
        if p.get("port") and str(p["port"]).isdigit()
    }

    for port in range(_PORT_START, _PORT_END):
        if port in used_by_pm:
            logger.debug("🔌 PortAllocator: port %d already claimed by ProcessManager", port)
            continue
        if _is_port_free(port):
            logger.info("🔌 PortAllocator: allocated port %d", port)
            return port

    logger.warning(
        "⚠️ PortAllocator: no free port found in range %d–%d",
        _PORT_START, _PORT_END,
    )
    return None


def _is_port_free(port: int) -> bool:
    """True if the OS reports the port as bindable on 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False
