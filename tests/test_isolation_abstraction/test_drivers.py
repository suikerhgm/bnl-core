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
