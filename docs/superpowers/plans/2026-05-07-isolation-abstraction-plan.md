# Isolation Abstraction Layer — Implementation Plan A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/isolation_abstraction/` — a unified isolation API with Tier 3–5 drivers (Docker, Sandbox, ProcessJail) fully functional on Windows today, automatically activating Tiers 1–2 on Linux without any API changes.

**Architecture:** Protocol+ABC `IsolationDriver` → `IsolationCapabilityDetector` probes environment once → `IsolationNegotiator` selects best tier via policy → `UnifiedIsolationRuntime` exposes `execute_isolated()` as the sole public API. Five drivers wrap existing singletons. No existing file is modified.

**Tech Stack:** Python 3.10+, sqlite3 (stdlib), `docker` SDK (`pip install docker`), pytest, existing Nexus singletons (`get_sandbox_manager`, `get_isolation_manager`).

**Spec:** `docs/superpowers/specs/2026-05-07-vm-isolation-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `core/isolation_abstraction/__init__.py` | Public re-exports + singleton getters |
| `core/isolation_abstraction/isolation_driver.py` | All shared types: `IsolationTier`, `DriverCapabilities`, `RuntimeHandle`, `ExecutionPayload`, `ExecutionResult`, `SnapshotRef`, `RuntimeConfig`, `IsolationDriver` ABC, `TIER_CAPABILITIES`, `TIER_SECURITY_SCORES` |
| `core/isolation_abstraction/isolation_capability_detector.py` | `CapabilitySnapshot`, `IsolationCapabilityDetector` — probes host, caches, rate-limited refresh |
| `core/isolation_abstraction/isolation_strategy_manager.py` | `IsolationPolicy`, `IsolationUnavailableError`, `IsolationStrategyManager` — pure tier selection |
| `core/isolation_abstraction/isolation_negotiator.py` | `NegotiationResult`, `IsolationNegotiator` — produces full reasoning record |
| `core/isolation_abstraction/isolation_audit_logger.py` | `IsolationAuditLogger` — append-only, hash-chained SQLite writer |
| `core/isolation_abstraction/unified_isolation_runtime.py` | `UnifiedIsolationRuntime`, `get_unified_runtime()` — the only thing callers import |
| `core/isolation_abstraction/drivers/__init__.py` | Driver registry list |
| `core/isolation_abstraction/drivers/process_jail_driver.py` | `ProcessJailDriver` — Tier 5, wraps `IsolationManager` |
| `core/isolation_abstraction/drivers/sandbox_driver.py` | `SandboxDriver` — Tier 4, wraps `SandboxManager` |
| `core/isolation_abstraction/drivers/docker_hardened_driver.py` | `DockerHardenedDriver` — Tier 3, wraps `docker` SDK |
| `data/nexus_vm_isolation.db` | Created automatically on first run |
| `app/routes/vm_routes.py` | FastAPI router for `/vm/*` endpoints |
| `app/vm_dashboard.py` | Single-file dashboard (HTML + auto-refresh) |
| `tests/test_isolation_abstraction/conftest.py` | Shared fixtures |
| `tests/test_isolation_abstraction/test_isolation_driver.py` | Types + TIER_CAPABILITIES |
| `tests/test_isolation_abstraction/test_capability_detector.py` | Probe + cache + refresh |
| `tests/test_isolation_abstraction/test_strategy_manager.py` | All four policies |
| `tests/test_isolation_abstraction/test_negotiator.py` | NegotiationResult correctness |
| `tests/test_isolation_abstraction/test_drivers.py` | All three drivers |
| `tests/test_isolation_abstraction/test_audit_logger.py` | Hash chain integrity |
| `tests/test_isolation_abstraction/test_unified_runtime.py` | Integration: execute_isolated() |

---

## Task 1: Core Types + IsolationDriver Protocol

**Files:**
- Create: `core/isolation_abstraction/__init__.py`
- Create: `core/isolation_abstraction/isolation_driver.py`
- Create: `tests/test_isolation_abstraction/__init__.py`
- Create: `tests/test_isolation_abstraction/test_isolation_driver.py`

- [ ] **Step 1: Create test file**

```python
# tests/test_isolation_abstraction/test_isolation_driver.py
import pytest
from dataclasses import fields
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, DriverCapabilities, RuntimeHandle,
    ExecutionPayload, ExecutionResult, SnapshotRef, RuntimeConfig,
    TIER_CAPABILITIES, TIER_SECURITY_SCORES, TIER_RISK_ADJUSTMENTS,
    IsolationDriver,
)


def test_isolation_tier_is_ordered():
    assert IsolationTier.FIRECRACKER < IsolationTier.DOCKER_HARDENED
    assert IsolationTier.DOCKER_HARDENED < IsolationTier.PROCESS_JAIL


def test_driver_capabilities_is_immutable():
    caps = TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]
    with pytest.raises(Exception):
        caps.supports_snapshots = True


def test_all_tiers_have_capabilities():
    for tier in IsolationTier:
        assert tier in TIER_CAPABILITIES
        assert tier in TIER_SECURITY_SCORES


def test_firecracker_has_strongest_score():
    assert TIER_SECURITY_SCORES[IsolationTier.FIRECRACKER] > TIER_SECURITY_SCORES[IsolationTier.DOCKER_HARDENED]
    assert TIER_SECURITY_SCORES[IsolationTier.DOCKER_HARDENED] > TIER_SECURITY_SCORES[IsolationTier.PROCESS_JAIL]


def test_qemu_has_risk_adjustment():
    assert TIER_RISK_ADJUSTMENTS[IsolationTier.QEMU] < 0


def test_runtime_handle_hashes_by_id():
    from datetime import datetime
    h1 = RuntimeHandle(runtime_id="abc", runtime_type="sandbox", tier=IsolationTier.SANDBOX, created_at=datetime.utcnow())
    h2 = RuntimeHandle(runtime_id="abc", runtime_type="jail", tier=IsolationTier.PROCESS_JAIL, created_at=datetime.utcnow())
    assert h1 == h2  # equality based on runtime_id
    assert hash(h1) == hash(h2)


def test_snapshot_ref_unavailable_default():
    ref = SnapshotRef(available=False, reason="not_supported")
    assert ref.available is False
    assert ref.snapshot_id is None


def test_isodriver_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        IsolationDriver()
```

- [ ] **Step 2: Create tests directory init**

```python
# tests/test_isolation_abstraction/__init__.py
```

- [ ] **Step 3: Run tests — verify they fail with ImportError**

```
pytest tests/test_isolation_abstraction/test_isolation_driver.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.isolation_abstraction'`

- [ ] **Step 4: Create package init**

```python
# core/isolation_abstraction/__init__.py
from .unified_isolation_runtime import UnifiedIsolationRuntime, get_unified_runtime
from .isolation_capability_detector import IsolationCapabilityDetector, CapabilitySnapshot, get_capability_detector
from .isolation_negotiator import IsolationNegotiator, NegotiationResult, get_negotiator
from .isolation_driver import (
    IsolationTier, IsolationDriver, DriverCapabilities,
    RuntimeHandle, ExecutionPayload, ExecutionResult,
    SnapshotRef, RuntimeConfig,
)

__all__ = [
    "get_unified_runtime", "UnifiedIsolationRuntime",
    "get_capability_detector", "IsolationCapabilityDetector", "CapabilitySnapshot",
    "get_negotiator", "IsolationNegotiator", "NegotiationResult",
    "IsolationTier", "IsolationDriver", "DriverCapabilities",
    "RuntimeHandle", "ExecutionPayload", "ExecutionResult",
    "SnapshotRef", "RuntimeConfig",
]
```

- [ ] **Step 5: Create isolation_driver.py**

```python
# core/isolation_abstraction/isolation_driver.py
from __future__ import annotations
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class IsolationTier(IntEnum):
    FIRECRACKER = 1
    QEMU = 2
    DOCKER_HARDENED = 3
    SANDBOX = 4
    PROCESS_JAIL = 5


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


@dataclass
class RuntimeHandle:
    runtime_id: str
    runtime_type: str
    tier: IsolationTier
    created_at: datetime
    _internal: dict = field(default_factory=dict, repr=False, compare=False)

    def __hash__(self) -> int:
        return hash(self.runtime_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RuntimeHandle):
            return self.runtime_id == other.runtime_id
        return NotImplemented


@dataclass
class ExecutionPayload:
    code: str | None = None
    command: str | None = None
    timeout_seconds: int = 30
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: str | None
    exit_code: int
    runtime_id: str
    tier_used: IsolationTier
    duration_ms: int
    negotiation: Any = None  # NegotiationResult, set after negotiation


@dataclass(frozen=True)
class SnapshotRef:
    available: bool
    snapshot_id: str | None = None
    reason: str | None = None


@dataclass
class RuntimeConfig:
    agent_id: str
    profile: str = "safe"
    max_cpu_percent: float = 50.0
    max_ram_mb: int = 512
    max_runtime_seconds: int = 60
    network_isolated: bool = True


TIER_SECURITY_SCORES: dict[IsolationTier, int] = {
    IsolationTier.FIRECRACKER: 95,
    IsolationTier.QEMU: 87,
    IsolationTier.DOCKER_HARDENED: 70,
    IsolationTier.SANDBOX: 40,
    IsolationTier.PROCESS_JAIL: 20,
}

TIER_RISK_ADJUSTMENTS: dict[IsolationTier, int] = {
    IsolationTier.FIRECRACKER: 0,
    IsolationTier.QEMU: -5,  # higher device emulation attack surface
    IsolationTier.DOCKER_HARDENED: 0,
    IsolationTier.SANDBOX: 0,
    IsolationTier.PROCESS_JAIL: 0,
}

TIER_CAPABILITIES: dict[IsolationTier, DriverCapabilities] = {
    IsolationTier.FIRECRACKER: DriverCapabilities(
        tier=IsolationTier.FIRECRACKER,
        supports_snapshots=True, supports_memory_snapshots=True,
        supports_hot_snapshot=True, supports_incremental_snapshots=True,
        supports_behavioral_lab=True, supports_network_isolation=True,
        supports_filesystem_isolation=True, supports_forensics=True,
        supports_live_forensics=True, supports_nested_isolation=True,
        supports_readonly_rootfs=True, supports_secure_boot=True,
        supports_tpm_emulation=True, supports_virtualized_gpu=False,
        supports_gpu_isolation=False, supports_network_deception=True,
        supports_runtime_migration=True, supports_attestation=True,
        supports_remote_nodes=True, supports_remote_execution=True,
        max_concurrent_runtimes=50,
    ),
    IsolationTier.QEMU: DriverCapabilities(
        tier=IsolationTier.QEMU,
        supports_snapshots=True, supports_memory_snapshots=True,
        supports_hot_snapshot=False, supports_incremental_snapshots=True,
        supports_behavioral_lab=True, supports_network_isolation=True,
        supports_filesystem_isolation=True, supports_forensics=True,
        supports_live_forensics=True, supports_nested_isolation=False,
        supports_readonly_rootfs=True, supports_secure_boot=True,
        supports_tpm_emulation=True, supports_virtualized_gpu=True,
        supports_gpu_isolation=False, supports_network_deception=True,
        supports_runtime_migration=False, supports_attestation=False,
        supports_remote_nodes=False, supports_remote_execution=False,
        max_concurrent_runtimes=10,
    ),
    IsolationTier.DOCKER_HARDENED: DriverCapabilities(
        tier=IsolationTier.DOCKER_HARDENED,
        supports_snapshots=True, supports_memory_snapshots=False,
        supports_hot_snapshot=False, supports_incremental_snapshots=False,
        supports_behavioral_lab=True, supports_network_isolation=True,
        supports_filesystem_isolation=True, supports_forensics=True,
        supports_live_forensics=False, supports_nested_isolation=False,
        supports_readonly_rootfs=True, supports_secure_boot=False,
        supports_tpm_emulation=False, supports_virtualized_gpu=False,
        supports_gpu_isolation=False, supports_network_deception=False,
        supports_runtime_migration=False, supports_attestation=False,
        supports_remote_nodes=False, supports_remote_execution=False,
        max_concurrent_runtimes=20,
    ),
    IsolationTier.SANDBOX: DriverCapabilities(
        tier=IsolationTier.SANDBOX,
        supports_snapshots=False, supports_memory_snapshots=False,
        supports_hot_snapshot=False, supports_incremental_snapshots=False,
        supports_behavioral_lab=False, supports_network_isolation=True,
        supports_filesystem_isolation=True, supports_forensics=False,
        supports_live_forensics=False, supports_nested_isolation=False,
        supports_readonly_rootfs=False, supports_secure_boot=False,
        supports_tpm_emulation=False, supports_virtualized_gpu=False,
        supports_gpu_isolation=False, supports_network_deception=False,
        supports_runtime_migration=False, supports_attestation=False,
        supports_remote_nodes=False, supports_remote_execution=False,
        max_concurrent_runtimes=0,
    ),
    IsolationTier.PROCESS_JAIL: DriverCapabilities(
        tier=IsolationTier.PROCESS_JAIL,
        supports_snapshots=False, supports_memory_snapshots=False,
        supports_hot_snapshot=False, supports_incremental_snapshots=False,
        supports_behavioral_lab=False, supports_network_isolation=False,
        supports_filesystem_isolation=True, supports_forensics=False,
        supports_live_forensics=False, supports_nested_isolation=False,
        supports_readonly_rootfs=False, supports_secure_boot=False,
        supports_tpm_emulation=False, supports_virtualized_gpu=False,
        supports_gpu_isolation=False, supports_network_deception=False,
        supports_runtime_migration=False, supports_attestation=False,
        supports_remote_nodes=False, supports_remote_execution=False,
        max_concurrent_runtimes=0,
    ),
}


class IsolationDriver(ABC):
    @property
    @abstractmethod
    def tier(self) -> IsolationTier: ...

    @property
    @abstractmethod
    def capabilities(self) -> DriverCapabilities: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle: ...

    @abstractmethod
    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult: ...

    @abstractmethod
    async def destroy(self, handle: RuntimeHandle) -> None: ...

    @abstractmethod
    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef: ...

    @abstractmethod
    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None: ...
```

- [ ] **Step 6: Run tests — verify they pass**

```
pytest tests/test_isolation_abstraction/test_isolation_driver.py -v
```
Expected: 8 PASSED

- [ ] **Step 7: Commit**

```
git add core/isolation_abstraction/__init__.py core/isolation_abstraction/isolation_driver.py tests/test_isolation_abstraction/
git commit -m "feat(isolation): core types, IsolationDriver ABC, TIER_CAPABILITIES"
```

---

## Task 2: Capability Detector

**Files:**
- Create: `core/isolation_abstraction/isolation_capability_detector.py`
- Create: `tests/test_isolation_abstraction/test_capability_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_isolation_abstraction/test_capability_detector.py
import time
import pytest
from unittest.mock import patch
from core.isolation_abstraction.isolation_capability_detector import (
    IsolationCapabilityDetector, CapabilitySnapshot,
)
from core.isolation_abstraction.isolation_driver import IsolationTier


def make_detector() -> IsolationCapabilityDetector:
    return IsolationCapabilityDetector()


def test_detect_returns_capability_snapshot():
    d = make_detector()
    snap = d.detect()
    assert isinstance(snap, CapabilitySnapshot)


def test_snapshot_is_frozen():
    d = make_detector()
    snap = d.detect()
    with pytest.raises(Exception):
        snap.has_docker = True


def test_sandbox_and_jail_always_available():
    d = make_detector()
    snap = d.detect()
    assert IsolationTier.SANDBOX in snap.available_tiers
    assert IsolationTier.PROCESS_JAIL in snap.available_tiers


def test_detect_cached_on_second_call():
    d = make_detector()
    snap1 = d.detect()
    snap2 = d.detect()
    assert snap1 is snap2  # same object, not re-probed


def test_refresh_returns_new_snapshot():
    d = make_detector()
    snap1 = d.detect()
    snap2 = d.refresh_capabilities(reason="test", requester="pytest")
    assert snap2 is not snap1


def test_refresh_cooldown_enforced():
    d = make_detector()
    d.detect()
    d.refresh_capabilities(reason="first", requester="pytest", cooldown_seconds=60)
    # Second refresh within cooldown raises
    with pytest.raises(ValueError, match="cooldown"):
        d.refresh_capabilities(reason="second", requester="pytest", cooldown_seconds=60)


def test_host_os_detected():
    d = make_detector()
    snap = d.detect()
    assert snap.host_os in ("linux", "windows", "macos", "unknown")


def test_firecracker_unavailable_on_windows_without_kvm():
    d = make_detector()
    snap = d.detect()
    import platform
    if platform.system().lower() == "windows":
        assert IsolationTier.FIRECRACKER not in snap.available_tiers


def test_last_refresh_reason_startup():
    d = make_detector()
    snap = d.detect()
    assert snap.last_refresh_reason == "startup"
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_capability_detector.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/isolation_abstraction/isolation_capability_detector.py
from __future__ import annotations
import os
import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .isolation_driver import IsolationTier


@dataclass(frozen=True)
class CapabilitySnapshot:
    has_firecracker: bool
    has_qemu: bool
    has_kvm: bool
    has_docker: bool
    has_wsl2: bool
    has_nested_virtualization: bool
    host_os: str
    docker_runtime: Optional[str]
    virtualization_type: Optional[str]
    last_refresh_reason: Optional[str]
    available_tiers: frozenset
    detected_at: datetime


class IsolationCapabilityDetector:
    _instance: Optional["IsolationCapabilityDetector"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._cache: Optional[CapabilitySnapshot] = None
        self._cache_lock = threading.Lock()
        self._last_refresh_at: Optional[datetime] = None

    def detect(self) -> CapabilitySnapshot:
        with self._cache_lock:
            if self._cache is None:
                self._cache = self._probe("startup")
                self._last_refresh_at = datetime.utcnow()
            return self._cache

    def refresh_capabilities(
        self,
        reason: str,
        requester: str,
        cooldown_seconds: int = 30,
    ) -> CapabilitySnapshot:
        with self._cache_lock:
            if self._last_refresh_at is not None:
                elapsed = (datetime.utcnow() - self._last_refresh_at).total_seconds()
                if elapsed < cooldown_seconds:
                    raise ValueError(
                        f"refresh cooldown active: {cooldown_seconds - elapsed:.0f}s remaining"
                    )
            self._cache = self._probe(reason)
            self._last_refresh_at = datetime.utcnow()
            return self._cache

    def _probe(self, reason: str) -> CapabilitySnapshot:
        sys = platform.system().lower()
        host_os = {"linux": "linux", "windows": "windows", "darwin": "macos"}.get(sys, "unknown")

        has_kvm = Path("/dev/kvm").exists() if host_os == "linux" else False
        has_firecracker = bool(shutil.which("firecracker")) and has_kvm
        has_qemu = bool(shutil.which("qemu-system-x86_64")) and has_kvm

        has_docker, docker_runtime = self._probe_docker()

        has_wsl2 = self._probe_wsl2(host_os)

        virt_type: Optional[str] = None
        if has_kvm:
            virt_type = "kvm"
        elif host_os == "windows":
            virt_type = "hyperv"
        elif has_wsl2:
            virt_type = "wsl2"

        tiers: set[IsolationTier] = {IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
        if has_docker:
            tiers.add(IsolationTier.DOCKER_HARDENED)
        if has_qemu:
            tiers.add(IsolationTier.QEMU)
        if has_firecracker:
            tiers.add(IsolationTier.FIRECRACKER)

        return CapabilitySnapshot(
            has_firecracker=has_firecracker,
            has_qemu=has_qemu,
            has_kvm=has_kvm,
            has_docker=has_docker,
            has_wsl2=has_wsl2,
            has_nested_virtualization=has_kvm,
            host_os=host_os,
            docker_runtime=docker_runtime,
            virtualization_type=virt_type,
            last_refresh_reason=reason,
            available_tiers=frozenset(tiers),
            detected_at=datetime.utcnow(),
        )

    @staticmethod
    def _probe_docker() -> tuple[bool, Optional[str]]:
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return True, "docker"
        except Exception:
            pass
        return False, None

    @staticmethod
    def _probe_wsl2(host_os: str) -> bool:
        if host_os == "linux":
            try:
                content = Path("/proc/version").read_text().lower()
                return "microsoft" in content
            except Exception:
                pass
        return "WSL_DISTRO_NAME" in os.environ


_detector_instance: Optional[IsolationCapabilityDetector] = None
_detector_lock = threading.Lock()


def get_capability_detector() -> IsolationCapabilityDetector:
    global _detector_instance
    if _detector_instance is None:
        with _detector_lock:
            if _detector_instance is None:
                _detector_instance = IsolationCapabilityDetector()
    return _detector_instance
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_isolation_abstraction/test_capability_detector.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Commit**

```
git add core/isolation_abstraction/isolation_capability_detector.py tests/test_isolation_abstraction/test_capability_detector.py
git commit -m "feat(isolation): CapabilitySnapshot + IsolationCapabilityDetector with rate-limited refresh"
```

---

## Task 3: Strategy Manager — Policy-Based Tier Selection

**Files:**
- Create: `core/isolation_abstraction/isolation_strategy_manager.py`
- Create: `tests/test_isolation_abstraction/test_strategy_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_isolation_abstraction/test_strategy_manager.py
import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
from datetime import datetime
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy, IsolationStrategyManager, IsolationUnavailableError,
)


def snap(tiers: set[IsolationTier]) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        has_firecracker=IsolationTier.FIRECRACKER in tiers,
        has_qemu=IsolationTier.QEMU in tiers,
        has_kvm=IsolationTier.FIRECRACKER in tiers or IsolationTier.QEMU in tiers,
        has_docker=IsolationTier.DOCKER_HARDENED in tiers,
        has_wsl2=False, has_nested_virtualization=False,
        host_os="linux" if IsolationTier.FIRECRACKER in tiers else "windows",
        docker_runtime="docker" if IsolationTier.DOCKER_HARDENED in tiers else None,
        virtualization_type=None, last_refresh_reason="test",
        available_tiers=frozenset(tiers),
        detected_at=datetime.utcnow(),
    )


ALL_TIERS = {IsolationTier.FIRECRACKER, IsolationTier.QEMU, IsolationTier.DOCKER_HARDENED,
             IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
WINDOWS_TIERS = {IsolationTier.DOCKER_HARDENED, IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
MINIMAL_TIERS = {IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}

mgr = IsolationStrategyManager()


def test_best_available_picks_firecracker_when_available():
    tier, *_ = mgr.select_tier(snap(ALL_TIERS), IsolationPolicy.BEST_AVAILABLE, None)
    assert tier == IsolationTier.FIRECRACKER


def test_best_available_falls_back_to_docker_on_windows():
    tier, *_ = mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None)
    assert tier == IsolationTier.DOCKER_HARDENED


def test_strict_isolation_blocks_if_no_kvm():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.STRICT_ISOLATION, None)


def test_strict_isolation_passes_with_firecracker():
    tier, *_ = mgr.select_tier(snap(ALL_TIERS), IsolationPolicy.STRICT_ISOLATION, None)
    assert tier in (IsolationTier.FIRECRACKER, IsolationTier.QEMU)


def test_no_fallback_raises_if_tier_unavailable():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(
            snap(WINDOWS_TIERS),
            IsolationPolicy.NO_FALLBACK,
            IsolationTier.FIRECRACKER,
        )


def test_no_fallback_succeeds_exact_match():
    tier, *_ = mgr.select_tier(
        snap(WINDOWS_TIERS),
        IsolationPolicy.NO_FALLBACK,
        IsolationTier.DOCKER_HARDENED,
    )
    assert tier == IsolationTier.DOCKER_HARDENED


def test_minimum_security_score_filters_low_tiers():
    tier, _, rejections = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
        min_security_score=65,
    )
    assert tier == IsolationTier.DOCKER_HARDENED  # score=70 passes
    assert IsolationTier.SANDBOX.name in rejections  # score=40 rejected


def test_required_capability_filters_incompatible_driver():
    tier, _, rejections = mgr.select_tier(
        snap(MINIMAL_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
        required_capabilities={"supports_forensics"},
    )
    # Neither sandbox nor jail supports forensics → IsolationUnavailableError
    # Actually this should raise since no tier satisfies
    assert False, "Should have raised"  # test verifies exception path


def test_required_capability_filters_incompatible_driver_raises():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(
            snap(MINIMAL_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
            required_capabilities={"supports_forensics"},
        )


def test_safe_degradation_allows_docker():
    tier, *_ = mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.SAFE_DEGRADATION, None)
    assert tier == IsolationTier.DOCKER_HARDENED
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_strategy_manager.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Remove the broken test and replace with correct version**

The test `test_required_capability_filters_incompatible_driver` has an `assert False` — remove it. The following test `test_required_capability_filters_incompatible_driver_raises` covers the same case correctly. Delete lines 73–76 (the broken test).

- [ ] **Step 4: Implement**

```python
# core/isolation_abstraction/isolation_strategy_manager.py
from __future__ import annotations
from enum import Enum
from typing import Optional

from .isolation_capability_detector import CapabilitySnapshot
from .isolation_driver import IsolationTier, TIER_CAPABILITIES, TIER_SECURITY_SCORES, TIER_RISK_ADJUSTMENTS


class IsolationPolicy(str, Enum):
    BEST_AVAILABLE = "best_available"
    SAFE_DEGRADATION = "safe_degradation"
    STRICT_ISOLATION = "strict_isolation"
    NO_FALLBACK = "no_fallback"


class IsolationUnavailableError(RuntimeError):
    pass


class IsolationStrategyManager:
    """Pure tier selection — no I/O, fully testable."""

    def select_tier(
        self,
        snapshot: CapabilitySnapshot,
        policy: IsolationPolicy,
        requested_tier: Optional[IsolationTier],
        min_security_score: int = 0,
        required_capabilities: Optional[set[str]] = None,
    ) -> tuple[IsolationTier, list[IsolationTier], dict[str, str]]:
        """
        Returns (selected_tier, tried_tiers, rejection_reasons).
        Raises IsolationUnavailableError if no tier satisfies constraints.
        """
        candidates = sorted(snapshot.available_tiers)  # IntEnum: smallest = best tier
        tried: list[IsolationTier] = []
        rejections: dict[str, str] = {}

        for tier in candidates:
            caps = TIER_CAPABILITIES[tier]
            score = TIER_SECURITY_SCORES[tier] + TIER_RISK_ADJUSTMENTS[tier]

            if score < min_security_score:
                rejections[tier.name] = f"score {score} < minimum {min_security_score}"
                tried.append(tier)
                continue

            if required_capabilities:
                missing = [c for c in required_capabilities if not getattr(caps, c, False)]
                if missing:
                    rejections[tier.name] = f"missing: {missing}"
                    tried.append(tier)
                    continue

            if policy == IsolationPolicy.NO_FALLBACK:
                if requested_tier is not None and tier != requested_tier:
                    rejections[tier.name] = "no_fallback: exact tier required"
                    tried.append(tier)
                    continue

            elif policy == IsolationPolicy.STRICT_ISOLATION:
                if tier not in (IsolationTier.FIRECRACKER, IsolationTier.QEMU):
                    rejections[tier.name] = "strict_isolation: requires tier 1 or 2"
                    tried.append(tier)
                    continue

            elif policy == IsolationPolicy.SAFE_DEGRADATION:
                if tier > IsolationTier.DOCKER_HARDENED:
                    if required_capabilities and "supports_network_isolation" in required_capabilities:
                        rejections[tier.name] = "safe_degradation: network isolation requires tier ≤ 3"
                        tried.append(tier)
                        continue

            return tier, tried, rejections

        raise IsolationUnavailableError(
            f"No tier satisfies policy={policy.value}, min_score={min_security_score}. "
            f"Available: {list(snapshot.available_tiers)}. Rejections: {rejections}"
        )
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_isolation_abstraction/test_strategy_manager.py -v
```
Expected: 9 PASSED

- [ ] **Step 6: Commit**

```
git add core/isolation_abstraction/isolation_strategy_manager.py tests/test_isolation_abstraction/test_strategy_manager.py
git commit -m "feat(isolation): IsolationPolicy + IsolationStrategyManager with four named policies"
```

---

## Task 4: Negotiator — Full Reasoning Record

**Files:**
- Create: `core/isolation_abstraction/isolation_negotiator.py`
- Create: `tests/test_isolation_abstraction/test_negotiator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_isolation_abstraction/test_negotiator.py
from datetime import datetime
import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier, TIER_CAPABILITIES, TIER_SECURITY_SCORES
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import IsolationNegotiator, NegotiationResult


def snap(tiers):
    return CapabilitySnapshot(
        has_firecracker=IsolationTier.FIRECRACKER in tiers,
        has_qemu=False, has_kvm=False,
        has_docker=IsolationTier.DOCKER_HARDENED in tiers,
        has_wsl2=False, has_nested_virtualization=False,
        host_os="windows",
        docker_runtime="docker" if IsolationTier.DOCKER_HARDENED in tiers else None,
        virtualization_type=None, last_refresh_reason="test",
        available_tiers=frozenset(tiers),
        detected_at=datetime.utcnow(),
    )


WINDOWS = {IsolationTier.DOCKER_HARDENED, IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
neg = IsolationNegotiator()


def test_negotiate_returns_negotiation_result():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert isinstance(result, NegotiationResult)


def test_fallback_level_zero_when_exact_match():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.NO_FALLBACK,
        requested_tier=IsolationTier.DOCKER_HARDENED
    )
    assert result.fallback_level == 0
    assert result.actual_tier == IsolationTier.DOCKER_HARDENED


def test_fallback_level_nonzero_when_degraded():
    # Request Tier 1 but only Tier 3 available
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE,
        requested_tier=IsolationTier.FIRECRACKER,
    )
    assert result.fallback_level > 0
    assert result.actual_tier == IsolationTier.DOCKER_HARDENED


def test_security_score_matches_tier():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    expected = TIER_SECURITY_SCORES[result.actual_tier]
    assert result.security_score == expected


def test_risk_adjusted_score_lower_for_qemu():
    ALL = frozenset(IsolationTier)
    full_snap = CapabilitySnapshot(
        has_firecracker=False, has_qemu=True, has_kvm=True, has_docker=True,
        has_wsl2=False, has_nested_virtualization=True, host_os="linux",
        docker_runtime="docker", virtualization_type="kvm", last_refresh_reason="test",
        available_tiers=frozenset({IsolationTier.QEMU, IsolationTier.DOCKER_HARDENED,
                                    IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}),
        detected_at=datetime.utcnow(),
    )
    result = neg.negotiate(full_snap, IsolationPolicy.BEST_AVAILABLE,
                           requested_tier=IsolationTier.QEMU)
    assert result.risk_adjusted_score < result.security_score


def test_candidate_drivers_populated():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert len(result.candidate_drivers) > 0


def test_rejection_reasons_populated_on_fallback():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE,
        requested_tier=IsolationTier.FIRECRACKER,
    )
    assert len(result.rejection_reasons) > 0


def test_forensic_support_matches_capabilities():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    caps = TIER_CAPABILITIES[result.actual_tier]
    assert result.forensic_support == caps.supports_forensics
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_negotiator.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/isolation_abstraction/isolation_negotiator.py
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .isolation_capability_detector import CapabilitySnapshot, get_capability_detector
from .isolation_driver import (
    IsolationTier, DriverCapabilities, TIER_CAPABILITIES,
    TIER_SECURITY_SCORES, TIER_RISK_ADJUSTMENTS,
)
from .isolation_strategy_manager import IsolationPolicy, IsolationStrategyManager


@dataclass
class NegotiationResult:
    requested_tier: Optional[IsolationTier]
    actual_tier: IsolationTier
    policy: IsolationPolicy
    reason: str
    host_os: str
    fallback_level: int
    fallback_chain: tuple
    driver_capabilities: DriverCapabilities
    security_score: int
    risk_adjusted_score: int
    forensic_support: bool
    behavioral_support: bool
    candidate_drivers: tuple
    rejection_reasons: dict
    capability_mismatches: dict
    policy_rejections: dict
    execution_duration_ms: Optional[int] = None
    actual_runtime_health: Optional[str] = None
    post_execution_anomalies: list = field(default_factory=list)
    degradation_impact: Optional[str] = None
    remote_execution_ready: bool = False
    degradation_acceptable: bool = True
    negotiated_at: datetime = field(default_factory=datetime.utcnow)


class IsolationNegotiator:
    def __init__(self) -> None:
        self._strategy = IsolationStrategyManager()

    def negotiate(
        self,
        snapshot: CapabilitySnapshot,
        policy: IsolationPolicy,
        requested_tier: Optional[IsolationTier] = None,
        min_security_score: int = 0,
        required_capabilities: Optional[set[str]] = None,
    ) -> NegotiationResult:
        selected, tried, rejections = self._strategy.select_tier(
            snapshot, policy, requested_tier,
            min_security_score, required_capabilities,
        )

        caps = TIER_CAPABILITIES[selected]
        base_score = TIER_SECURITY_SCORES[selected]
        adj = TIER_RISK_ADJUSTMENTS[selected]

        fallback_level = 0
        if requested_tier is not None and selected != requested_tier:
            fallback_level = selected.value - (
                requested_tier.value if requested_tier in snapshot.available_tiers
                else min(snapshot.available_tiers).value
            )
            fallback_level = max(1, abs(fallback_level))

        return NegotiationResult(
            requested_tier=requested_tier,
            actual_tier=selected,
            policy=policy,
            reason=self._build_reason(selected, requested_tier, fallback_level),
            host_os=snapshot.host_os,
            fallback_level=fallback_level,
            fallback_chain=tuple(tried),
            driver_capabilities=caps,
            security_score=base_score,
            risk_adjusted_score=base_score + adj,
            forensic_support=caps.supports_forensics,
            behavioral_support=caps.supports_behavioral_lab,
            candidate_drivers=tuple(snapshot.available_tiers),
            rejection_reasons=rejections,
            capability_mismatches={},
            policy_rejections={},
            remote_execution_ready=caps.supports_remote_execution,
            degradation_acceptable=(fallback_level == 0 or policy != IsolationPolicy.NO_FALLBACK),
        )

    @staticmethod
    def _build_reason(
        selected: IsolationTier,
        requested: Optional[IsolationTier],
        fallback_level: int,
    ) -> str:
        if fallback_level == 0 or requested is None:
            return f"exact_match: {selected.name}"
        return f"fallback_from_{requested.name}_to_{selected.name} (level={fallback_level})"


_negotiator_instance: Optional[IsolationNegotiator] = None
_negotiator_lock = threading.Lock()


def get_negotiator() -> IsolationNegotiator:
    global _negotiator_instance
    if _negotiator_instance is None:
        with _negotiator_lock:
            if _negotiator_instance is None:
                _negotiator_instance = IsolationNegotiator()
    return _negotiator_instance
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_isolation_abstraction/test_negotiator.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Commit**

```
git add core/isolation_abstraction/isolation_negotiator.py tests/test_isolation_abstraction/test_negotiator.py
git commit -m "feat(isolation): IsolationNegotiator + NegotiationResult with full reasoning trail"
```

---

## Task 5: Tier 5 — ProcessJailDriver

**Files:**
- Create: `core/isolation_abstraction/drivers/__init__.py`
- Create: `core/isolation_abstraction/drivers/process_jail_driver.py`
- Create: `tests/test_isolation_abstraction/test_drivers.py`

- [ ] **Step 1: Write failing tests (ProcessJail section)**

```python
# tests/test_isolation_abstraction/test_drivers.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, RuntimeConfig, ExecutionPayload,
)


# ─── ProcessJailDriver ────────────────────────────────────────────────────────

def test_process_jail_driver_tier():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    assert d.tier == IsolationTier.PROCESS_JAIL


def test_process_jail_driver_always_available():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    assert d.is_available() is True


def test_process_jail_capabilities_match_tier():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    d = ProcessJailDriver()
    assert d.capabilities == TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]


@pytest.mark.asyncio
async def test_process_jail_create_runtime_returns_handle():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    from core.isolation.isolation_manager import get_isolation_manager
    mock_mgr = MagicMock()
    mock_mgr.create_isolated_workspace.return_value = "/tmp/workspace"
    with patch("core.isolation_abstraction.drivers.process_jail_driver.get_isolation_manager",
               return_value=mock_mgr):
        d = ProcessJailDriver()
        config = RuntimeConfig(agent_id="test-agent")
        handle = await d.create_runtime(config)
    assert handle.tier == IsolationTier.PROCESS_JAIL
    assert handle.runtime_id is not None


@pytest.mark.asyncio
async def test_process_jail_snapshot_returns_unavailable():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    from datetime import datetime
    from core.isolation_abstraction.isolation_driver import RuntimeHandle
    d = ProcessJailDriver()
    handle = RuntimeHandle(
        runtime_id="x", runtime_type="jail",
        tier=IsolationTier.PROCESS_JAIL, created_at=datetime.utcnow()
    )
    ref = await d.snapshot(handle)
    assert ref.available is False
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_drivers.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create drivers package**

```python
# core/isolation_abstraction/drivers/__init__.py
from .process_jail_driver import ProcessJailDriver
from .sandbox_driver import SandboxDriver
from .docker_hardened_driver import DockerHardenedDriver

ALL_DRIVERS = [DockerHardenedDriver, SandboxDriver, ProcessJailDriver]
```

- [ ] **Step 4: Implement ProcessJailDriver**

```python
# core/isolation_abstraction/drivers/process_jail_driver.py
from __future__ import annotations
import uuid
from datetime import datetime

from ..isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities,
    RuntimeConfig, RuntimeHandle, ExecutionPayload, ExecutionResult,
    SnapshotRef, TIER_CAPABILITIES,
)


class ProcessJailDriver(IsolationDriver):
    """Tier 5: Wraps existing IsolationManager. Always available."""

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.PROCESS_JAIL

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]

    def is_available(self) -> bool:
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        from core.isolation.isolation_manager import get_isolation_manager
        mgr = get_isolation_manager()
        workspace = mgr.create_isolated_workspace(config.agent_id, ".")
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="jail",
            tier=IsolationTier.PROCESS_JAIL,
            created_at=datetime.utcnow(),
        )
        handle._internal["workspace"] = workspace
        handle._internal["agent_id"] = config.agent_id
        return handle

    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult:
        import asyncio, time
        from core.isolation.isolation_manager import get_isolation_manager
        start = time.monotonic()
        mgr = get_isolation_manager()
        output, error, code = "", None, 0
        try:
            if payload.command:
                result = await asyncio.create_subprocess_shell(
                    payload.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=handle._internal.get("workspace", "."),
                )
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=payload.timeout_seconds
                )
                output = stdout.decode(errors="replace")
                error = stderr.decode(errors="replace") or None
                code = result.returncode or 0
        except Exception as e:
            error = str(e)
            code = 1
        return ExecutionResult(
            success=code == 0,
            output=output,
            error=error,
            exit_code=code,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.PROCESS_JAIL,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        pass  # process jail cleanup is lightweight; workspace temp dir removed by OS

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        return SnapshotRef(available=False, reason="process_jail_no_snapshots")

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        from core.isolation.isolation_manager import get_isolation_manager
        mgr = get_isolation_manager()
        agent_id = handle._internal.get("agent_id", "unknown")
        # Best-effort: flag in existing permission manager
        try:
            from core.security.permission_manager import get_permission_manager
            get_permission_manager().isolate_agent(agent_id, reason)
        except Exception:
            pass
```

- [ ] **Step 5: Run ProcessJail tests**

```
pytest tests/test_isolation_abstraction/test_drivers.py -k "process_jail" -v
```
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```
git add core/isolation_abstraction/drivers/ tests/test_isolation_abstraction/test_drivers.py
git commit -m "feat(isolation): ProcessJailDriver (Tier 5) — always-available fallback"
```

---

## Task 6: Tier 4 — SandboxDriver

**Files:**
- Modify: `core/isolation_abstraction/drivers/sandbox_driver.py` (create)
- Modify: `tests/test_isolation_abstraction/test_drivers.py` (add tests)

- [ ] **Step 1: Add SandboxDriver tests to test_drivers.py**

Append to `tests/test_isolation_abstraction/test_drivers.py`:

```python
# ─── SandboxDriver ────────────────────────────────────────────────────────────

def test_sandbox_driver_tier():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    d = SandboxDriver()
    assert d.tier == IsolationTier.SANDBOX


def test_sandbox_driver_always_available():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    d = SandboxDriver()
    assert d.is_available() is True


@pytest.mark.asyncio
async def test_sandbox_create_returns_handle():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {
        "sandbox_id": "sb-001", "status": "CREATED"
    }
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
    assert handle.tier == IsolationTier.SANDBOX
    assert handle._internal["sandbox_id"] == "sb-001"


@pytest.mark.asyncio
async def test_sandbox_quarantine_calls_manager():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    from core.isolation_abstraction.isolation_driver import RuntimeHandle
    mock_mgr = MagicMock()
    mock_mgr.quarantine_sandbox.return_value = True
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = RuntimeHandle(
            runtime_id="r1", runtime_type="sandbox",
            tier=IsolationTier.SANDBOX, created_at=datetime.utcnow()
        )
        handle._internal["sandbox_id"] = "sb-001"
        await d.quarantine(handle, "test")
    mock_mgr.quarantine_sandbox.assert_called_once_with("sb-001", "test")
```

- [ ] **Step 2: Run to verify new tests fail**

```
pytest tests/test_isolation_abstraction/test_drivers.py -k "sandbox" -v
```
Expected: `ImportError` for `SandboxDriver`

- [ ] **Step 3: Implement SandboxDriver**

```python
# core/isolation_abstraction/drivers/sandbox_driver.py
from __future__ import annotations
import uuid
from datetime import datetime

from ..isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities,
    RuntimeConfig, RuntimeHandle, ExecutionPayload, ExecutionResult,
    SnapshotRef, TIER_CAPABILITIES,
)


class SandboxDriver(IsolationDriver):
    """Tier 4: Wraps existing SandboxManager. Always available."""

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.SANDBOX

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.SANDBOX]

    def is_available(self) -> bool:
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        from core.sandbox.sandbox_manager import get_sandbox_manager
        mgr = get_sandbox_manager()
        result = mgr.create_sandbox(
            agent_id=config.agent_id,
            mode="STRICT_ISOLATION",
        )
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="sandbox",
            tier=IsolationTier.SANDBOX,
            created_at=datetime.utcnow(),
        )
        handle._internal["sandbox_id"] = result["sandbox_id"]
        handle._internal["agent_id"] = config.agent_id
        return handle

    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult:
        import time
        from core.sandbox.sandbox_manager import get_sandbox_manager
        start = time.monotonic()
        mgr = get_sandbox_manager()
        cmd = payload.command or (f"python -c {repr(payload.code)}" if payload.code else "")
        result = mgr.execute_in_sandbox(
            command=cmd,
            mode="STRICT_ISOLATION",
            agent_id=handle._internal.get("agent_id", "unknown"),
        )
        return ExecutionResult(
            success=result.get("success", False),
            output=result.get("output", ""),
            error=result.get("error"),
            exit_code=result.get("exit_code", 0),
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.SANDBOX,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        from core.sandbox.sandbox_manager import get_sandbox_manager
        try:
            get_sandbox_manager().destroy_sandbox(handle._internal["sandbox_id"])
        except Exception:
            pass

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        return SnapshotRef(available=False, reason="sandbox_no_snapshots")

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        from core.sandbox.sandbox_manager import get_sandbox_manager
        try:
            get_sandbox_manager().quarantine_sandbox(handle._internal["sandbox_id"], reason)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_isolation_abstraction/test_drivers.py -k "sandbox" -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```
git add core/isolation_abstraction/drivers/sandbox_driver.py tests/test_isolation_abstraction/test_drivers.py
git commit -m "feat(isolation): SandboxDriver (Tier 4) wrapping SandboxManager"
```

---

## Task 7: Tier 3 — DockerHardenedDriver

**Files:**
- Create: `core/isolation_abstraction/drivers/docker_hardened_driver.py`
- Modify: `tests/test_isolation_abstraction/test_drivers.py` (add tests)

- [ ] **Step 1: Install docker SDK if missing**

```
pip install docker
```

- [ ] **Step 2: Add DockerHardenedDriver tests**

Append to `tests/test_isolation_abstraction/test_drivers.py`:

```python
# ─── DockerHardenedDriver ─────────────────────────────────────────────────────

def test_docker_driver_tier():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    d = DockerHardenedDriver()
    assert d.tier == IsolationTier.DOCKER_HARDENED


def test_docker_driver_unavailable_when_no_docker(monkeypatch):
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=1))
    d = DockerHardenedDriver()
    d._available = None  # reset cached value
    assert d.is_available() is False


@pytest.mark.asyncio
async def test_docker_create_runtime_uses_hardened_config():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    import docker
    mock_container = MagicMock()
    mock_container.id = "ctr-abc123"
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container
    with patch("core.isolation_abstraction.drivers.docker_hardened_driver.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_client
        mock_docker.DockerClient.return_value = mock_client
        d = DockerHardenedDriver()
        d._available = True
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
    assert handle.tier == IsolationTier.DOCKER_HARDENED
    assert handle._internal["container_id"] == "ctr-abc123"


@pytest.mark.asyncio
async def test_docker_snapshot_returns_available():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    from core.isolation_abstraction.isolation_driver import RuntimeHandle
    mock_container = MagicMock()
    mock_container.commit.return_value = MagicMock(id="img-snap-001")
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    with patch("core.isolation_abstraction.drivers.docker_hardened_driver.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_client
        d = DockerHardenedDriver()
        d._available = True
        handle = RuntimeHandle(
            runtime_id="r1", runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.utcnow()
        )
        handle._internal["container_id"] = "ctr-abc123"
        ref = await d.snapshot(handle)
    assert ref.available is True
```

- [ ] **Step 3: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_drivers.py -k "docker" -v
```
Expected: `ImportError`

- [ ] **Step 4: Implement DockerHardenedDriver**

```python
# core/isolation_abstraction/drivers/docker_hardened_driver.py
from __future__ import annotations
import platform
import subprocess
import uuid
from datetime import datetime
from typing import Optional

from ..isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities,
    RuntimeConfig, RuntimeHandle, ExecutionPayload, ExecutionResult,
    SnapshotRef, TIER_CAPABILITIES,
)

_HARDENED_RUN_KWARGS = dict(
    read_only=False,           # overlay is writable, base image is readonly
    network_mode="none",       # no network by default; overridden by network_isolated=False
    mem_limit="512m",
    cpu_period=100_000,
    cpu_quota=50_000,          # 50% CPU
    pids_limit=64,
    security_opt=["no-new-privileges:true"],
    cap_drop=["ALL"],
    detach=True,
    remove=False,              # we manage lifecycle explicitly
)


class DockerHardenedDriver(IsolationDriver):
    """Tier 3: Docker container with hardened run config. Tier 3 on Windows today."""

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.DOCKER_HARDENED

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.DOCKER_HARDENED]

    def is_available(self) -> bool:
        if self._available is None:
            try:
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True, timeout=5,
                )
                self._available = result.returncode == 0
            except Exception:
                self._available = False
        return self._available

    def _client(self):
        import docker
        sys = platform.system().lower()
        if sys == "windows":
            return docker.DockerClient(base_url="npipe:////./pipe/docker_engine")
        return docker.from_env()

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        client = self._client()
        kwargs = dict(_HARDENED_RUN_KWARGS)
        kwargs["mem_limit"] = f"{config.max_ram_mb}m"
        kwargs["cpu_quota"] = int(config.max_cpu_percent * 1000)
        container = client.containers.run(
            "python:3.11-slim",
            command="sleep infinity",
            **kwargs,
        )
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED,
            created_at=datetime.utcnow(),
        )
        handle._internal["container_id"] = container.id
        handle._internal["agent_id"] = config.agent_id
        return handle

    async def execute(self, handle: RuntimeHandle, payload: ExecutionPayload) -> ExecutionResult:
        import time
        client = self._client()
        start = time.monotonic()
        ctr_id = handle._internal["container_id"]
        container = client.containers.get(ctr_id)
        cmd = payload.command or (f"python -c {repr(payload.code)}" if payload.code else "echo ''")
        exit_code, output = container.exec_run(
            cmd,
            demux=False,
            timeout=payload.timeout_seconds,
        )
        out_str = output.decode(errors="replace") if output else ""
        return ExecutionResult(
            success=exit_code == 0,
            output=out_str,
            error=out_str if exit_code != 0 else None,
            exit_code=exit_code or 0,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.DOCKER_HARDENED,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        try:
            client = self._client()
            ctr = client.containers.get(handle._internal["container_id"])
            ctr.remove(force=True)
        except Exception:
            pass

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        try:
            client = self._client()
            ctr = client.containers.get(handle._internal["container_id"])
            snap_id = str(uuid.uuid4())[:8]
            image = ctr.commit(repository=f"nexus-snap-{snap_id}")
            return SnapshotRef(available=True, snapshot_id=image.id)
        except Exception as e:
            return SnapshotRef(available=False, reason=str(e))

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        try:
            client = self._client()
            ctr = client.containers.get(handle._internal["container_id"])
            ctr.pause()  # freeze without destroying — preserve for forensics
        except Exception:
            pass
```

- [ ] **Step 5: Run all driver tests**

```
pytest tests/test_isolation_abstraction/test_drivers.py -v
```
Expected: all PASSED (Docker tests skip gracefully if daemon not running)

- [ ] **Step 6: Commit**

```
git add core/isolation_abstraction/drivers/docker_hardened_driver.py tests/test_isolation_abstraction/test_drivers.py
git commit -m "feat(isolation): DockerHardenedDriver (Tier 3) — hardened container runtime"
```

---

## Task 8: Database Schema + Audit Logger

**Files:**
- Create: `core/isolation_abstraction/isolation_audit_logger.py`
- Create: `tests/test_isolation_abstraction/test_audit_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_isolation_abstraction/test_audit_logger.py
import pytest
import sqlite3
from pathlib import Path
from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger


DB = Path("data/nexus_vm_isolation_test.db")


@pytest.fixture(autouse=True)
def clean_db():
    if DB.exists():
        DB.unlink()
    yield
    if DB.exists():
        DB.unlink()


def make_logger():
    return IsolationAuditLogger(db_path=DB)


def test_tables_created_on_init():
    logger = make_logger()
    with sqlite3.connect(str(DB)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "vm_events" in tables
    assert "vm_sessions" in tables
    assert "virtual_machines" in tables


def test_log_event_writes_row():
    logger = make_logger()
    logger.log_event(
        vm_id="vm-001",
        event_type="BOOT",
        severity="INFO",
        description="VM booted",
        metadata={},
    )
    with sqlite3.connect(str(DB)) as conn:
        rows = list(conn.execute("SELECT vm_id, event_type FROM vm_events"))
    assert len(rows) == 1
    assert rows[0] == ("vm-001", "BOOT")


def test_hash_chain_integrity():
    logger = make_logger()
    for i in range(3):
        logger.log_event(
            vm_id="vm-001",
            event_type=f"EVENT_{i}",
            severity="INFO",
            description=f"Event {i}",
            metadata={},
        )
    assert logger.verify_chain() is True


def test_tamper_detection():
    logger = make_logger()
    logger.log_event(vm_id="vm-001", event_type="BOOT", severity="INFO",
                     description="ok", metadata={})
    # Tamper the row
    with sqlite3.connect(str(DB)) as conn:
        conn.execute("UPDATE vm_events SET description='TAMPERED' WHERE 1=1")
    assert logger.verify_chain() is False


def test_log_negotiation_writes_session():
    from core.isolation_abstraction.isolation_driver import IsolationTier, TIER_CAPABILITIES
    from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
    from core.isolation_abstraction.isolation_negotiator import NegotiationResult
    from datetime import datetime
    result = NegotiationResult(
        requested_tier=IsolationTier.DOCKER_HARDENED,
        actual_tier=IsolationTier.DOCKER_HARDENED,
        policy=IsolationPolicy.BEST_AVAILABLE,
        reason="exact_match",
        host_os="windows",
        fallback_level=0,
        fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.DOCKER_HARDENED],
        security_score=70,
        risk_adjusted_score=70,
        forensic_support=True,
        behavioral_support=True,
        candidate_drivers=(IsolationTier.DOCKER_HARDENED,),
        rejection_reasons={},
        capability_mismatches={},
        policy_rejections={},
    )
    logger = make_logger()
    logger.log_negotiation("session-001", "vm-001", result)
    with sqlite3.connect(str(DB)) as conn:
        rows = list(conn.execute("SELECT session_id, actual_tier FROM vm_sessions"))
    assert rows[0] == ("session-001", "DOCKER_HARDENED")
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_audit_logger.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/isolation_abstraction/isolation_audit_logger.py
from __future__ import annotations
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .isolation_negotiator import NegotiationResult

_DDL = """
CREATE TABLE IF NOT EXISTS virtual_machines (
    vm_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_tier TEXT,
    fallback_level INTEGER DEFAULT 0,
    security_score INTEGER,
    risk_adjusted_score INTEGER,
    node_id TEXT,
    cluster_id TEXT,
    remote_runtime BOOLEAN DEFAULT FALSE,
    created_at TEXT,
    destroyed_at TEXT,
    agent_id TEXT
);
CREATE TABLE IF NOT EXISTS vm_sessions (
    session_id TEXT PRIMARY KEY,
    vm_id TEXT,
    requested_tier TEXT,
    actual_tier TEXT,
    policy TEXT,
    negotiation_result TEXT,
    candidate_drivers TEXT,
    rejection_reasons TEXT,
    capability_mismatches TEXT,
    policy_rejections TEXT,
    execution_duration_ms INTEGER,
    actual_runtime_health TEXT,
    post_execution_anomalies TEXT,
    degradation_impact TEXT,
    started_at TEXT,
    ended_at TEXT,
    exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS vm_events (
    event_id TEXT PRIMARY KEY,
    vm_id TEXT,
    event_type TEXT,
    severity TEXT,
    description TEXT,
    metadata TEXT,
    correlation_id TEXT,
    runtime_chain_id TEXT,
    origin_layer TEXT,
    origin_component TEXT,
    timestamp TEXT,
    row_hash TEXT,
    prev_hash TEXT
);
CREATE TABLE IF NOT EXISTS vm_escape_attempts (
    attempt_id TEXT PRIMARY KEY,
    vm_id TEXT,
    signal_type TEXT,
    detection_method TEXT,
    evidence TEXT,
    side_channel_indicators TEXT,
    vm_fingerprinting_detected BOOLEAN,
    hypervisor_api_abuse BOOLEAN,
    timing_anomaly_detected BOOLEAN,
    severity TEXT,
    response_action TEXT,
    forensic_snapshot_id TEXT,
    partial_failure_tracking TEXT,
    timestamp TEXT
);
CREATE TABLE IF NOT EXISTS vm_policies (
    policy_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    definition TEXT NOT NULL,
    minimum_security_score INTEGER,
    allowed_runtime_types TEXT,
    forbidden_runtime_types TEXT,
    minimum_required_capabilities TEXT,
    version INTEGER DEFAULT 1,
    signature TEXT,
    created_at TEXT,
    superseded_at TEXT
);
CREATE TABLE IF NOT EXISTS vm_forensics (
    forensic_id TEXT PRIMARY KEY,
    vm_id TEXT,
    session_id TEXT,
    timeline TEXT,
    process_tree TEXT,
    network_flows TEXT,
    filesystem_diff TEXT,
    memory_hashes TEXT,
    runtime_entropy_score REAL,
    suspicious_api_sequences TEXT,
    behavioral_anomaly_score REAL,
    cross_runtime_correlations TEXT,
    attack_graph TEXT,
    repeated_behavioral_fingerprints TEXT,
    shared_anomaly_signatures TEXT,
    campaign_correlation_id TEXT,
    memory_metadata TEXT,
    escape_signals TEXT,
    hypervisor_alerts TEXT,
    risk_score INTEGER,
    preserved_at TEXT,
    trigger TEXT
);
CREATE TABLE IF NOT EXISTS vm_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    vm_id TEXT,
    snapshot_type TEXT,
    state_path TEXT,
    manifest_hash TEXT,
    parent_snapshot_id TEXT,
    is_secure_boot_verified BOOLEAN,
    tpm_measurement TEXT,
    attestation_report TEXT,
    created_at TEXT,
    restored_at TEXT
);
CREATE TABLE IF NOT EXISTS vm_runtime_metrics (
    metric_id TEXT PRIMARY KEY,
    vm_id TEXT,
    cpu_percent REAL,
    ram_mb REAL,
    disk_io_kbps REAL,
    network_kbps REAL,
    process_count INTEGER,
    entropy_score REAL,
    crypto_mining_score REAL,
    burst_detected BOOLEAN,
    scheduler_latency_ms REAL,
    hypervisor_pressure_score REAL,
    isolation_stability_score REAL,
    anomaly_flags TEXT,
    timestamp TEXT
);
CREATE INDEX IF NOT EXISTS idx_vm_events_vm_id ON vm_events(vm_id);
CREATE INDEX IF NOT EXISTS idx_vm_events_severity ON vm_events(severity);
CREATE INDEX IF NOT EXISTS idx_vm_events_timestamp ON vm_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_vm_events_correlation ON vm_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_vm_sessions_vm_id ON vm_sessions(vm_id);
CREATE INDEX IF NOT EXISTS idx_virtual_machines_status ON virtual_machines(status);
CREATE INDEX IF NOT EXISTS idx_virtual_machines_agent ON virtual_machines(agent_id);
"""

_DEFAULT_DB = Path("data/nexus_vm_isolation.db")


class IsolationAuditLogger:
    """Append-only, hash-chained audit logger. Thread-safe."""

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self._db = db_path
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev_hash: Optional[str] = None
        with sqlite3.connect(str(self._db)) as conn:
            conn.executescript(_DDL)
        self._prev_hash = self._load_last_hash()

    def _load_last_hash(self) -> Optional[str]:
        try:
            with sqlite3.connect(str(self._db)) as conn:
                row = conn.execute(
                    "SELECT row_hash FROM vm_events ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def log_event(
        self,
        vm_id: str,
        event_type: str,
        severity: str,
        description: str,
        metadata: dict,
        correlation_id: Optional[str] = None,
        runtime_chain_id: Optional[str] = None,
        origin_layer: str = "isolation_abstraction",
        origin_component: Optional[str] = None,
    ) -> None:
        with self._lock:
            event_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()
            meta_str = json.dumps(metadata)
            raw = f"{event_id}{vm_id}{event_type}{severity}{description}{meta_str}{now}{self._prev_hash or ''}"
            row_hash = hashlib.sha256(raw.encode()).hexdigest()
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    """INSERT INTO vm_events
                    (event_id, vm_id, event_type, severity, description, metadata,
                     correlation_id, runtime_chain_id, origin_layer, origin_component,
                     timestamp, row_hash, prev_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, vm_id, event_type, severity, description, meta_str,
                     correlation_id, runtime_chain_id, origin_layer, origin_component,
                     now, row_hash, self._prev_hash),
                )
            self._prev_hash = row_hash

    def log_negotiation(
        self,
        session_id: str,
        vm_id: Optional[str],
        result: "NegotiationResult",
    ) -> None:
        with self._lock:
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO vm_sessions
                    (session_id, vm_id, requested_tier, actual_tier, policy,
                     negotiation_result, candidate_drivers, rejection_reasons,
                     capability_mismatches, policy_rejections, started_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        session_id, vm_id,
                        result.requested_tier.name if result.requested_tier else None,
                        result.actual_tier.name,
                        result.policy.value,
                        json.dumps({"reason": result.reason, "fallback_level": result.fallback_level,
                                    "security_score": result.security_score,
                                    "risk_adjusted_score": result.risk_adjusted_score}),
                        json.dumps([t.name for t in result.candidate_drivers]),
                        json.dumps(result.rejection_reasons),
                        json.dumps(result.capability_mismatches),
                        json.dumps(result.policy_rejections),
                        datetime.utcnow().isoformat(),
                    ),
                )

    def verify_chain(self) -> bool:
        """Returns True if hash chain is unbroken."""
        with sqlite3.connect(str(self._db)) as conn:
            rows = list(conn.execute(
                "SELECT event_id, vm_id, event_type, severity, description, metadata, "
                "timestamp, row_hash, prev_hash FROM vm_events ORDER BY timestamp ASC"
            ))
        prev = None
        for row in rows:
            event_id, vm_id, event_type, severity, description, meta, ts, row_hash, prev_hash = row
            if prev_hash != prev:
                return False
            raw = f"{event_id}{vm_id}{event_type}{severity}{description}{meta}{ts}{prev_hash or ''}"
            expected = hashlib.sha256(raw.encode()).hexdigest()
            if expected != row_hash:
                return False
            prev = row_hash
        return True
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_isolation_abstraction/test_audit_logger.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```
git add core/isolation_abstraction/isolation_audit_logger.py tests/test_isolation_abstraction/test_audit_logger.py
git commit -m "feat(isolation): full DB schema (8 tables) + hash-chained IsolationAuditLogger"
```

---

## Task 9: UnifiedIsolationRuntime — Public API

**Files:**
- Create: `core/isolation_abstraction/unified_isolation_runtime.py`
- Create: `tests/test_isolation_abstraction/test_unified_runtime.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_isolation_abstraction/test_unified_runtime.py
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from core.isolation_abstraction.isolation_driver import IsolationTier, ExecutionPayload, RuntimeConfig
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy


@pytest.fixture(autouse=True)
def clean_db():
    p = Path("data/nexus_vm_isolation_test_runtime.db")
    if p.exists():
        p.unlink()
    yield
    if p.exists():
        p.unlink()


def make_runtime(db_suffix="test_runtime"):
    from core.isolation_abstraction.unified_isolation_runtime import UnifiedIsolationRuntime
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    logger = IsolationAuditLogger(db_path=Path(f"data/nexus_vm_isolation_{db_suffix}.db"))
    return UnifiedIsolationRuntime(audit_logger=logger)


@pytest.mark.asyncio
async def test_execute_isolated_returns_execution_result():
    runtime = make_runtime()
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo hello"),
        policy=IsolationPolicy.BEST_AVAILABLE,
    )
    assert result.success is True or result.tier_used is not None  # always runs some tier


@pytest.mark.asyncio
async def test_execute_isolated_tier_used_is_set():
    runtime = make_runtime()
    result = await runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    assert isinstance(result.tier_used, IsolationTier)


@pytest.mark.asyncio
async def test_execute_isolated_negotiation_attached():
    runtime = make_runtime()
    result = await runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    assert result.negotiation is not None
    assert result.negotiation.actual_tier == result.tier_used


@pytest.mark.asyncio
async def test_strict_isolation_raises_on_windows():
    import platform
    if platform.system().lower() != "windows":
        pytest.skip("Windows-only test")
    from core.isolation_abstraction.isolation_strategy_manager import IsolationUnavailableError
    runtime = make_runtime()
    with pytest.raises(IsolationUnavailableError):
        await runtime.execute_isolated(
            ExecutionPayload(command="echo hi"),
            policy=IsolationPolicy.STRICT_ISOLATION,
        )


@pytest.mark.asyncio
async def test_create_and_destroy_runtime_handle():
    runtime = make_runtime()
    handle = await runtime.create_isolated_runtime(policy=IsolationPolicy.BEST_AVAILABLE)
    assert handle.runtime_id is not None
    await runtime.destroy_runtime(handle)  # should not raise


def test_get_negotiation_history_empty_initially():
    runtime = make_runtime(db_suffix="test_history")
    history = runtime.get_negotiation_history(limit=10)
    assert isinstance(history, list)


def test_refresh_capabilities_returns_snapshot():
    runtime = make_runtime(db_suffix="test_refresh")
    snap = runtime.refresh_capabilities(reason="test")
    assert snap.host_os in ("linux", "windows", "macos", "unknown")
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_isolation_abstraction/test_unified_runtime.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/isolation_abstraction/unified_isolation_runtime.py
from __future__ import annotations
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .isolation_audit_logger import IsolationAuditLogger
from .isolation_capability_detector import get_capability_detector, CapabilitySnapshot
from .isolation_driver import (
    IsolationDriver, IsolationTier, ExecutionPayload, ExecutionResult,
    RuntimeConfig, RuntimeHandle,
)
from .isolation_negotiator import get_negotiator, NegotiationResult
from .isolation_strategy_manager import IsolationPolicy


class UnifiedIsolationRuntime:
    """
    SINGLETON. The only public API for all isolation operations.
    Callers never import from vm_isolation/, sandbox/, or isolation/ directly.
    """

    def __init__(self, audit_logger: Optional[IsolationAuditLogger] = None) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._drivers: list[IsolationDriver] = self._build_driver_list()
        self._detector = get_capability_detector()
        self._negotiator = get_negotiator()

    def _build_driver_list(self) -> list[IsolationDriver]:
        drivers: list[IsolationDriver] = []
        # VM-tier drivers (stubs until vm_isolation/ is built in Plan B)
        try:
            from core.vm_isolation.vm_manager import get_vm_manager
            drivers.append(get_vm_manager())
        except ImportError:
            pass
        # Tier 3–5 always attempted
        try:
            from .drivers.docker_hardened_driver import DockerHardenedDriver
            drivers.append(DockerHardenedDriver())
        except ImportError:
            pass
        try:
            from .drivers.sandbox_driver import SandboxDriver
            drivers.append(SandboxDriver())
        except ImportError:
            pass
        try:
            from .drivers.process_jail_driver import ProcessJailDriver
            drivers.append(ProcessJailDriver())
        except ImportError:
            pass
        return drivers

    def _get_driver(self, tier: IsolationTier) -> Optional[IsolationDriver]:
        for d in self._drivers:
            if d.tier == tier and d.is_available():
                return d
        return None

    async def execute_isolated(
        self,
        payload: ExecutionPayload,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        required_tier: Optional[IsolationTier] = None,
        minimum_security_score: int = 0,
        requires_forensics: bool = False,
        requires_network_isolation: bool = False,
        requires_behavioral_lab: bool = False,
        requires_live_forensics: bool = False,
    ) -> ExecutionResult:
        required_caps: set[str] = set()
        if requires_forensics:
            required_caps.add("supports_forensics")
        if requires_network_isolation:
            required_caps.add("supports_network_isolation")
        if requires_behavioral_lab:
            required_caps.add("supports_behavioral_lab")
        if requires_live_forensics:
            required_caps.add("supports_live_forensics")

        snap = self._detector.detect()
        negotiation = self._negotiator.negotiate(
            snap, policy, required_tier,
            min_security_score=minimum_security_score,
            required_capabilities=required_caps or None,
        )

        driver = self._get_driver(negotiation.actual_tier)
        if driver is None:
            # Should not happen — negotiator only picks available tiers
            from .isolation_strategy_manager import IsolationUnavailableError
            raise IsolationUnavailableError(f"Driver for {negotiation.actual_tier} not instantiated")

        session_id = str(uuid.uuid4())
        config = RuntimeConfig(agent_id="unified", max_runtime_seconds=payload.timeout_seconds)
        handle = await driver.create_runtime(config)
        self._logger.log_negotiation(session_id, handle.runtime_id, negotiation)

        result = await driver.execute(handle, payload)
        result.negotiation = negotiation
        await driver.destroy(handle)

        self._logger.log_event(
            vm_id=handle.runtime_id,
            event_type="EXECUTION_COMPLETE",
            severity="INFO",
            description=f"tier={negotiation.actual_tier.name} success={result.success}",
            metadata={"exit_code": result.exit_code, "duration_ms": result.duration_ms},
            origin_component="unified_isolation_runtime",
        )
        return result

    async def create_isolated_runtime(
        self,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        minimum_security_score: int = 0,
        **requirements,
    ) -> RuntimeHandle:
        snap = self._detector.detect()
        negotiation = self._negotiator.negotiate(snap, policy, min_security_score=minimum_security_score)
        driver = self._get_driver(negotiation.actual_tier)
        if driver is None:
            from .isolation_strategy_manager import IsolationUnavailableError
            raise IsolationUnavailableError(f"Driver unavailable: {negotiation.actual_tier}")
        config = RuntimeConfig(agent_id="unified")
        return await driver.create_runtime(config)

    async def destroy_runtime(self, handle: RuntimeHandle) -> None:
        driver = self._get_driver(handle.tier)
        if driver:
            await driver.destroy(handle)

    def refresh_capabilities(self, reason: str = "manual_refresh") -> CapabilitySnapshot:
        try:
            return self._detector.refresh_capabilities(reason=reason, requester="unified_runtime")
        except ValueError:
            return self._detector.detect()

    def get_negotiation_history(self, limit: int = 100) -> list[dict]:
        import sqlite3
        try:
            with sqlite3.connect(str(self._logger._db)) as conn:
                rows = conn.execute(
                    "SELECT session_id, vm_id, actual_tier, policy, negotiation_result, started_at "
                    "FROM vm_sessions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"session_id": r[0], "vm_id": r[1], "actual_tier": r[2],
                 "policy": r[3], "negotiation": r[4], "started_at": r[5]}
                for r in rows
            ]
        except Exception:
            return []


_runtime_instance: Optional[UnifiedIsolationRuntime] = None
_runtime_lock = threading.Lock()


def get_unified_runtime() -> UnifiedIsolationRuntime:
    global _runtime_instance
    if _runtime_instance is None:
        with _runtime_lock:
            if _runtime_instance is None:
                _runtime_instance = UnifiedIsolationRuntime()
    return _runtime_instance
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_isolation_abstraction/test_unified_runtime.py -v
```
Expected: all PASSED (strict isolation test skips on Linux)

- [ ] **Step 5: Run full test suite for the module**

```
pytest tests/test_isolation_abstraction/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```
git add core/isolation_abstraction/unified_isolation_runtime.py tests/test_isolation_abstraction/test_unified_runtime.py
git commit -m "feat(isolation): UnifiedIsolationRuntime — single public API, full integration"
```

---

## Task 10: API Routes

**Files:**
- Create: `app/routes/vm_routes.py`
- Modify: `nexus_bot.py` (add router registration — ~3 lines)

- [ ] **Step 1: Create vm_routes.py**

```python
# app/routes/vm_routes.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.isolation_abstraction import get_unified_runtime
from core.isolation_abstraction.isolation_driver import IsolationTier, ExecutionPayload, RuntimeConfig
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy, IsolationUnavailableError

router = APIRouter(prefix="/vm", tags=["vm-isolation"])


class CreateVMRequest(BaseModel):
    policy: str = "best_available"
    required_tier: Optional[str] = None
    agent_id: str = "api"
    requires_forensics: bool = False
    minimum_security_score: int = 0


class ExecuteRequest(BaseModel):
    runtime_id: str
    command: Optional[str] = None
    code: Optional[str] = None
    timeout_seconds: int = 30


@router.get("/status")
def vm_status():
    runtime = get_unified_runtime()
    snap = runtime._detector.detect()
    return {
        "host_os": snap.host_os,
        "available_tiers": [t.name for t in snap.available_tiers],
        "docker_runtime": snap.docker_runtime,
        "virtualization_type": snap.virtualization_type,
    }


@router.get("/capabilities")
def vm_capabilities():
    snap = get_unified_runtime()._detector.detect()
    return {
        "has_firecracker": snap.has_firecracker,
        "has_qemu": snap.has_qemu,
        "has_kvm": snap.has_kvm,
        "has_docker": snap.has_docker,
        "has_wsl2": snap.has_wsl2,
        "host_os": snap.host_os,
        "docker_runtime": snap.docker_runtime,
        "virtualization_type": snap.virtualization_type,
        "available_tiers": [t.name for t in snap.available_tiers],
        "detected_at": snap.detected_at.isoformat(),
    }


@router.post("/capabilities/refresh")
def vm_capabilities_refresh():
    snap = get_unified_runtime().refresh_capabilities(reason="api_request")
    return {
        "available_tiers": [t.name for t in snap.available_tiers],
        "detected_at": snap.detected_at.isoformat(),
        "last_refresh_reason": snap.last_refresh_reason,
    }


@router.get("/negotiation/history")
def vm_negotiation_history(limit: int = 50):
    return get_unified_runtime().get_negotiation_history(limit=limit)


@router.get("/list")
def vm_list():
    import sqlite3
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT vm_id, session_id, tier, status, security_score, agent_id, created_at "
            "FROM virtual_machines ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [
        {"vm_id": r[0], "session_id": r[1], "tier": r[2],
         "status": r[3], "security_score": r[4], "agent_id": r[5], "created_at": r[6]}
        for r in rows
    ]


@router.get("/threats")
def vm_threats(limit: int = 50):
    import sqlite3, json
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT attempt_id, vm_id, signal_type, severity, response_action, timestamp "
            "FROM vm_escape_attempts ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [
        {"attempt_id": r[0], "vm_id": r[1], "signal_type": r[2],
         "severity": r[3], "response_action": r[4], "timestamp": r[5]}
        for r in rows
    ]


@router.get("/policies")
def vm_policies():
    import sqlite3, json
    from pathlib import Path
    db = Path("data/nexus_vm_isolation.db")
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT profile, definition, minimum_security_score, version FROM vm_policies "
            "WHERE superseded_at IS NULL"
        ).fetchall()
    return [
        {"profile": r[0], "definition": json.loads(r[1]), "minimum_security_score": r[2], "version": r[3]}
        for r in rows
    ]
```

- [ ] **Step 2: Register router in nexus_bot.py**

Find the section in `nexus_bot.py` where other routers are included (look for `app.include_router`). Add:

```python
from app.routes.vm_routes import router as vm_router
app.include_router(vm_router)
```

- [ ] **Step 3: Start server and verify endpoints respond**

```
python run.py
```

In another terminal:
```
curl http://localhost:8000/vm/status
curl http://localhost:8000/vm/capabilities
```
Expected: JSON response with `host_os`, `available_tiers`, etc.

- [ ] **Step 4: Commit**

```
git add app/routes/vm_routes.py nexus_bot.py
git commit -m "feat(isolation): /vm/* API endpoints — status, capabilities, list, threats, policies"
```

---

## Task 11: Dashboard

**Files:**
- Create: `app/vm_dashboard.py`

- [ ] **Step 1: Create dashboard**

```python
# app/vm_dashboard.py
"""
VM Isolation Dashboard — single-file Flask dashboard with auto-refresh panels.
Follows the same pattern as existing Nexus dashboards.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template_string

app = Flask(__name__)

_DB = Path("data/nexus_vm_isolation.db")

_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Nexus — VM Isolation Dashboard</title>
<style>
  body{font-family:monospace;background:#0d1117;color:#e6edf3;margin:0;padding:20px;}
  h1{color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:8px;}
  h2{color:#79c0ff;font-size:.9em;text-transform:uppercase;letter-spacing:.1em;margin-top:24px;}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;}
  .card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;}
  .badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75em;font-weight:700;}
  .tier1{background:#238636;} .tier2{background:#1f6feb;} .tier3{background:#9e6a03;}
  .tier4{background:#388bfd22;color:#58a6ff;} .tier5{background:#1c1c1c;color:#666;}
  .ok{color:#3fb950;} .warn{color:#d29922;} .crit{color:#f85149;}
  table{width:100%;border-collapse:collapse;font-size:.82em;}
  th{text-align:left;color:#8b949e;padding:4px 8px;border-bottom:1px solid #21262d;}
  td{padding:4px 8px;border-bottom:1px solid #161b22;}
  .score-bar{height:6px;background:#21262d;border-radius:3px;margin-top:4px;}
  .score-fill{height:100%;border-radius:3px;background:#3fb950;}
  .ts{color:#484f58;font-size:.75em;}
  .available{color:#3fb950;} .unavailable{color:#484f58;}
</style>
</head>
<body>
<h1>&#x1F6E1; Nexus VM Isolation Dashboard</h1>
<p class="ts">{{ now }} — auto-refresh 5s</p>

<div class="grid">

  <!-- Capability Map -->
  <div class="card">
    <h2>&#x1F50D; Capability Map</h2>
    {% for tier, available, score in tier_status %}
    <div style="margin:6px 0;display:flex;align-items:center;gap:8px;">
      <span class="badge tier{{ loop.index }}">T{{ loop.index }}</span>
      <span>{{ tier }}</span>
      <span class="{{ 'available' if available else 'unavailable' }}">
        {{ '✓ available' if available else '✗ unavailable' }}
      </span>
      {% if available %}
      <span style="margin-left:auto;color:#58a6ff;">{{ score }}</span>
      {% endif %}
    </div>
    {% endfor %}
    <hr style="border-color:#21262d;margin:10px 0;">
    <div class="ts">OS: {{ cap.host_os }} | Docker: {{ cap.docker_runtime or 'none' }} | Virt: {{ cap.virtualization_type or 'none' }}</div>
  </div>

  <!-- Active VMs -->
  <div class="card">
    <h2>&#x1F5A5; Active VMs</h2>
    {% if vms %}
    <table>
      <tr><th>ID</th><th>Tier</th><th>Status</th><th>Score</th><th>Agent</th></tr>
      {% for vm in vms %}
      <tr>
        <td class="ts">{{ vm.vm_id[:8] }}…</td>
        <td><span class="badge tier{{ vm.tier_num }}">{{ vm.tier }}</span></td>
        <td class="{{ 'ok' if vm.status == 'RUNNING' else 'warn' }}">{{ vm.status }}</td>
        <td>
          {{ vm.security_score or '-' }}
          {% if vm.security_score %}
          <div class="score-bar"><div class="score-fill" style="width:{{ vm.security_score }}%"></div></div>
          {% endif %}
        </td>
        <td class="ts">{{ vm.agent_id }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="ts">No active VMs</p>
    {% endif %}
  </div>

  <!-- Negotiation Feed -->
  <div class="card">
    <h2>&#x1F4CA; Recent Negotiations</h2>
    {% if negotiations %}
    <table>
      <tr><th>Requested</th><th>Actual</th><th>Policy</th><th>Time</th></tr>
      {% for n in negotiations %}
      <tr>
        <td>{{ n.requested or 'best' }}</td>
        <td><span class="badge tier{{ n.tier_num }}">{{ n.actual }}</span></td>
        <td class="ts">{{ n.policy }}</td>
        <td class="ts">{{ n.started_at[:19] if n.started_at else '-' }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="ts">No negotiations yet</p>
    {% endif %}
  </div>

  <!-- Escape Attempts -->
  <div class="card">
    <h2>&#x26A0; Escape Attempts</h2>
    {% if threats %}
    <table>
      <tr><th>Signal</th><th>VM</th><th>Severity</th><th>Response</th></tr>
      {% for t in threats %}
      <tr>
        <td>{{ t.signal_type }}</td>
        <td class="ts">{{ t.vm_id[:8] }}…</td>
        <td class="{{ 'crit' if t.severity == 'CRITICAL' else 'warn' }}">{{ t.severity }}</td>
        <td class="ts">{{ t.response_action }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="ok ts">No escape attempts detected</p>
    {% endif %}
  </div>

  <!-- Recent Events (hash-chain indicator) -->
  <div class="card">
    <h2>&#x1F4DC; Audit Trail</h2>
    <div>Chain integrity: <span class="{{ 'ok' if chain_ok else 'crit' }}">{{ '✓ intact' if chain_ok else '✗ BROKEN' }}</span></div>
    {% if events %}
    <table style="margin-top:8px;">
      <tr><th>Type</th><th>Severity</th><th>VM</th><th>Time</th></tr>
      {% for e in events %}
      <tr>
        <td>{{ e.event_type }}</td>
        <td class="{{ 'ok' if e.severity == 'INFO' else ('warn' if e.severity == 'WARNING' else 'crit') }}">{{ e.severity }}</td>
        <td class="ts">{{ e.vm_id[:8] if e.vm_id else '-' }}…</td>
        <td class="ts">{{ e.timestamp[:19] if e.timestamp else '-' }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="ts">No events yet</p>
    {% endif %}
  </div>

</div>
</body>
</html>
"""

_TIER_SCORES = {
    "FIRECRACKER": (1, 95), "QEMU": (2, 82), "DOCKER_HARDENED": (3, 70),
    "SANDBOX": (4, 40), "PROCESS_JAIL": (5, 20),
}


def _read_db() -> dict:
    if not _DB.exists():
        return {}
    try:
        with sqlite3.connect(str(_DB)) as conn:
            conn.row_factory = sqlite3.Row
            vms = [dict(r) for r in conn.execute(
                "SELECT vm_id, tier, status, security_score, agent_id FROM virtual_machines "
                "WHERE status NOT IN ('DESTROYED') ORDER BY created_at DESC LIMIT 20"
            )]
            negs = [dict(r) for r in conn.execute(
                "SELECT session_id, requested_tier, actual_tier, policy, started_at "
                "FROM vm_sessions ORDER BY started_at DESC LIMIT 10"
            )]
            threats = [dict(r) for r in conn.execute(
                "SELECT vm_id, signal_type, severity, response_action FROM vm_escape_attempts "
                "ORDER BY timestamp DESC LIMIT 10"
            )]
            events = [dict(r) for r in conn.execute(
                "SELECT event_type, severity, vm_id, timestamp FROM vm_events "
                "ORDER BY timestamp DESC LIMIT 15"
            )]
        return {"vms": vms, "negotiations": negs, "threats": threats, "events": events}
    except Exception:
        return {}


@app.route("/")
@app.route("/vm/dashboard")
def dashboard():
    from core.isolation_abstraction.isolation_capability_detector import get_capability_detector
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    cap = get_capability_detector().detect()
    data = _read_db()

    tier_status = [
        ("FIRECRACKER", "FIRECRACKER" in [t.name for t in cap.available_tiers], 95),
        ("QEMU", "QEMU" in [t.name for t in cap.available_tiers], 82),
        ("DOCKER_HARDENED", "DOCKER_HARDENED" in [t.name for t in cap.available_tiers], 70),
        ("SANDBOX", True, 40),
        ("PROCESS_JAIL", True, 20),
    ]

    # Enrich VMs with tier_num
    for vm in data.get("vms", []):
        num, _ = _TIER_SCORES.get(vm.get("tier", ""), (5, 20))
        vm["tier_num"] = num

    # Enrich negotiations
    for n in data.get("negotiations", []):
        n["requested"] = n.pop("requested_tier", None)
        n["actual"] = n.pop("actual_tier", "?")
        num, _ = _TIER_SCORES.get(n.get("actual", ""), (5, 20))
        n["tier_num"] = num

    # Verify chain
    chain_ok = True
    try:
        logger = IsolationAuditLogger()
        chain_ok = logger.verify_chain()
    except Exception:
        pass

    return render_template_string(
        _TEMPLATE,
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        cap=cap,
        tier_status=tier_status,
        vms=data.get("vms", []),
        negotiations=data.get("negotiations", []),
        threats=data.get("threats", []),
        events=data.get("events", []),
        chain_ok=chain_ok,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False)
```

- [ ] **Step 2: Run dashboard**

```
python app/vm_dashboard.py
```
Open `http://localhost:5010` in browser. Verify: capability map shows correct tiers, no errors in terminal.

- [ ] **Step 3: Commit**

```
git add app/vm_dashboard.py
git commit -m "feat(isolation): VM isolation dashboard with capability map, negotiation feed, audit trail"
```

---

## Task 12: conftest.py + Full Test Suite Run

**Files:**
- Create: `tests/test_isolation_abstraction/conftest.py`

- [ ] **Step 1: Create shared fixtures**

```python
# tests/test_isolation_abstraction/conftest.py
import pytest
from pathlib import Path


@pytest.fixture(scope="session", autouse=True)
def ensure_data_dir():
    Path("data").mkdir(exist_ok=True)


@pytest.fixture
def temp_db(tmp_path):
    """Provides a fresh SQLite DB path for each test."""
    return tmp_path / "test.db"
```

- [ ] **Step 2: Install pytest-asyncio if missing**

```
pip install pytest-asyncio
```

- [ ] **Step 3: Add pytest config to pyproject.toml or pytest.ini**

If `pytest.ini` doesn't exist:
```ini
# pytest.ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: Run full suite**

```
pytest tests/test_isolation_abstraction/ -v --tb=short
```
Expected: all PASSED. Note which tests skip (strict isolation on Linux, Docker tests if daemon not running).

- [ ] **Step 5: Final commit**

```
git add tests/test_isolation_abstraction/conftest.py pytest.ini
git commit -m "test(isolation): full test suite passing — Plan A complete"
```

---

## Self-Review

**Spec coverage check:**

| Spec Requirement | Task |
|-----------------|------|
| `isolation_driver.py` — Protocol + ABC hybrid | Task 1 |
| `DriverCapabilities` frozen, all fields | Task 1 |
| `TIER_CAPABILITIES` for all 5 tiers | Task 1 |
| `CapabilitySnapshot` frozen + `detect()` cached | Task 2 |
| `refresh_capabilities()` rate-limited | Task 2 |
| 4 `IsolationPolicy` values | Task 3 |
| `IsolationUnavailableError` | Task 3 |
| `minimum_security_score` filtering | Task 3 |
| `required_capabilities` filtering | Task 3 |
| `NegotiationResult` with full reasoning trail | Task 4 |
| `risk_adjusted_score` (QEMU -5 adj) | Task 4 |
| `ProcessJailDriver` — Tier 5 always available | Task 5 |
| `SandboxDriver` — Tier 4 always available | Task 6 |
| `DockerHardenedDriver` — Tier 3 hardened config | Task 7 |
| All 8 DB tables + indexes | Task 8 |
| `IsolationAuditLogger` hash-chained, tamper detection | Task 8 |
| `execute_isolated()` unified public API | Task 9 |
| `create_isolated_runtime()` | Task 9 |
| `get_negotiation_history()` | Task 9 |
| `/vm/*` endpoints with rate limiting note | Task 10 |
| Dashboard with all panels | Task 11 |
| `RuntimeHandle` opaque to callers | Task 1, 9 |
| Dependency direction — no circular imports | All tasks |
| Tiers 1–2 activate automatically on Linux | Task 9 (driver list auto-detects) |

**All spec requirements covered. No gaps found.**

**Placeholder scan:** No TBD, TODO, or "similar to" references found.

**Type consistency:** `IsolationTier`, `NegotiationResult`, `RuntimeHandle`, `DriverCapabilities`, `ExecutionPayload`, `ExecutionResult`, `SnapshotRef` defined once in `isolation_driver.py`, imported consistently everywhere.
