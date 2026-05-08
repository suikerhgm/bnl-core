"""
isolation_driver.py — Core Types + IsolationDriver Protocol
Task 1 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: ONLY stdlib imports. Zero project imports.
"""
from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# 1. IsolationTier
# ---------------------------------------------------------------------------

class IsolationTier(IntEnum):
    FIRECRACKER = 1
    QEMU = 2
    DOCKER_HARDENED = 3
    SANDBOX = 4
    PROCESS_JAIL = 5


# ---------------------------------------------------------------------------
# 2. RuntimeLifecycleState
# ---------------------------------------------------------------------------

class RuntimeLifecycleState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    QUARANTINED = "quarantined"
    SNAPSHOTTED = "snapshotted"
    FROZEN = "frozen"
    DESTROYED = "destroyed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 3. DriverCapabilities (frozen dataclass)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriverCapabilities:
    tier: IsolationTier
    supports_snapshots: bool
    supports_memory_snapshots: bool
    supports_hot_snapshot: bool
    supports_incremental_snapshots: bool
    supports_behavioral_lab: bool
    supports_network_isolation: bool
    supports_filesystem_isolation: bool
    supports_forensics: bool
    supports_live_forensics: bool
    supports_nested_isolation: bool
    supports_readonly_rootfs: bool
    supports_secure_boot: bool
    supports_tpm_emulation: bool
    supports_virtualized_gpu: bool
    supports_gpu_isolation: bool
    supports_network_deception: bool
    supports_runtime_migration: bool
    supports_attestation: bool
    supports_remote_nodes: bool
    supports_remote_execution: bool
    max_concurrent_runtimes: int  # 0 = unlimited


# ---------------------------------------------------------------------------
# 4. Module-level handle state registry
# ---------------------------------------------------------------------------

_handle_state_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()


def _set_handle_state(runtime_id: str, key: str, value: object) -> None:
    """Store driver-internal state for a runtime handle."""
    with _registry_lock:
        if runtime_id not in _handle_state_registry:
            _handle_state_registry[runtime_id] = {}
        _handle_state_registry[runtime_id][key] = value


def _get_handle_state(runtime_id: str, key: str, default=None) -> object:
    """Retrieve driver-internal state for a runtime handle."""
    with _registry_lock:
        return _handle_state_registry.get(runtime_id, {}).get(key, default)


def _clear_handle_state(runtime_id: str) -> None:
    """Remove all stored state for a runtime handle."""
    with _registry_lock:
        _handle_state_registry.pop(runtime_id, None)


# ---------------------------------------------------------------------------
# 5. RuntimeHandle (frozen, hashed by runtime_id only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuntimeHandle:
    runtime_id: str
    runtime_type: str
    tier: IsolationTier
    created_at: datetime
    state: RuntimeLifecycleState = RuntimeLifecycleState.CREATED

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuntimeHandle):
            return NotImplemented
        return self.runtime_id == other.runtime_id

    def __hash__(self) -> int:
        return hash(self.runtime_id)


# ---------------------------------------------------------------------------
# 6. ExecutionPayload
# ---------------------------------------------------------------------------

@dataclass
class ExecutionPayload:
    code: str | None = None
    command: str | None = None
    timeout_seconds: int = 30
    environment: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 7. ExecutionContext
# ---------------------------------------------------------------------------

@dataclass
class ExecutionContext:
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    trace_id: str | None = None
    preserve_forensics: bool = False


# ---------------------------------------------------------------------------
# 8. ExecutionResult
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: str | None
    exit_code: int
    runtime_id: str
    tier_used: IsolationTier
    duration_ms: int
    negotiation: Any = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    trace_id: str | None = None
    runtime_state: RuntimeLifecycleState = RuntimeLifecycleState.DESTROYED
    health_stats: Any = None


# ---------------------------------------------------------------------------
# 9. SnapshotRef (frozen, forensic chain support)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotRef:
    available: bool
    snapshot_id: str | None = None
    reason: str | None = None
    integrity_hash: str | None = None
    snapshot_chain_parent: str | None = None
    snapshot_reason: str | None = None  # MANUAL / QUARANTINE / EMERGENCY / SCHEDULED


# ---------------------------------------------------------------------------
# 10. RuntimeConfig
# ---------------------------------------------------------------------------

@dataclass
class RuntimeConfig:
    agent_id: str
    profile: str = "safe"
    max_cpu_percent: float = 50.0
    max_ram_mb: int = 512
    max_runtime_seconds: int = 60
    network_isolated: bool = True


# ---------------------------------------------------------------------------
# 11. RuntimeHealthStats
# ---------------------------------------------------------------------------

@dataclass
class RuntimeHealthStats:
    runtime_id: str
    health_score: float = 100.0
    stability_score: float = 100.0
    anomaly_score: float = 0.0
    failure_rate: float = 0.0
    updated_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 12. Security scores and risk adjustments
# ---------------------------------------------------------------------------

TIER_SECURITY_SCORES: dict[IsolationTier, int] = {
    IsolationTier.FIRECRACKER: 95,
    IsolationTier.QEMU: 87,
    IsolationTier.DOCKER_HARDENED: 70,
    IsolationTier.SANDBOX: 40,
    IsolationTier.PROCESS_JAIL: 20,
}

TIER_RISK_ADJUSTMENTS: dict[IsolationTier, int] = {
    IsolationTier.FIRECRACKER: 0,
    IsolationTier.QEMU: -5,       # higher device emulation attack surface
    IsolationTier.DOCKER_HARDENED: 0,
    IsolationTier.SANDBOX: 0,
    IsolationTier.PROCESS_JAIL: 0,
}


# ---------------------------------------------------------------------------
# 13. TIER_CAPABILITIES
# ---------------------------------------------------------------------------
# Column order matches spec table:
# snap | mem_snap | hot_snap | incr_snap | behav_lab | net_iso | fs_iso |
# forensics | live_forensics | nested | ro_rootfs | secure_boot | tpm |
# vgpu | gpu_iso | net_dec | runtime_mig | attest | remote_nodes |
# remote_exec | max_concurrent

TIER_CAPABILITIES: dict[IsolationTier, DriverCapabilities] = {
    IsolationTier.FIRECRACKER: DriverCapabilities(
        tier=IsolationTier.FIRECRACKER,
        supports_snapshots=True,
        supports_memory_snapshots=True,
        supports_hot_snapshot=True,
        supports_incremental_snapshots=True,
        supports_behavioral_lab=True,
        supports_network_isolation=True,
        supports_filesystem_isolation=True,
        supports_forensics=True,
        supports_live_forensics=True,
        supports_nested_isolation=True,
        supports_readonly_rootfs=True,
        supports_secure_boot=True,
        supports_tpm_emulation=True,
        supports_virtualized_gpu=False,
        supports_gpu_isolation=False,
        supports_network_deception=True,
        supports_runtime_migration=True,
        supports_attestation=True,
        supports_remote_nodes=True,
        supports_remote_execution=True,
        max_concurrent_runtimes=50,
    ),
    IsolationTier.QEMU: DriverCapabilities(
        tier=IsolationTier.QEMU,
        supports_snapshots=True,
        supports_memory_snapshots=True,
        supports_hot_snapshot=False,
        supports_incremental_snapshots=True,
        supports_behavioral_lab=True,
        supports_network_isolation=True,
        supports_filesystem_isolation=True,
        supports_forensics=True,
        supports_live_forensics=True,
        supports_nested_isolation=False,
        supports_readonly_rootfs=True,
        supports_secure_boot=True,
        supports_tpm_emulation=True,
        supports_virtualized_gpu=True,
        supports_gpu_isolation=False,
        supports_network_deception=True,
        supports_runtime_migration=False,
        supports_attestation=False,
        supports_remote_nodes=False,
        supports_remote_execution=False,
        max_concurrent_runtimes=10,
    ),
    IsolationTier.DOCKER_HARDENED: DriverCapabilities(
        tier=IsolationTier.DOCKER_HARDENED,
        supports_snapshots=True,
        supports_memory_snapshots=False,
        supports_hot_snapshot=False,
        supports_incremental_snapshots=False,
        supports_behavioral_lab=True,
        supports_network_isolation=True,
        supports_filesystem_isolation=True,
        supports_forensics=True,
        supports_live_forensics=False,
        supports_nested_isolation=False,
        supports_readonly_rootfs=True,
        supports_secure_boot=False,
        supports_tpm_emulation=False,
        supports_virtualized_gpu=False,
        supports_gpu_isolation=False,
        supports_network_deception=False,
        supports_runtime_migration=False,
        supports_attestation=False,
        supports_remote_nodes=False,
        supports_remote_execution=False,
        max_concurrent_runtimes=20,
    ),
    IsolationTier.SANDBOX: DriverCapabilities(
        tier=IsolationTier.SANDBOX,
        supports_snapshots=False,
        supports_memory_snapshots=False,
        supports_hot_snapshot=False,
        supports_incremental_snapshots=False,
        supports_behavioral_lab=False,
        supports_network_isolation=True,
        supports_filesystem_isolation=True,
        supports_forensics=False,
        supports_live_forensics=False,
        supports_nested_isolation=False,
        supports_readonly_rootfs=False,
        supports_secure_boot=False,
        supports_tpm_emulation=False,
        supports_virtualized_gpu=False,
        supports_gpu_isolation=False,
        supports_network_deception=False,
        supports_runtime_migration=False,
        supports_attestation=False,
        supports_remote_nodes=False,
        supports_remote_execution=False,
        max_concurrent_runtimes=0,
    ),
    IsolationTier.PROCESS_JAIL: DriverCapabilities(
        tier=IsolationTier.PROCESS_JAIL,
        supports_snapshots=False,
        supports_memory_snapshots=False,
        supports_hot_snapshot=False,
        supports_incremental_snapshots=False,
        supports_behavioral_lab=False,
        supports_network_isolation=False,
        supports_filesystem_isolation=True,
        supports_forensics=False,
        supports_live_forensics=False,
        supports_nested_isolation=False,
        supports_readonly_rootfs=False,
        supports_secure_boot=False,
        supports_tpm_emulation=False,
        supports_virtualized_gpu=False,
        supports_gpu_isolation=False,
        supports_network_deception=False,
        supports_runtime_migration=False,
        supports_attestation=False,
        supports_remote_nodes=False,
        supports_remote_execution=False,
        max_concurrent_runtimes=0,
    ),
}


# ---------------------------------------------------------------------------
# 14. IsolationDriver (ABC)
# ---------------------------------------------------------------------------

class IsolationDriver(ABC):
    """Abstract base class that every isolation backend must implement."""

    @property
    @abstractmethod
    def tier(self) -> IsolationTier:
        """The isolation tier this driver operates at."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilities:
        """Capabilities advertised by this driver."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the driver's backend is reachable and operational."""
        ...

    @abstractmethod
    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        """Provision a new isolated runtime and return its handle."""
        ...

    @abstractmethod
    async def execute(
        self,
        handle: RuntimeHandle,
        payload: ExecutionPayload,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionResult:
        """Execute a payload inside the runtime referenced by handle."""
        ...

    @abstractmethod
    async def destroy(self, handle: RuntimeHandle) -> None:
        """Tear down the runtime and release all resources."""
        ...

    @abstractmethod
    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        """Take a snapshot of the runtime. Returns SnapshotRef indicating result."""
        ...

    @abstractmethod
    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        """Move the runtime into quarantine, blocking further execution."""
        ...
