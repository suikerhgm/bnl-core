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
        with patch("core.vm_isolation.firecracker_runtime._KVM_DEVICE") as mock_kvm:
            mock_kvm.exists.return_value = True
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
