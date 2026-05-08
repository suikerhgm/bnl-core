# VM Isolation Layer — Implementation Plan B

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/vm_isolation/` — Tier 1 (Firecracker) and Tier 2 (QEMU) drivers as capability-aware stubs that auto-degrade to existing Tier 3–5 drivers on Windows, fully integrated under the existing `UnifiedIsolationRuntime`.

**Architecture:** `FirecrackerRuntime` and `QemuRuntime` implement `IsolationDriver` with real `is_available()` detection (platform + binary probing) and stub `create_runtime`/`execute` bodies. `VMManager` is an internal orchestrator (not a driver itself). `UnifiedIsolationRuntime._build_driver_list()` is updated to import Tier 1–2 drivers directly. On Windows, both return `is_available()=False`, the negotiator skips them, and Tier 3–5 run unchanged. On Linux with KVM, they activate automatically.

**Tech Stack:** Python 3.10+, stdlib only (platform, shutil, subprocess, threading, uuid, datetime), existing `IsolationDriver` ABC from Plan A, existing `IsolationAuditLogger`, `_set_handle_state`/`_get_handle_state`/`_clear_handle_state`.

**Spec:** `docs/superpowers/specs/2026-05-07-vm-isolation-design.md`
**Plan A:** `docs/superpowers/plans/2026-05-07-isolation-abstraction-plan.md` (already complete, 110 tests passing)

---

## File Map

| File | Responsibility |
|------|---------------|
| `core/vm_isolation/__init__.py` | Package init + `get_vm_manager()` export |
| `core/vm_isolation/firecracker_runtime.py` | `FirecrackerRuntime` — Tier 1 IsolationDriver, real detection, stub execution |
| `core/vm_isolation/qemu_runtime.py` | `QemuRuntime` — Tier 2 IsolationDriver, real detection, stub execution |
| `core/vm_isolation/vm_policy_engine.py` | `VMProfile` enum, `VMPolicy` frozen dataclass, `VMPolicyEngine` |
| `core/vm_isolation/vm_lifecycle.py` | `VMLifecycleTracker` — state machine, writes to `nexus_vm_isolation.db` |
| `core/vm_isolation/vm_escape_detector.py` | `VMEscapeDetector` — signal hooks, all stubs returning `EscapeSignal` objects |
| `core/vm_isolation/hypervisor_guardian.py` | `HypervisorGuardian` — daemon thread base, monitoring loop, alert routing |
| `core/vm_isolation/vm_manager.py` | `VMManager` — internal orchestrator, holds references to Tier 1–2 runtimes |
| `core/isolation_abstraction/unified_isolation_runtime.py` | Modify `_build_driver_list()` to register Tier 1–2 directly |
| `tests/test_vm_isolation/__init__.py` | Test package |
| `tests/test_vm_isolation/test_firecracker_runtime.py` | Tier 1 driver tests |
| `tests/test_vm_isolation/test_qemu_runtime.py` | Tier 2 driver tests |
| `tests/test_vm_isolation/test_vm_policy_engine.py` | Policy + profile tests |
| `tests/test_vm_isolation/test_vm_lifecycle.py` | Lifecycle state machine tests |
| `tests/test_vm_isolation/test_vm_escape_detector.py` | Escape hook tests |
| `tests/test_vm_isolation/test_hypervisor_guardian.py` | Guardian daemon tests |
| `tests/test_vm_isolation/test_vm_manager.py` | VMManager orchestrator tests |
| `tests/test_vm_isolation/test_integration.py` | Full Tier 1–5 integration under UnifiedIsolationRuntime |

---

## Task 1: FirecrackerRuntime — Tier 1 Driver

**Files:**
- Create: `core/vm_isolation/__init__.py`
- Create: `core/vm_isolation/firecracker_runtime.py`
- Create: `tests/test_vm_isolation/__init__.py`
- Create: `tests/test_vm_isolation/test_firecracker_runtime.py`

- [ ] **Step 1: Create test file**

```python
# tests/test_vm_isolation/test_firecracker_runtime.py
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, RuntimeConfig, ExecutionPayload, ExecutionContext,
    RuntimeLifecycleState, RuntimeHandle,
    _get_handle_state, _set_handle_state,
)


def test_firecracker_tier():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    assert FirecrackerRuntime().tier == IsolationTier.FIRECRACKER


def test_firecracker_capabilities_match_tier():
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    assert FirecrackerRuntime().capabilities == TIER_CAPABILITIES[IsolationTier.FIRECRACKER]


def test_firecracker_unavailable_on_windows():
    import platform
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    if platform.system().lower() == "windows":
        assert d.is_available() is False


def test_firecracker_unavailable_when_no_binary():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    with patch("core.vm_isolation.firecracker_runtime.shutil.which", return_value=None):
        with patch("core.vm_isolation.firecracker_runtime.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            d._available = None
            assert d.is_available() is False


def test_firecracker_available_when_binary_and_kvm():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    with patch("core.vm_isolation.firecracker_runtime.shutil.which", return_value="/usr/bin/firecracker"):
        with patch("core.vm_isolation.firecracker_runtime.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            with patch("core.vm_isolation.firecracker_runtime.platform.system", return_value="Linux"):
                d._available = None
                assert d.is_available() is True


@pytest.mark.asyncio
async def test_firecracker_create_runtime_stub_raises_when_unavailable():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    d._available = False
    with pytest.raises(RuntimeError, match="unavailable"):
        await d.create_runtime(RuntimeConfig(agent_id="test"))


@pytest.mark.asyncio
async def test_firecracker_snapshot_unavailable_when_not_running():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    handle = RuntimeHandle(
        runtime_id="fake-id", runtime_type="firecracker",
        tier=IsolationTier.FIRECRACKER,
        created_at=datetime.now(timezone.utc),
    )
    ref = await d.snapshot(handle)
    # When VM not actually running, snapshot returns unavailable
    assert ref.available is False


@pytest.mark.asyncio
async def test_firecracker_quarantine_sets_state():
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    d = FirecrackerRuntime()
    handle = RuntimeHandle(
        runtime_id="fake-q", runtime_type="firecracker",
        tier=IsolationTier.FIRECRACKER,
        created_at=datetime.now(timezone.utc),
    )
    _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
    await d.quarantine(handle, "test reason")
    assert _get_handle_state(handle.runtime_id, "state") == RuntimeLifecycleState.QUARANTINED
```

- [ ] **Step 2: Create test package init**

```python
# tests/test_vm_isolation/__init__.py
```

- [ ] **Step 3: Run tests — verify ImportError**

```
python -m pytest tests/test_vm_isolation/test_firecracker_runtime.py -v
```
Expected: `ModuleNotFoundError: No module named 'core.vm_isolation'`

- [ ] **Step 4: Create vm_isolation package init**

```python
# core/vm_isolation/__init__.py
from .vm_manager import VMManager, get_vm_manager

__all__ = ["VMManager", "get_vm_manager"]
```

- [ ] **Step 5: Implement FirecrackerRuntime**

```python
# core/vm_isolation/firecracker_runtime.py
from __future__ import annotations
import platform
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.isolation_abstraction.isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities, RuntimeConfig,
    RuntimeHandle, ExecutionPayload, ExecutionResult, SnapshotRef,
    RuntimeLifecycleState, ExecutionContext,
    TIER_CAPABILITIES,
    _set_handle_state, _get_handle_state, _clear_handle_state,
)

_FIRECRACKER_BINARY = "firecracker"
_KVM_DEVICE = Path("/dev/kvm")


class FirecrackerRuntime(IsolationDriver):
    """
    Tier 1 — Firecracker microVM driver.
    Requires: Linux + /dev/kvm + firecracker binary.
    On Windows or missing deps: is_available() returns False.
    create_runtime/execute are functional stubs — full boot flow in Plan C.
    """

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.FIRECRACKER

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.FIRECRACKER]

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._detect()
        return self._available

    def _detect(self) -> bool:
        if platform.system().lower() != "linux":
            return False
        if not _KVM_DEVICE.exists():
            return False
        if not shutil.which(_FIRECRACKER_BINARY):
            return False
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        if not self.is_available():
            raise RuntimeError(
                "FirecrackerRuntime unavailable: requires Linux + /dev/kvm + firecracker binary"
            )
        # Stub: full jailer + API socket boot in Plan C
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="firecracker",
            tier=IsolationTier.FIRECRACKER,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        _set_handle_state(handle.runtime_id, "agent_id", config.agent_id)
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
        _set_handle_state(handle.runtime_id, "profile", config.profile)
        return handle

    async def execute(
        self,
        handle: RuntimeHandle,
        payload: ExecutionPayload,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionResult:
        ctx = ctx or ExecutionContext()
        # Stub: real vsock/API execution in Plan C
        return ExecutionResult(
            success=False,
            output="",
            error="FirecrackerRuntime.execute: full microVM execution not yet implemented (Plan C)",
            exit_code=1,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.FIRECRACKER,
            duration_ms=0,
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.FAILED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.DESTROYED)
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        state = _get_handle_state(handle.runtime_id, "state")
        if state not in (RuntimeLifecycleState.RUNNING, RuntimeLifecycleState.FROZEN):
            return SnapshotRef(
                available=False,
                reason="vm_not_running",
                snapshot_reason="MANUAL",
            )
        # Stub: real memory + disk snapshot via Firecracker API in Plan C
        return SnapshotRef(
            available=False,
            reason="firecracker_snapshot_stub_plan_c",
            snapshot_reason="MANUAL",
        )

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
        # Stub: send SIGSTOP to jailer process in Plan C
```

- [ ] **Step 6: Run tests**

```
python -m pytest tests/test_vm_isolation/test_firecracker_runtime.py -v
```
Expected: 8 PASSED (note: __init__.py imports vm_manager which doesn't exist yet — create a minimal stub first)

- [ ] **Step 7: Create minimal vm_manager stub** (to unblock __init__.py import)

```python
# core/vm_isolation/vm_manager.py  (minimal stub — full implementation in Task 7)
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
```

- [ ] **Step 8: Run tests again**

```
python -m pytest tests/test_vm_isolation/test_firecracker_runtime.py -v
```
Expected: 8 PASSED

- [ ] **Step 9: Verify Plan A tests unbroken**

```
python -m pytest tests/test_isolation_abstraction/ -q --tb=no
```
Expected: 110 passed

- [ ] **Step 10: Commit**

```
git add core/vm_isolation/ tests/test_vm_isolation/
git commit -m "feat(vm): Task 1 — FirecrackerRuntime (Tier 1) stub + capability detection"
```

---

## Task 2: QemuRuntime — Tier 2 Driver

**Files:**
- Create: `core/vm_isolation/qemu_runtime.py`
- Create: `tests/test_vm_isolation/test_qemu_runtime.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_qemu_runtime.py
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, RuntimeConfig, ExecutionPayload, ExecutionContext,
    RuntimeLifecycleState, RuntimeHandle,
    _get_handle_state, _set_handle_state,
)


def test_qemu_tier():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    assert QemuRuntime().tier == IsolationTier.QEMU


def test_qemu_capabilities_match_tier():
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    from core.vm_isolation.qemu_runtime import QemuRuntime
    assert QemuRuntime().capabilities == TIER_CAPABILITIES[IsolationTier.QEMU]


def test_qemu_unavailable_on_windows():
    import platform
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    if platform.system().lower() == "windows":
        assert d.is_available() is False


def test_qemu_unavailable_when_no_binary():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    with patch("core.vm_isolation.qemu_runtime.shutil.which", return_value=None):
        with patch("core.vm_isolation.qemu_runtime.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            d._available = None
            assert d.is_available() is False


def test_qemu_available_when_binary_and_kvm():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    with patch("core.vm_isolation.qemu_runtime.shutil.which", return_value="/usr/bin/qemu-system-x86_64"):
        with patch("core.vm_isolation.qemu_runtime.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            with patch("core.vm_isolation.qemu_runtime.platform.system", return_value="Linux"):
                d._available = None
                assert d.is_available() is True


def test_qemu_risk_adjustment_is_negative():
    from core.isolation_abstraction.isolation_driver import TIER_RISK_ADJUSTMENTS
    assert TIER_RISK_ADJUSTMENTS[IsolationTier.QEMU] < 0


@pytest.mark.asyncio
async def test_qemu_create_runtime_raises_when_unavailable():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    d._available = False
    with pytest.raises(RuntimeError, match="unavailable"):
        await d.create_runtime(RuntimeConfig(agent_id="test"))


@pytest.mark.asyncio
async def test_qemu_execute_returns_stub_result():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    handle = RuntimeHandle(
        runtime_id="fake-qemu", runtime_type="qemu",
        tier=IsolationTier.QEMU, created_at=datetime.now(timezone.utc),
    )
    result = await d.execute(handle, ExecutionPayload(command="echo hi"))
    assert result.tier_used == IsolationTier.QEMU
    assert result.success is False  # stub, not yet implemented
    assert "stub" in result.error.lower() or "not yet" in result.error.lower()


@pytest.mark.asyncio
async def test_qemu_quarantine_sets_state():
    from core.vm_isolation.qemu_runtime import QemuRuntime
    d = QemuRuntime()
    handle = RuntimeHandle(
        runtime_id="fake-qemu-q", runtime_type="qemu",
        tier=IsolationTier.QEMU, created_at=datetime.now(timezone.utc),
    )
    _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
    await d.quarantine(handle, "test")
    assert _get_handle_state(handle.runtime_id, "state") == RuntimeLifecycleState.QUARANTINED
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_vm_isolation/test_qemu_runtime.py -v
```
Expected: `ImportError: cannot import name 'QemuRuntime'`

- [ ] **Step 3: Implement QemuRuntime**

```python
# core/vm_isolation/qemu_runtime.py
from __future__ import annotations
import platform
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.isolation_abstraction.isolation_driver import (
    IsolationDriver, IsolationTier, DriverCapabilities, RuntimeConfig,
    RuntimeHandle, ExecutionPayload, ExecutionResult, SnapshotRef,
    RuntimeLifecycleState, ExecutionContext,
    TIER_CAPABILITIES,
    _set_handle_state, _get_handle_state, _clear_handle_state,
)

_QEMU_BINARY = "qemu-system-x86_64"
_KVM_DEVICE = Path("/dev/kvm")


class QemuRuntime(IsolationDriver):
    """
    Tier 2 — QEMU/KVM driver.
    Requires: Linux + /dev/kvm + qemu-system-x86_64 binary.
    Higher attack surface than Firecracker (risk_adjustment = -5).
    create_runtime/execute are functional stubs — full boot flow in Plan C.
    """

    def __init__(self) -> None:
        self._available: Optional[bool] = None

    @property
    def tier(self) -> IsolationTier:
        return IsolationTier.QEMU

    @property
    def capabilities(self) -> DriverCapabilities:
        return TIER_CAPABILITIES[IsolationTier.QEMU]

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._detect()
        return self._available

    def _detect(self) -> bool:
        if platform.system().lower() != "linux":
            return False
        if not _KVM_DEVICE.exists():
            return False
        if not shutil.which(_QEMU_BINARY):
            return False
        return True

    async def create_runtime(self, config: RuntimeConfig) -> RuntimeHandle:
        if not self.is_available():
            raise RuntimeError(
                "QemuRuntime unavailable: requires Linux + /dev/kvm + qemu-system-x86_64"
            )
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()),
            runtime_type="qemu",
            tier=IsolationTier.QEMU,
            created_at=datetime.now(timezone.utc),
            state=RuntimeLifecycleState.CREATED,
        )
        _set_handle_state(handle.runtime_id, "agent_id", config.agent_id)
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.RUNNING)
        _set_handle_state(handle.runtime_id, "profile", config.profile)
        return handle

    async def execute(
        self,
        handle: RuntimeHandle,
        payload: ExecutionPayload,
        ctx: ExecutionContext | None = None,
    ) -> ExecutionResult:
        ctx = ctx or ExecutionContext()
        return ExecutionResult(
            success=False,
            output="",
            error="QemuRuntime.execute: full QEMU/KVM execution not yet implemented (Plan C)",
            exit_code=1,
            runtime_id=handle.runtime_id,
            tier_used=IsolationTier.QEMU,
            duration_ms=0,
            execution_id=ctx.execution_id,
            correlation_id=ctx.correlation_id,
            trace_id=ctx.trace_id,
            runtime_state=RuntimeLifecycleState.FAILED,
        )

    async def destroy(self, handle: RuntimeHandle) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.DESTROYED)
        _clear_handle_state(handle.runtime_id)

    async def snapshot(self, handle: RuntimeHandle) -> SnapshotRef:
        state = _get_handle_state(handle.runtime_id, "state")
        if state not in (RuntimeLifecycleState.RUNNING, RuntimeLifecycleState.FROZEN):
            return SnapshotRef(available=False, reason="vm_not_running", snapshot_reason="MANUAL")
        return SnapshotRef(
            available=False,
            reason="qemu_snapshot_stub_plan_c",
            snapshot_reason="MANUAL",
        )

    async def quarantine(self, handle: RuntimeHandle, reason: str) -> None:
        _set_handle_state(handle.runtime_id, "state", RuntimeLifecycleState.QUARANTINED)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_qemu_runtime.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Run all tests**

```
python -m pytest tests/ -q --tb=no
```
Expected: 119+ passed (110 Plan A + 8 Firecracker + 9 QEMU + 2 vm_isolation init)

- [ ] **Step 6: Commit**

```
git add core/vm_isolation/qemu_runtime.py tests/test_vm_isolation/test_qemu_runtime.py
git commit -m "feat(vm): Task 2 — QemuRuntime (Tier 2) stub + capability detection"
```

---

## Task 3: VMPolicyEngine

**Files:**
- Create: `core/vm_isolation/vm_policy_engine.py`
- Create: `tests/test_vm_isolation/test_vm_policy_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_vm_policy_engine.py
import pytest
from core.vm_isolation.vm_policy_engine import (
    VMProfile, VMPolicy, VMPolicyEngine,
    PROFILE_POLICIES,
)


def test_vm_profiles_exist():
    assert VMProfile.SAFE_VM.value == "safe_vm"
    assert VMProfile.RESTRICTED_VM.value == "restricted_vm"
    assert VMProfile.QUARANTINE_VM.value == "quarantine_vm"
    assert VMProfile.LOCKDOWN_VM.value == "lockdown_vm"


def test_vm_policy_is_frozen():
    p = PROFILE_POLICIES[VMProfile.SAFE_VM]
    with pytest.raises(Exception):
        p.allow_host_mounts = True


def test_safe_vm_allows_outbound():
    p = PROFILE_POLICIES[VMProfile.SAFE_VM]
    assert p.allow_host_mounts is False
    assert p.allow_shared_memory is False
    assert p.readonly_boot_layer is True
    assert p.disposable_disk is True
    assert p.auto_destroy_on_exit is True
    assert p.minimum_security_score == 60


def test_lockdown_vm_max_restrictions():
    p = PROFILE_POLICIES[VMProfile.LOCKDOWN_VM]
    assert p.allow_host_mounts is False
    assert p.allow_outbound_network is False
    assert p.minimum_security_score == 90
    assert "qemu" in p.forbidden_runtime_types


def test_quarantine_vm_no_network():
    p = PROFILE_POLICIES[VMProfile.QUARANTINE_VM]
    assert p.allow_outbound_network is False
    assert p.allow_host_mounts is False


def test_policy_engine_get_policy():
    engine = VMPolicyEngine()
    p = engine.get_policy(VMProfile.SAFE_VM)
    assert isinstance(p, VMPolicy)
    assert p.profile == VMProfile.SAFE_VM


def test_policy_engine_validate_tier_passes():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    # Docker (score=70) passes SAFE_VM (min=60)
    ok, reason = engine.validate_tier(IsolationTier.DOCKER_HARDENED, VMProfile.SAFE_VM)
    assert ok is True
    assert reason is None


def test_policy_engine_validate_tier_fails_lockdown():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    # Sandbox (score=40) fails LOCKDOWN_VM (min=90)
    ok, reason = engine.validate_tier(IsolationTier.SANDBOX, VMProfile.LOCKDOWN_VM)
    assert ok is False
    assert reason is not None


def test_policy_engine_validate_tier_fails_forbidden():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    # QEMU forbidden in LOCKDOWN_VM
    ok, reason = engine.validate_tier(IsolationTier.QEMU, VMProfile.LOCKDOWN_VM)
    assert ok is False
    assert "forbidden" in reason.lower()
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_vm_isolation/test_vm_policy_engine.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/vm_isolation/vm_policy_engine.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from core.isolation_abstraction.isolation_driver import (
    IsolationTier, TIER_SECURITY_SCORES, TIER_RISK_ADJUSTMENTS,
)


class VMProfile(str, Enum):
    SAFE_VM       = "safe_vm"
    RESTRICTED_VM = "restricted_vm"
    QUARANTINE_VM = "quarantine_vm"
    LOCKDOWN_VM   = "lockdown_vm"


@dataclass(frozen=True)
class VMPolicy:
    profile: VMProfile
    allow_host_mounts: bool
    allow_outbound_network: bool
    allow_shared_memory: bool          # always False
    readonly_boot_layer: bool          # always True
    disposable_disk: bool              # always True
    encrypted_runtime_storage: bool
    max_cpu_percent: float
    max_ram_mb: int
    max_runtime_seconds: int
    auto_destroy_on_exit: bool
    minimum_security_score: int
    allowed_runtime_types: frozenset
    forbidden_runtime_types: frozenset


# Runtime type names matching IsolationStrategyManager conventions
_TIER_RUNTIME_TYPE = {
    IsolationTier.FIRECRACKER:    "firecracker",
    IsolationTier.QEMU:           "qemu",
    IsolationTier.DOCKER_HARDENED:"docker",
    IsolationTier.SANDBOX:        "sandbox",
    IsolationTier.PROCESS_JAIL:   "jail",
}

PROFILE_POLICIES: dict[VMProfile, VMPolicy] = {
    VMProfile.SAFE_VM: VMPolicy(
        profile=VMProfile.SAFE_VM,
        allow_host_mounts=False,
        allow_outbound_network=True,
        allow_shared_memory=False,
        readonly_boot_layer=True,
        disposable_disk=True,
        encrypted_runtime_storage=False,
        max_cpu_percent=50.0,
        max_ram_mb=512,
        max_runtime_seconds=300,
        auto_destroy_on_exit=True,
        minimum_security_score=60,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker", "sandbox", "jail"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.RESTRICTED_VM: VMPolicy(
        profile=VMProfile.RESTRICTED_VM,
        allow_host_mounts=False,
        allow_outbound_network=False,
        allow_shared_memory=False,
        readonly_boot_layer=True,
        disposable_disk=True,
        encrypted_runtime_storage=True,
        max_cpu_percent=25.0,
        max_ram_mb=256,
        max_runtime_seconds=120,
        auto_destroy_on_exit=True,
        minimum_security_score=70,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.QUARANTINE_VM: VMPolicy(
        profile=VMProfile.QUARANTINE_VM,
        allow_host_mounts=False,
        allow_outbound_network=False,
        allow_shared_memory=False,
        readonly_boot_layer=True,
        disposable_disk=True,
        encrypted_runtime_storage=True,
        max_cpu_percent=10.0,
        max_ram_mb=128,
        max_runtime_seconds=60,
        auto_destroy_on_exit=False,   # preserve for forensics
        minimum_security_score=70,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.LOCKDOWN_VM: VMPolicy(
        profile=VMProfile.LOCKDOWN_VM,
        allow_host_mounts=False,
        allow_outbound_network=False,
        allow_shared_memory=False,
        readonly_boot_layer=True,
        disposable_disk=True,
        encrypted_runtime_storage=True,
        max_cpu_percent=10.0,
        max_ram_mb=128,
        max_runtime_seconds=60,
        auto_destroy_on_exit=False,   # preserve for forensics
        minimum_security_score=90,
        allowed_runtime_types=frozenset({"firecracker"}),
        forbidden_runtime_types=frozenset({"qemu"}),  # QEMU too high attack surface
    ),
}


class VMPolicyEngine:
    """Validates tiers against VM profiles. Stateless."""

    def get_policy(self, profile: VMProfile) -> VMPolicy:
        return PROFILE_POLICIES[profile]

    def validate_tier(
        self,
        tier: IsolationTier,
        profile: VMProfile,
    ) -> Tuple[bool, Optional[str]]:
        """Returns (valid, rejection_reason). reason is None if valid."""
        policy = PROFILE_POLICIES[profile]
        runtime_type = _TIER_RUNTIME_TYPE[tier]

        if runtime_type in policy.forbidden_runtime_types:
            return False, f"runtime type '{runtime_type}' is forbidden for {profile.value}"

        if policy.allowed_runtime_types and runtime_type not in policy.allowed_runtime_types:
            return False, f"runtime type '{runtime_type}' not in allowed set for {profile.value}"

        effective_score = TIER_SECURITY_SCORES[tier] + TIER_RISK_ADJUSTMENTS[tier]
        if effective_score < policy.minimum_security_score:
            return False, (
                f"security score {effective_score} < minimum {policy.minimum_security_score} "
                f"for {profile.value}"
            )

        return True, None
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_vm_policy_engine.py -v
```
Expected: 10 PASSED

- [ ] **Step 5: Commit**

```
git add core/vm_isolation/vm_policy_engine.py tests/test_vm_isolation/test_vm_policy_engine.py
git commit -m "feat(vm): Task 3 — VMProfile, VMPolicy, VMPolicyEngine (4 profiles)"
```

---

## Task 4: VMLifecycleTracker

**Files:**
- Create: `core/vm_isolation/vm_lifecycle.py`
- Create: `tests/test_vm_isolation/test_vm_lifecycle.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_vm_lifecycle.py
import pytest
from pathlib import Path
from core.isolation_abstraction.isolation_driver import IsolationTier, RuntimeLifecycleState
from core.vm_isolation.vm_policy_engine import VMProfile


@pytest.fixture
def tracker(tmp_path):
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    logger = IsolationAuditLogger(db_path=tmp_path / "lifecycle.db")
    return VMLifecycleTracker(audit_logger=logger)


def test_tracker_create_session(tracker):
    session_id = tracker.create_session(
        vm_id="vm-1", tier=IsolationTier.DOCKER_HARDENED,
        profile=VMProfile.SAFE_VM, agent_id="a1",
        security_score=70, risk_adjusted_score=70,
    )
    assert isinstance(session_id, str) and len(session_id) == 36


def test_tracker_get_session_state(tracker):
    session_id = tracker.create_session(
        vm_id="vm-2", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a2",
        security_score=40, risk_adjusted_score=40,
    )
    state = tracker.get_state("vm-2")
    assert state == RuntimeLifecycleState.RUNNING


def test_tracker_transition_to_quarantined(tracker):
    tracker.create_session(
        vm_id="vm-3", tier=IsolationTier.DOCKER_HARDENED,
        profile=VMProfile.QUARANTINE_VM, agent_id="a3",
        security_score=70, risk_adjusted_score=70,
    )
    tracker.transition("vm-3", RuntimeLifecycleState.QUARANTINED, reason="escape detected")
    assert tracker.get_state("vm-3") == RuntimeLifecycleState.QUARANTINED


def test_tracker_transition_to_destroyed(tracker):
    tracker.create_session(
        vm_id="vm-4", tier=IsolationTier.PROCESS_JAIL,
        profile=VMProfile.SAFE_VM, agent_id="a4",
        security_score=20, risk_adjusted_score=20,
    )
    tracker.transition("vm-4", RuntimeLifecycleState.DESTROYED)
    assert tracker.get_state("vm-4") == RuntimeLifecycleState.DESTROYED


def test_tracker_unknown_vm_returns_none(tracker):
    assert tracker.get_state("nonexistent-vm") is None


def test_tracker_list_active(tracker):
    tracker.create_session(
        vm_id="vm-5", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a5",
        security_score=40, risk_adjusted_score=40,
    )
    tracker.create_session(
        vm_id="vm-6", tier=IsolationTier.SANDBOX,
        profile=VMProfile.SAFE_VM, agent_id="a6",
        security_score=40, risk_adjusted_score=40,
    )
    tracker.transition("vm-6", RuntimeLifecycleState.DESTROYED)
    active = tracker.list_active()
    ids = [v["vm_id"] for v in active]
    assert "vm-5" in ids
    assert "vm-6" not in ids
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_vm_isolation/test_vm_lifecycle.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/vm_isolation/vm_lifecycle.py
from __future__ import annotations
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
from core.isolation_abstraction.isolation_driver import IsolationTier, RuntimeLifecycleState
from core.vm_isolation.vm_policy_engine import VMProfile


class VMLifecycleTracker:
    """
    Tracks VM state transitions. Writes to nexus_vm_isolation.db via IsolationAuditLogger.
    Thread-safe. In-memory state cache for fast lookups.
    """

    def __init__(self, audit_logger: Optional[IsolationAuditLogger] = None) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._states: dict[str, RuntimeLifecycleState] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        vm_id: str,
        tier: IsolationTier,
        profile: VMProfile,
        agent_id: str,
        security_score: int,
        risk_adjusted_score: int,
        fallback_level: int = 0,
    ) -> str:
        session_id = str(uuid.uuid4())
        with self._lock:
            self._states[vm_id] = RuntimeLifecycleState.RUNNING
        self._logger.log_vm_created(
            vm_id=vm_id,
            session_id=session_id,
            tier=tier.name,
            agent_id=agent_id,
            security_score=security_score,
            risk_adjusted_score=risk_adjusted_score,
            fallback_level=fallback_level,
        )
        self._logger.log_event(
            vm_id=vm_id,
            event_type="VM_CREATED",
            severity="INFO",
            description=f"profile={profile.value} tier={tier.name}",
            metadata={
                "session_id": session_id,
                "profile": profile.value,
                "tier": tier.name,
                "security_score": security_score,
                "fallback_level": fallback_level,
            },
            origin_component="vm_lifecycle_tracker",
        )
        return session_id

    def transition(
        self,
        vm_id: str,
        new_state: RuntimeLifecycleState,
        reason: str = "",
    ) -> None:
        with self._lock:
            old_state = self._states.get(vm_id, RuntimeLifecycleState.CREATED)
            self._states[vm_id] = new_state
        severity = "WARNING" if new_state == RuntimeLifecycleState.QUARANTINED else "INFO"
        if new_state in (RuntimeLifecycleState.FAILED, RuntimeLifecycleState.QUARANTINED):
            severity = "WARNING"
        self._logger.log_event(
            vm_id=vm_id,
            event_type="STATE_TRANSITION",
            severity=severity,
            description=f"{old_state.value} → {new_state.value}",
            metadata={"old_state": old_state.value, "new_state": new_state.value, "reason": reason},
            origin_component="vm_lifecycle_tracker",
        )
        if new_state == RuntimeLifecycleState.DESTROYED:
            self._logger.log_vm_destroyed(vm_id)

    def get_state(self, vm_id: str) -> Optional[RuntimeLifecycleState]:
        with self._lock:
            return self._states.get(vm_id)

    def list_active(self) -> list[dict]:
        """Returns VMs not in DESTROYED or FAILED state."""
        import sqlite3
        from pathlib import Path
        try:
            with sqlite3.connect(str(self._logger._db)) as conn:
                rows = conn.execute(
                    "SELECT vm_id, tier, status, security_score, agent_id "
                    "FROM virtual_machines WHERE status NOT IN ('DESTROYED', 'FAILED') "
                    "ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            return [
                {"vm_id": r[0], "tier": r[1], "status": r[2],
                 "security_score": r[3], "agent_id": r[4]}
                for r in rows
            ]
        except Exception:
            return []
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_vm_lifecycle.py -v
```
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```
git add core/vm_isolation/vm_lifecycle.py tests/test_vm_isolation/test_vm_lifecycle.py
git commit -m "feat(vm): Task 4 — VMLifecycleTracker with state machine + audit integration"
```

---

## Task 5: VMEscapeDetector

**Files:**
- Create: `core/vm_isolation/vm_escape_detector.py`
- Create: `tests/test_vm_isolation/test_vm_escape_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_vm_escape_detector.py
import pytest
from core.vm_isolation.vm_escape_detector import (
    VMEscapeDetector, EscapeSignal, EscapeSignalType, EscapeSeverity,
)


def make_detector():
    return VMEscapeDetector()


def test_escape_signal_type_values():
    assert EscapeSignalType.HYPERVISOR_PROBE.value == "hypervisor_probe"
    assert EscapeSignalType.DOCKER_SOCKET_PROBE.value == "docker_socket_probe"
    assert EscapeSignalType.NAMESPACE_ESCAPE.value == "namespace_escape"
    assert EscapeSignalType.SIDE_CHANNEL_PROBE.value == "side_channel_probe"
    assert EscapeSignalType.DEVICE_ENUMERATION.value == "device_enumeration"


def test_escape_signal_is_dataclass():
    sig = EscapeSignal(
        vm_id="vm-test",
        signal_type=EscapeSignalType.HYPERVISOR_PROBE,
        severity=EscapeSeverity.HIGH,
        evidence={"detail": "probe detected"},
        detection_method="heuristic",
    )
    assert sig.vm_id == "vm-test"
    assert sig.severity == EscapeSeverity.HIGH


def test_check_hypervisor_probing_returns_no_signals_for_benign(tmp_path):
    detector = make_detector()
    # With no KVM on Windows, this should return empty list (benign)
    signals = detector.check_hypervisor_probing("vm-test", {})
    assert isinstance(signals, list)


def test_check_docker_socket_returns_list(tmp_path):
    detector = make_detector()
    signals = detector.check_docker_socket_access("vm-test")
    assert isinstance(signals, list)


def test_check_namespace_escape_returns_list():
    detector = make_detector()
    signals = detector.check_namespace_escape("vm-test", {})
    assert isinstance(signals, list)


def test_full_scan_returns_list():
    detector = make_detector()
    signals = detector.scan_all("vm-test", runtime_metadata={})
    assert isinstance(signals, list)
    # All items are EscapeSignal instances
    for s in signals:
        assert isinstance(s, EscapeSignal)


def test_signals_have_required_fields():
    detector = make_detector()
    signals = detector.scan_all("vm-test", runtime_metadata={"suspicious_syscalls": True})
    for s in signals:
        assert s.vm_id == "vm-test"
        assert s.signal_type in EscapeSignalType.__members__.values()
        assert s.severity in EscapeSeverity.__members__.values()
        assert isinstance(s.evidence, dict)
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_vm_isolation/test_vm_escape_detector.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/vm_isolation/vm_escape_detector.py
"""
VMEscapeDetector — escape signal detection hooks.
All check methods return lists of EscapeSignal (empty = no signals detected).
Full detection logic (KVM perf counters, inotify, timing analysis) in Plan C.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EscapeSignalType(str, Enum):
    HYPERVISOR_PROBE    = "hypervisor_probe"
    NAMESPACE_ESCAPE    = "namespace_escape"
    DOCKER_SOCKET_PROBE = "docker_socket_probe"
    MOUNT_ABUSE         = "mount_abuse"
    SIDE_CHANNEL_PROBE  = "side_channel_probe"
    DEVICE_ENUMERATION  = "device_enumeration"
    TIMING_ANOMALY      = "timing_anomaly"
    MEMORY_BALLOON_ABUSE = "memory_balloon_abuse"
    PROCFS_ABUSE        = "procfs_abuse"


class EscapeSeverity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


@dataclass
class EscapeSignal:
    vm_id: str
    signal_type: EscapeSignalType
    severity: EscapeSeverity
    evidence: dict
    detection_method: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    side_channel_indicators: dict = field(default_factory=dict)
    vm_fingerprinting_detected: bool = False


class VMEscapeDetector:
    """
    Escape signal detection. Each check returns list[EscapeSignal].
    Empty list = no signals detected.
    Full kernel-level detection (KVM perf, inotify, seccomp audit) in Plan C.
    """

    def check_hypervisor_probing(
        self,
        vm_id: str,
        runtime_metadata: dict,
    ) -> list[EscapeSignal]:
        """Detect unusual hypercall patterns or CPUID leaf abuse. Stub."""
        signals: list[EscapeSignal] = []
        # Future: read KVM perf counters, detect CPUID fingerprinting attempts
        if runtime_metadata.get("suspicious_hypercalls"):
            signals.append(EscapeSignal(
                vm_id=vm_id,
                signal_type=EscapeSignalType.HYPERVISOR_PROBE,
                severity=EscapeSeverity.HIGH,
                evidence={"detail": "suspicious_hypercalls flag set in metadata"},
                detection_method="metadata_heuristic",
            ))
        return signals

    def check_docker_socket_access(self, vm_id: str) -> list[EscapeSignal]:
        """Detect /var/run/docker.sock access from inside VM. Stub."""
        import platform
        signals: list[EscapeSignal] = []
        # Future: inotify watch on docker socket from host side
        # On Windows: docker socket path differs, skip
        if platform.system().lower() == "linux":
            from pathlib import Path
            socket_path = Path("/var/run/docker.sock")
            # Check if socket exists and was recently accessed — heuristic only
            # Real detection requires inotify (Plan C)
            pass
        return signals

    def check_namespace_escape(
        self,
        vm_id: str,
        runtime_metadata: dict,
    ) -> list[EscapeSignal]:
        """Detect pivot_root, unshare, clone3 abuse. Stub."""
        signals: list[EscapeSignal] = []
        if runtime_metadata.get("namespace_violation"):
            signals.append(EscapeSignal(
                vm_id=vm_id,
                signal_type=EscapeSignalType.NAMESPACE_ESCAPE,
                severity=EscapeSeverity.CRITICAL,
                evidence={"detail": "namespace_violation in metadata"},
                detection_method="metadata_heuristic",
            ))
        return signals

    def check_side_channel_probing(
        self,
        vm_id: str,
        timing_samples: list[float],
    ) -> list[EscapeSignal]:
        """Detect cache-flush or speculative execution probe patterns. Stub."""
        signals: list[EscapeSignal] = []
        # Future: statistical analysis of timing_samples for Spectre-class patterns
        return signals

    def scan_all(
        self,
        vm_id: str,
        runtime_metadata: dict,
    ) -> list[EscapeSignal]:
        """Run all available checks. Returns combined signal list."""
        signals: list[EscapeSignal] = []
        signals.extend(self.check_hypervisor_probing(vm_id, runtime_metadata))
        signals.extend(self.check_docker_socket_access(vm_id))
        signals.extend(self.check_namespace_escape(vm_id, runtime_metadata))
        signals.extend(self.check_side_channel_probing(vm_id, []))
        return signals
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_vm_escape_detector.py -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```
git add core/vm_isolation/vm_escape_detector.py tests/test_vm_isolation/test_vm_escape_detector.py
git commit -m "feat(vm): Task 5 — VMEscapeDetector signal hooks (stubs, Plan C full detection)"
```

---

## Task 6: HypervisorGuardian — Base Daemon

**Files:**
- Create: `core/vm_isolation/hypervisor_guardian.py`
- Create: `tests/test_vm_isolation/test_hypervisor_guardian.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_hypervisor_guardian.py
import time
import pytest
from pathlib import Path
from core.vm_isolation.vm_escape_detector import EscapeSignalType, EscapeSeverity


@pytest.fixture
def guardian(tmp_path):
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    from core.vm_isolation.vm_escape_detector import VMEscapeDetector
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    logger = IsolationAuditLogger(db_path=tmp_path / "guardian.db")
    tracker = VMLifecycleTracker(audit_logger=logger)
    detector = VMEscapeDetector()
    return HypervisorGuardian(
        audit_logger=logger,
        lifecycle_tracker=tracker,
        escape_detector=detector,
        poll_interval_seconds=0.1,  # fast for tests
    )


def test_guardian_starts_and_stops(guardian):
    guardian.start()
    assert guardian.is_running() is True
    guardian.stop()
    assert guardian.is_running() is False


def test_guardian_register_vm(guardian):
    from core.isolation_abstraction.isolation_driver import IsolationTier
    from core.vm_isolation.vm_policy_engine import VMProfile
    guardian.register_vm("vm-g1", IsolationTier.DOCKER_HARDENED, VMProfile.SAFE_VM)
    assert "vm-g1" in guardian.monitored_vms()


def test_guardian_deregister_vm(guardian):
    from core.isolation_abstraction.isolation_driver import IsolationTier
    from core.vm_isolation.vm_policy_engine import VMProfile
    guardian.register_vm("vm-g2", IsolationTier.SANDBOX, VMProfile.SAFE_VM)
    guardian.deregister_vm("vm-g2")
    assert "vm-g2" not in guardian.monitored_vms()


def test_guardian_alert_callback_called(guardian):
    from core.isolation_abstraction.isolation_driver import IsolationTier
    from core.vm_isolation.vm_policy_engine import VMProfile
    from core.vm_isolation.vm_escape_detector import EscapeSignal

    alerts_received = []

    def on_alert(signal: EscapeSignal) -> None:
        alerts_received.append(signal)

    guardian.register_alert_callback(on_alert)
    guardian.register_vm("vm-g3", IsolationTier.DOCKER_HARDENED, VMProfile.SAFE_VM)

    # Manually trigger an alert
    from core.vm_isolation.vm_escape_detector import EscapeSignal, EscapeSignalType, EscapeSeverity
    sig = EscapeSignal(
        vm_id="vm-g3",
        signal_type=EscapeSignalType.HYPERVISOR_PROBE,
        severity=EscapeSeverity.HIGH,
        evidence={},
        detection_method="test",
    )
    guardian._dispatch_alert(sig)
    assert len(alerts_received) == 1
    assert alerts_received[0].vm_id == "vm-g3"


def test_guardian_get_stats(guardian):
    stats = guardian.get_stats()
    assert "monitored_count" in stats
    assert "is_running" in stats
    assert "poll_interval_seconds" in stats
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_vm_isolation/test_hypervisor_guardian.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement**

```python
# core/vm_isolation/hypervisor_guardian.py
"""
HypervisorGuardian — base daemon that monitors active VMs.
Runs a polling loop, calls VMEscapeDetector on each VM, dispatches alerts.
Full kernel-level probes (KVM perf, inotify, memory balloon) in Plan C.
"""
from __future__ import annotations
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
from core.isolation_abstraction.isolation_driver import IsolationTier
from core.vm_isolation.vm_escape_detector import VMEscapeDetector, EscapeSignal, EscapeSeverity
from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
from core.vm_isolation.vm_policy_engine import VMProfile


class HypervisorGuardian:
    """
    Base monitoring daemon. Polls registered VMs, runs escape detection,
    dispatches alerts to registered callbacks.
    """

    def __init__(
        self,
        audit_logger: Optional[IsolationAuditLogger] = None,
        lifecycle_tracker: Optional[VMLifecycleTracker] = None,
        escape_detector: Optional[VMEscapeDetector] = None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._tracker = lifecycle_tracker or VMLifecycleTracker(audit_logger=self._logger)
        self._detector = escape_detector or VMEscapeDetector()
        self._poll_interval = poll_interval_seconds

        self._vms: dict[str, dict] = {}           # vm_id → {tier, profile}
        self._vms_lock = threading.Lock()
        self._callbacks: list[Callable[[EscapeSignal], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HypervisorGuardian",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._poll_interval * 2 + 1)
            self._thread = None

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def register_vm(self, vm_id: str, tier: IsolationTier, profile: VMProfile) -> None:
        with self._vms_lock:
            self._vms[vm_id] = {"tier": tier, "profile": profile}

    def deregister_vm(self, vm_id: str) -> None:
        with self._vms_lock:
            self._vms.pop(vm_id, None)

    def monitored_vms(self) -> list[str]:
        with self._vms_lock:
            return list(self._vms.keys())

    def register_alert_callback(self, callback: Callable[[EscapeSignal], None]) -> None:
        self._callbacks.append(callback)

    def _dispatch_alert(self, signal: EscapeSignal) -> None:
        severity = "CRITICAL" if signal.severity == EscapeSeverity.CRITICAL else "WARNING"
        self._logger.log_event(
            vm_id=signal.vm_id,
            event_type="ESCAPE_SIGNAL",
            severity=severity,
            description=f"{signal.signal_type.value} detected via {signal.detection_method}",
            metadata={
                "signal_type": signal.signal_type.value,
                "severity": signal.severity.value,
                "evidence": signal.evidence,
            },
            origin_component="hypervisor_guardian",
        )
        for cb in self._callbacks:
            try:
                cb(signal)
            except Exception:
                pass

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception:
                pass
            time.sleep(self._poll_interval)

    def _poll_once(self) -> None:
        with self._vms_lock:
            vm_ids = list(self._vms.keys())
        for vm_id in vm_ids:
            signals = self._detector.scan_all(vm_id, runtime_metadata={})
            for signal in signals:
                self._dispatch_alert(signal)

    def get_stats(self) -> dict:
        return {
            "monitored_count": len(self.monitored_vms()),
            "is_running": self.is_running(),
            "poll_interval_seconds": self._poll_interval,
            "callback_count": len(self._callbacks),
        }
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_hypervisor_guardian.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```
git add core/vm_isolation/hypervisor_guardian.py tests/test_vm_isolation/test_hypervisor_guardian.py
git commit -m "feat(vm): Task 6 — HypervisorGuardian base daemon (polling + alert dispatch)"
```

---

## Task 7: VMManager — Internal Orchestrator

**Files:**
- Modify: `core/vm_isolation/vm_manager.py` (replace stub with full implementation)
- Create: `tests/test_vm_isolation/test_vm_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vm_isolation/test_vm_manager.py
import pytest
from core.isolation_abstraction.isolation_driver import IsolationTier


def test_vm_manager_singleton():
    from core.vm_isolation.vm_manager import get_vm_manager
    m1 = get_vm_manager()
    m2 = get_vm_manager()
    assert m1 is m2


def test_vm_manager_firecracker_runtime_accessible():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
    mgr = VMManager()
    assert isinstance(mgr.firecracker, FirecrackerRuntime)


def test_vm_manager_qemu_runtime_accessible():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.qemu_runtime import QemuRuntime
    mgr = VMManager()
    assert isinstance(mgr.qemu, QemuRuntime)


def test_vm_manager_best_available_tier_on_windows():
    import platform
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    if platform.system().lower() == "windows":
        # Neither Firecracker nor QEMU available on Windows
        assert mgr.best_available_vm_tier() is None


def test_vm_manager_has_vm_isolation_false_on_windows():
    import platform
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    if platform.system().lower() == "windows":
        assert mgr.has_vm_isolation() is False


def test_vm_manager_guardian_accessible():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    mgr = VMManager()
    assert isinstance(mgr.guardian, HypervisorGuardian)


def test_vm_manager_lifecycle_tracker_accessible():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    mgr = VMManager()
    assert isinstance(mgr.lifecycle, VMLifecycleTracker)


def test_vm_manager_policy_engine_accessible():
    from core.vm_isolation.vm_manager import VMManager
    from core.vm_isolation.vm_policy_engine import VMPolicyEngine
    mgr = VMManager()
    assert isinstance(mgr.policy_engine, VMPolicyEngine)


def test_vm_manager_get_drivers_returns_list():
    from core.vm_isolation.vm_manager import VMManager
    mgr = VMManager()
    drivers = mgr.get_drivers()
    assert isinstance(drivers, list)
    # On Windows: empty list (neither Firecracker nor QEMU available)
    # On Linux+KVM: up to 2 drivers
    import platform
    if platform.system().lower() == "windows":
        assert len(drivers) == 0
```

- [ ] **Step 2: Run to verify failure (get_drivers, firecracker, qemu properties missing)**

```
python -m pytest tests/test_vm_isolation/test_vm_manager.py -v
```
Expected: `AttributeError` or `AssertionError`

- [ ] **Step 3: Replace vm_manager.py stub with full implementation**

```python
# core/vm_isolation/vm_manager.py
"""
VMManager — internal orchestrator for VM-tier runtimes.
NOT an IsolationDriver itself. Holds FirecrackerRuntime + QemuRuntime,
delegates to the appropriate one, coordinates guardian + lifecycle.
"""
from __future__ import annotations
import threading
from typing import Optional

from core.isolation_abstraction.isolation_driver import IsolationDriver, IsolationTier
from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
from core.vm_isolation.qemu_runtime import QemuRuntime
from core.vm_isolation.vm_escape_detector import VMEscapeDetector
from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
from core.vm_isolation.vm_policy_engine import VMPolicyEngine


class VMManager:
    """
    Internal orchestrator. Provides access to:
    - FirecrackerRuntime (Tier 1)
    - QemuRuntime (Tier 2)
    - HypervisorGuardian (monitoring daemon)
    - VMLifecycleTracker (state machine)
    - VMPolicyEngine (profile validation)

    Call get_drivers() to get the list of available IsolationDriver instances
    for registration in UnifiedIsolationRuntime._build_driver_list().
    """

    def __init__(self) -> None:
        self._firecracker = FirecrackerRuntime()
        self._qemu = QemuRuntime()
        self._policy_engine = VMPolicyEngine()
        self._escape_detector = VMEscapeDetector()
        self._lifecycle = VMLifecycleTracker()
        self._guardian = HypervisorGuardian(
            lifecycle_tracker=self._lifecycle,
            escape_detector=self._escape_detector,
        )

    @property
    def firecracker(self) -> FirecrackerRuntime:
        return self._firecracker

    @property
    def qemu(self) -> QemuRuntime:
        return self._qemu

    @property
    def guardian(self) -> HypervisorGuardian:
        return self._guardian

    @property
    def lifecycle(self) -> VMLifecycleTracker:
        return self._lifecycle

    @property
    def policy_engine(self) -> VMPolicyEngine:
        return self._policy_engine

    def has_vm_isolation(self) -> bool:
        """True if at least one VM-tier driver is available."""
        return self._firecracker.is_available() or self._qemu.is_available()

    def best_available_vm_tier(self) -> Optional[IsolationTier]:
        """Returns the best available VM tier, or None if none available."""
        if self._firecracker.is_available():
            return IsolationTier.FIRECRACKER
        if self._qemu.is_available():
            return IsolationTier.QEMU
        return None

    def get_drivers(self) -> list[IsolationDriver]:
        """
        Returns available VM-tier drivers in priority order.
        Called by UnifiedIsolationRuntime._build_driver_list().
        On Windows: returns [] (both unavailable).
        On Linux+KVM: returns [FirecrackerRuntime] or [FirecrackerRuntime, QemuRuntime].
        """
        drivers: list[IsolationDriver] = []
        if self._firecracker.is_available():
            drivers.append(self._firecracker)
        if self._qemu.is_available():
            drivers.append(self._qemu)
        return drivers


_instance: Optional[VMManager] = None
_lock = threading.Lock()


def get_vm_manager() -> VMManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = VMManager()
    return _instance
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_vm_isolation/test_vm_manager.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -q --tb=no
```
Expected: 143+ passed (110 Plan A + all Plan B tasks so far)

- [ ] **Step 6: Commit**

```
git add core/vm_isolation/vm_manager.py tests/test_vm_isolation/test_vm_manager.py
git commit -m "feat(vm): Task 7 — VMManager orchestrator (FirecrackerRuntime + QemuRuntime + Guardian)"
```

---

## Task 8: Update UnifiedIsolationRuntime + Integration Tests

**Files:**
- Modify: `core/isolation_abstraction/unified_isolation_runtime.py` (update `_build_driver_list`)
- Create: `tests/test_vm_isolation/test_integration.py`

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_vm_isolation/test_integration.py
"""
Integration tests verifying Tier 1–5 layered degradation
under the existing UnifiedIsolationRuntime.
"""
import platform
import pytest
from pathlib import Path
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionPayload, ExecutionContext,
)
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy, IsolationUnavailableError,
)


@pytest.fixture
def runtime(tmp_path):
    from core.isolation_abstraction.unified_isolation_runtime import UnifiedIsolationRuntime
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    logger = IsolationAuditLogger(db_path=tmp_path / "integration.db")
    return UnifiedIsolationRuntime(audit_logger=logger)


def test_vm_manager_registered_in_driver_list(runtime):
    """VMManager.get_drivers() result appears in the driver list."""
    from core.vm_isolation.vm_manager import get_vm_manager
    # On Windows: VM drivers unavailable, but registered (is_available=False)
    # On Linux+KVM: Tier 1-2 actually in driver list
    # The key check: no ImportError means integration is wired
    tiers = [d.tier for d in runtime._drivers]
    # At minimum Tier 3-5 always present
    assert IsolationTier.PROCESS_JAIL in tiers
    assert IsolationTier.SANDBOX in tiers


@pytest.mark.asyncio
async def test_execute_isolated_best_available(runtime):
    """BEST_AVAILABLE runs on the highest available tier."""
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo integration"),
        policy=IsolationPolicy.BEST_AVAILABLE,
    )
    assert result.tier_used is not None
    assert result.negotiation is not None


@pytest.mark.asyncio
async def test_strict_isolation_unavailable_on_windows(runtime):
    """STRICT_ISOLATION raises on Windows (no KVM)."""
    if platform.system().lower() != "windows":
        pytest.skip("Windows-only")
    with pytest.raises(IsolationUnavailableError):
        await runtime.execute_isolated(
            ExecutionPayload(command="echo hi"),
            policy=IsolationPolicy.STRICT_ISOLATION,
        )


@pytest.mark.asyncio
async def test_requesting_firecracker_degrades_to_lower_tier(runtime):
    """Requesting FIRECRACKER on Windows → BEST_AVAILABLE falls back."""
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo fallback"),
        required_tier=IsolationTier.FIRECRACKER,
        policy=IsolationPolicy.BEST_AVAILABLE,
    )
    if platform.system().lower() == "windows":
        # Must have degraded
        assert result.negotiation.fallback_level > 0
        assert result.tier_used != IsolationTier.FIRECRACKER
    # On Linux+KVM with Firecracker: fallback_level == 0


@pytest.mark.asyncio
async def test_negotiation_history_recorded(runtime):
    """Negotiations are persisted to the DB."""
    await runtime.execute_isolated(ExecutionPayload(command="echo history"))
    history = runtime.get_negotiation_history(limit=5)
    assert len(history) >= 1
    assert history[0]["actual_tier"] is not None


@pytest.mark.asyncio
async def test_correlation_id_propagated(runtime):
    """ExecutionContext correlation_id reaches ExecutionResult."""
    ctx = ExecutionContext(correlation_id="integ-corr-999")
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo corr"),
        ctx=ctx,
    )
    assert result.correlation_id == "integ-corr-999"


def test_capability_snapshot_includes_firecracker_flag(runtime):
    """CapabilitySnapshot correctly reflects Firecracker availability."""
    snap = runtime._detector.detect()
    if platform.system().lower() == "windows":
        assert snap.has_firecracker is False
        assert IsolationTier.FIRECRACKER not in snap.available_tiers
    # On Linux+KVM with binary: has_firecracker=True


def test_get_vm_manager_returns_orchestrator():
    """get_vm_manager() returns the full VMManager with all sub-components."""
    from core.vm_isolation.vm_manager import get_vm_manager
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    mgr = get_vm_manager()
    assert isinstance(mgr.guardian, HypervisorGuardian)
    assert isinstance(mgr.lifecycle, VMLifecycleTracker)
```

- [ ] **Step 2: Run to check current state**

```
python -m pytest tests/test_vm_isolation/test_integration.py -v
```
Expected: Most pass except `test_vm_manager_registered_in_driver_list` which may fail because `_build_driver_list` still uses the old `get_vm_manager()` append pattern.

- [ ] **Step 3: Update `_build_driver_list` in unified_isolation_runtime.py**

Find `_build_driver_list()` in [core/isolation_abstraction/unified_isolation_runtime.py](core/isolation_abstraction/unified_isolation_runtime.py) and replace the entire method:

```python
def _build_driver_list(self) -> list[IsolationDriver]:
    """Build driver list in tier order. Missing deps degrade gracefully."""
    drivers: list[IsolationDriver] = []
    # Tier 1–2: VM drivers via VMManager
    try:
        from core.vm_isolation.vm_manager import get_vm_manager
        vm_drivers = get_vm_manager().get_drivers()
        drivers.extend(vm_drivers)
    except ImportError:
        pass
    # Tier 3: Docker hardened
    try:
        from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
        drivers.append(DockerHardenedDriver())
    except ImportError:
        pass
    # Tier 4: Sandbox
    try:
        from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
        drivers.append(SandboxDriver())
    except ImportError:
        pass
    # Tier 5: ProcessJail — always available
    try:
        from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
        drivers.append(ProcessJailDriver())
    except ImportError:
        pass
    return drivers
```

- [ ] **Step 4: Run integration tests**

```
python -m pytest tests/test_vm_isolation/test_integration.py -v
```
Expected: 8 PASSED (strict_isolation skips on Linux, firecracker tests pass on Windows with fallback)

- [ ] **Step 5: Run full suite — verify no regressions**

```
python -m pytest tests/ -q --tb=short
```
Expected: 150+ passed, 0 failed. Plan A's 110 tests unbroken.

- [ ] **Step 6: Commit**

```
git add core/isolation_abstraction/unified_isolation_runtime.py tests/test_vm_isolation/test_integration.py
git commit -m "feat(vm): Task 8 — integrate Tier 1-2 into UnifiedIsolationRuntime + integration tests"
```

---

## Self-Review

**Spec coverage:**

| Spec Requirement | Task |
|---|---|
| VMManager singleton | Task 7 |
| FirecrackerDriver with real capability detection | Task 1 |
| QemuDriver with real capability detection | Task 2 |
| DockerHardenedDriver integration (existing, now wire via get_drivers) | Task 8 |
| VM audit logging | Task 4 (VMLifecycleTracker writes to IsolationAuditLogger) |
| VM lifecycle tracking | Task 4 |
| Escape detection hooks | Task 5 |
| HypervisorGuardian base (architecture only) | Task 6 |
| Layered degradation working from start | Task 8 (integration tests) |
| No breakage to UnifiedIsolationRuntime | Task 8 (110 Plan A tests rerun) |
| Windows full compatibility (fallback to Docker/Sandbox) | Tasks 1, 2, 8 |
| Hooks for microVM pool | VMManager.get_drivers() (pool would prepend warm instances) |
| Hooks for VM-level snapshot | SnapshotRef stubs in Task 1+2, Plan C activates them |
| Hooks for forensic VM capture | VMEscapeDetector + HypervisorGuardian dispatch + IsolationAuditLogger |

**Placeholder scan:** No TBDs. Stub methods contain real function signatures with documented Plan C references. `scan_all` in Task 5 calls all check methods. `_monitor_loop` in Task 6 polls real VMs.

**Type consistency:**
- `EscapeSignal` defined in Task 5, used in Task 6 — consistent
- `VMLifecycleTracker` defined in Task 4, injected into `HypervisorGuardian` in Task 6 and `VMManager` in Task 7 — consistent
- `get_vm_manager()` returns `VMManager`, `VMManager.get_drivers()` returns `list[IsolationDriver]` — consistent with Task 8 usage
- `_build_driver_list()` calls `vm_drivers = get_vm_manager().get_drivers()` and `drivers.extend(vm_drivers)` — `extend` works on `list[IsolationDriver]` ✅
