from __future__ import annotations
import threading
from typing import Optional


class VMManager:
    """Internal orchestrator for VM-tier runtimes. Not itself an IsolationDriver."""
    pass


_instance: Optional[VMManager] = None
_lock = threading.Lock()


def get_vm_manager() -> VMManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = VMManager()
    return _instance
