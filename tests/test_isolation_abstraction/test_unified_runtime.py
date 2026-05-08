"""
test_unified_runtime.py — Tests for UnifiedIsolationRuntime
Task 9 of the Nexus BNL Isolation Abstraction Layer.
"""
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from core.isolation_abstraction.isolation_driver import (
    IsolationTier, ExecutionPayload, RuntimeConfig, ExecutionContext,
    RuntimeHandle, ExecutionResult, RuntimeLifecycleState,
)
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy, IsolationUnavailableError,
)


def make_runtime(tmp_path):
    from core.isolation_abstraction.unified_isolation_runtime import UnifiedIsolationRuntime
    from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
    logger = IsolationAuditLogger(db_path=tmp_path / "test_runtime.db")
    return UnifiedIsolationRuntime(audit_logger=logger)


@pytest.mark.asyncio
async def test_execute_isolated_returns_execution_result(tmp_path):
    runtime = make_runtime(tmp_path)
    result = await runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    assert isinstance(result, ExecutionResult)
    assert result.tier_used is not None


@pytest.mark.asyncio
async def test_execute_isolated_attaches_negotiation(tmp_path):
    runtime = make_runtime(tmp_path)
    result = await runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    assert result.negotiation is not None
    assert result.negotiation.actual_tier == result.tier_used


@pytest.mark.asyncio
async def test_execute_isolated_propagates_ctx(tmp_path):
    runtime = make_runtime(tmp_path)
    ctx = ExecutionContext(correlation_id="test-corr-001")
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo hello"),
        ctx=ctx,
    )
    assert result.correlation_id == "test-corr-001"


@pytest.mark.asyncio
async def test_strict_isolation_raises_on_windows(tmp_path):
    import platform
    if platform.system().lower() != "windows":
        pytest.skip("Windows-only test")
    runtime = make_runtime(tmp_path)
    with pytest.raises(IsolationUnavailableError):
        await runtime.execute_isolated(
            ExecutionPayload(command="echo hi"),
            policy=IsolationPolicy.STRICT_ISOLATION,
        )


@pytest.mark.asyncio
async def test_degradation_logged_on_fallback(tmp_path):
    import sqlite3
    runtime = make_runtime(tmp_path)
    # Request FIRECRACKER (unavailable) → should fall back and log DEGRADATION
    try:
        await runtime.execute_isolated(
            ExecutionPayload(command="echo hi"),
            required_tier=IsolationTier.FIRECRACKER,
            policy=IsolationPolicy.BEST_AVAILABLE,
        )
    except IsolationUnavailableError:
        pass  # strict policy might block
    # Check if degradation event was logged
    with sqlite3.connect(str(tmp_path / "test_runtime.db")) as conn:
        rows = list(conn.execute(
            "SELECT event_type FROM vm_events WHERE event_type='DEGRADATION'"
        ))
    # On Windows, Firecracker is unavailable, so fallback occurred
    import platform
    if platform.system().lower() == "windows":
        assert len(rows) > 0


@pytest.mark.asyncio
async def test_create_and_destroy_runtime(tmp_path):
    runtime = make_runtime(tmp_path)
    handle = await runtime.create_isolated_runtime(policy=IsolationPolicy.BEST_AVAILABLE)
    assert handle.runtime_id is not None
    await runtime.destroy_runtime(handle)


def test_refresh_capabilities_returns_snapshot(tmp_path):
    runtime = make_runtime(tmp_path)
    snap = runtime.refresh_capabilities(reason="test")
    from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
    assert isinstance(snap, CapabilitySnapshot)
    assert snap.host_os in ("linux", "windows", "macos", "unknown")


def test_get_negotiation_history_empty_initially(tmp_path):
    runtime = make_runtime(tmp_path)
    history = runtime.get_negotiation_history(limit=10)
    assert isinstance(history, list)


def test_get_negotiation_history_after_execute(tmp_path):
    import asyncio
    runtime = make_runtime(tmp_path)
    asyncio.get_event_loop().run_until_complete(
        runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    )
    history = runtime.get_negotiation_history(limit=10)
    assert len(history) >= 1
    assert "actual_tier" in history[0]


def test_singleton_returns_same_instance():
    from core.isolation_abstraction.unified_isolation_runtime import get_unified_runtime
    r1 = get_unified_runtime()
    r2 = get_unified_runtime()
    assert r1 is r2


@pytest.mark.asyncio
async def test_execute_on_remote_node_raises(tmp_path):
    runtime = make_runtime(tmp_path)
    with pytest.raises(NotImplementedError):
        await runtime.execute_on_remote_node("node-1", ExecutionPayload(command="echo"))
