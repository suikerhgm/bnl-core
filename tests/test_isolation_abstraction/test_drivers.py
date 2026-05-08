"""
Tests for core/isolation_abstraction/drivers/process_jail_driver.py
Task 5: ProcessJailDriver (Tier 5)
"""
import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from core.isolation_abstraction.isolation_driver import (
    IsolationTier, RuntimeConfig, ExecutionPayload, ExecutionContext,
    RuntimeLifecycleState, RuntimeHandle, SnapshotRef,
    _get_handle_state, _set_handle_state,
)


# ─── ProcessJailDriver ────────────────────────────────────────────────────────

def test_process_jail_tier():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    assert d.tier == IsolationTier.PROCESS_JAIL


def test_process_jail_always_available():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    assert ProcessJailDriver().is_available() is True


def test_process_jail_capabilities_match_tier():
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    assert d.capabilities == TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]


@pytest.mark.asyncio
async def test_process_jail_create_runtime_returns_handle():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    config = RuntimeConfig(agent_id="test-agent")
    handle = await d.create_runtime(config)
    assert handle.tier == IsolationTier.PROCESS_JAIL
    assert handle.runtime_id is not None
    assert _get_handle_state(handle.runtime_id, "agent_id") == "test-agent"


@pytest.mark.asyncio
async def test_process_jail_execute_echo():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    config = RuntimeConfig(agent_id="test")
    handle = await d.create_runtime(config)
    result = await d.execute(handle, ExecutionPayload(command="echo hello"))
    assert result.success is True
    assert "hello" in result.output
    assert result.tier_used == IsolationTier.PROCESS_JAIL


@pytest.mark.asyncio
async def test_process_jail_execute_sets_execution_id():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    handle = await d.create_runtime(RuntimeConfig(agent_id="t"))
    ctx = ExecutionContext(correlation_id="corr-123")
    result = await d.execute(handle, ExecutionPayload(command="echo hi"), ctx=ctx)
    assert result.execution_id == ctx.execution_id
    assert result.correlation_id == "corr-123"


@pytest.mark.asyncio
async def test_process_jail_snapshot_unavailable():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    handle = await d.create_runtime(RuntimeConfig(agent_id="t"))
    ref = await d.snapshot(handle)
    assert ref.available is False


@pytest.mark.asyncio
async def test_process_jail_destroy_clears_state():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    handle = await d.create_runtime(RuntimeConfig(agent_id="t"))
    rid = handle.runtime_id
    await d.destroy(handle)
    assert _get_handle_state(rid, "agent_id") is None


@pytest.mark.asyncio
async def test_process_jail_timeout_returns_failure():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    handle = await d.create_runtime(RuntimeConfig(agent_id="t"))
    # Very short timeout on a sleep command
    result = await d.execute(
        handle,
        ExecutionPayload(
            command='python -c "import time; time.sleep(10)"',
            timeout_seconds=1,
        ),
    )
    assert result.success is False
    assert result.exit_code == 124


@pytest.mark.asyncio
async def test_process_jail_quarantine_sets_state():
    from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
    d = ProcessJailDriver()
    handle = await d.create_runtime(RuntimeConfig(agent_id="t"))
    with patch(
        "core.isolation_abstraction.drivers.process_jail_driver.get_permission_manager",
        side_effect=ImportError,
    ):
        await d.quarantine(handle, "test reason")
    assert _get_handle_state(handle.runtime_id, "state") == RuntimeLifecycleState.QUARANTINED


# ─── SandboxDriver ────────────────────────────────────────────────────────────

def test_sandbox_driver_tier():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    assert SandboxDriver().tier == IsolationTier.SANDBOX


def test_sandbox_driver_always_available():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    assert SandboxDriver().is_available() is True


def test_sandbox_capabilities_match_tier():
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    assert SandboxDriver().capabilities == TIER_CAPABILITIES[IsolationTier.SANDBOX]


@pytest.mark.asyncio
async def test_sandbox_create_runtime_returns_handle():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-001", "status": "CREATED"}
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
    assert handle.tier == IsolationTier.SANDBOX
    assert _get_handle_state(handle.runtime_id, "sandbox_id") == "sb-001"
    assert _get_handle_state(handle.runtime_id, "agent_id") == "a1"


@pytest.mark.asyncio
async def test_sandbox_execute_returns_result():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-002", "status": "CREATED"}
    mock_mgr.execute_in_sandbox.return_value = {
        "success": True, "output": "hello", "error": None, "exit_code": 0
    }
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
        result = await d.execute(handle, ExecutionPayload(command="echo hello"))
    assert result.success is True
    assert result.output == "hello"
    assert result.tier_used == IsolationTier.SANDBOX


@pytest.mark.asyncio
async def test_sandbox_execute_propagates_ctx():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-003", "status": "CREATED"}
    mock_mgr.execute_in_sandbox.return_value = {"success": True, "output": "", "error": None, "exit_code": 0}
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
        ctx = ExecutionContext(correlation_id="corr-456")
        result = await d.execute(handle, ExecutionPayload(command="echo"), ctx=ctx)
    assert result.correlation_id == "corr-456"
    assert result.execution_id == ctx.execution_id


@pytest.mark.asyncio
async def test_sandbox_snapshot_unavailable():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-004", "status": "CREATED"}
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
        ref = await d.snapshot(handle)
    assert ref.available is False


@pytest.mark.asyncio
async def test_sandbox_quarantine_calls_manager_and_sets_state():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-005", "status": "CREATED"}
    mock_mgr.quarantine_sandbox.return_value = True
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        with patch("core.isolation_abstraction.drivers.sandbox_driver.get_permission_manager",
                   side_effect=ImportError):
            d = SandboxDriver()
            handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
            await d.quarantine(handle, "test reason")
    mock_mgr.quarantine_sandbox.assert_called_once_with("sb-005", "test reason")
    assert _get_handle_state(handle.runtime_id, "state") == RuntimeLifecycleState.QUARANTINED


@pytest.mark.asyncio
async def test_sandbox_destroy_clears_state():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-006", "status": "CREATED"}
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
        rid = handle.runtime_id
        await d.destroy(handle)
    assert _get_handle_state(rid, "sandbox_id") is None


@pytest.mark.asyncio
async def test_sandbox_execute_handles_exception_gracefully():
    from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
    mock_mgr = MagicMock()
    mock_mgr.create_sandbox.return_value = {"sandbox_id": "sb-007", "status": "CREATED"}
    mock_mgr.execute_in_sandbox.side_effect = RuntimeError("sandbox crashed")
    with patch("core.isolation_abstraction.drivers.sandbox_driver.get_sandbox_manager",
               return_value=mock_mgr):
        d = SandboxDriver()
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))
        result = await d.execute(handle, ExecutionPayload(command="anything"))
    assert result.success is False
    assert "sandbox crashed" in result.error
