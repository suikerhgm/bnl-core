"""
Tests for core/isolation_abstraction/drivers/process_jail_driver.py
Task 5: ProcessJailDriver (Tier 5)
"""
import asyncio
import uuid
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


# ─── DockerHardenedDriver ─────────────────────────────────────────────────────

def test_docker_driver_tier():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    assert DockerHardenedDriver().tier == IsolationTier.DOCKER_HARDENED


def test_docker_driver_capabilities_match():
    from core.isolation_abstraction.isolation_driver import TIER_CAPABILITIES
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    assert DockerHardenedDriver().capabilities == TIER_CAPABILITIES[IsolationTier.DOCKER_HARDENED]


def test_docker_driver_unavailable_when_no_docker():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    d = DockerHardenedDriver()
    with patch("core.isolation_abstraction.drivers.docker_hardened_driver.subprocess.run",
               return_value=MagicMock(returncode=1)):
        d._available = None  # reset cache
        assert d.is_available() is False


def test_docker_driver_available_when_docker_running():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    d = DockerHardenedDriver()
    with patch("core.isolation_abstraction.drivers.docker_hardened_driver.subprocess.run",
               return_value=MagicMock(returncode=0)):
        d._available = None
        assert d.is_available() is True


@pytest.mark.asyncio
async def test_docker_create_runtime_uses_hardened_config():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_container = MagicMock()
    mock_container.id = "ctr-abc123"
    mock_client = MagicMock()
    mock_client.info.return_value = {"DefaultRuntime": "runc", "SecurityOptions": [], "CgroupDriver": "cgroupfs"}
    mock_client.containers.run.return_value = mock_container

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        handle = await d.create_runtime(RuntimeConfig(agent_id="a1"))

    assert handle.tier == IsolationTier.DOCKER_HARDENED
    assert _get_handle_state(handle.runtime_id, "container_id") == "ctr-abc123"
    # Verify hardened kwargs were passed
    call_kwargs = mock_client.containers.run.call_args[1]
    assert call_kwargs["network_mode"] == "none"
    assert "ALL" in call_kwargs["cap_drop"]
    assert "no-new-privileges:true" in call_kwargs["security_opt"]


@pytest.mark.asyncio
async def test_docker_create_runtime_raises_on_unhealthy_daemon():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_client = MagicMock()
    mock_client.info.side_effect = Exception("daemon not running")

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="unhealthy"):
            await d.create_runtime(RuntimeConfig(agent_id="a1"))


@pytest.mark.asyncio
async def test_docker_execute_returns_result():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_container = MagicMock()
    mock_container.exec_run.return_value = (0, b"hello world")
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()), runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.now(timezone.utc),
        )
        _set_handle_state(handle.runtime_id, "container_id", "ctr-abc")
        result = await d.execute(handle, ExecutionPayload(command="echo hello world"))

    assert result.success is True
    assert "hello world" in result.output
    assert result.tier_used == IsolationTier.DOCKER_HARDENED


@pytest.mark.asyncio
async def test_docker_execute_propagates_ctx():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_container = MagicMock()
    mock_container.exec_run.return_value = (0, b"ok")
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    d = DockerHardenedDriver()
    ctx = ExecutionContext(correlation_id="docker-corr-789")
    with patch.object(d, "_get_client", return_value=mock_client):
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()), runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.now(timezone.utc),
        )
        _set_handle_state(handle.runtime_id, "container_id", "ctr-xyz")
        result = await d.execute(handle, ExecutionPayload(command="echo"), ctx=ctx)

    assert result.correlation_id == "docker-corr-789"
    assert result.execution_id == ctx.execution_id


@pytest.mark.asyncio
async def test_docker_snapshot_returns_snapshot_ref():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_image = MagicMock()
    mock_image.id = "sha256:abc123"
    mock_container = MagicMock()
    mock_container.commit.return_value = mock_image
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()), runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.now(timezone.utc),
        )
        _set_handle_state(handle.runtime_id, "container_id", "ctr-abc")
        ref = await d.snapshot(handle)

    assert ref.available is True
    assert ref.snapshot_id == "sha256:abc123"


@pytest.mark.asyncio
async def test_docker_quarantine_pauses_container():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_container = MagicMock()
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        with patch("core.isolation_abstraction.drivers.docker_hardened_driver.get_permission_manager",
                   side_effect=ImportError):
            handle = RuntimeHandle(
                runtime_id=str(uuid.uuid4()), runtime_type="docker",
                tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.now(timezone.utc),
            )
            _set_handle_state(handle.runtime_id, "container_id", "ctr-abc")
            await d.quarantine(handle, "suspicious activity")

    mock_container.pause.assert_called_once()
    assert _get_handle_state(handle.runtime_id, "state") == RuntimeLifecycleState.QUARANTINED


@pytest.mark.asyncio
async def test_docker_destroy_removes_container():
    from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
    mock_container = MagicMock()
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    d = DockerHardenedDriver()
    with patch.object(d, "_get_client", return_value=mock_client):
        handle = RuntimeHandle(
            runtime_id=str(uuid.uuid4()), runtime_type="docker",
            tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.now(timezone.utc),
        )
        ctr_id = "ctr-to-remove"
        _set_handle_state(handle.runtime_id, "container_id", ctr_id)
        rid = handle.runtime_id
        await d.destroy(handle)

    mock_container.remove.assert_called_once_with(force=True)
    assert _get_handle_state(rid, "container_id") is None
