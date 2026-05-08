import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from core.isolation_abstraction.isolation_driver import (
    IsolationTier, RuntimeConfig, ExecutionPayload, ExecutionContext,
    RuntimeLifecycleState, RuntimeHandle,
    _get_handle_state, _set_handle_state, TIER_RISK_ADJUSTMENTS,
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
        with patch("core.vm_isolation.qemu_runtime._KVM_DEVICE") as mock_kvm:
            mock_kvm.exists.return_value = True
            with patch("core.vm_isolation.qemu_runtime.platform.system", return_value="Linux"):
                d._available = None
                assert d.is_available() is True


def test_qemu_risk_adjustment_is_negative():
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
    assert result.success is False
    assert "not yet implemented" in result.error or "stub" in result.error.lower()


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
