# tests/test_vm_isolation/test_integration.py
"""
Integration tests: full Tier 1–5 layered degradation under UnifiedIsolationRuntime.
Verifies that VMManager.get_drivers() is correctly wired into the runtime.
"""
import platform
import pytest
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


def test_driver_list_contains_tier3_through_5(runtime):
    """Tier 3–5 always in driver list regardless of platform."""
    tiers = [d.tier for d in runtime._drivers]
    assert IsolationTier.PROCESS_JAIL in tiers
    assert IsolationTier.SANDBOX in tiers


def test_vm_manager_get_drivers_wired(runtime):
    """VMManager.get_drivers() result is in driver list (empty on Windows, non-empty on Linux+KVM)."""
    from core.vm_isolation.vm_manager import get_vm_manager
    vm_drivers = get_vm_manager().get_drivers()
    driver_tiers = {d.tier for d in runtime._drivers}
    for d in vm_drivers:
        assert d.tier in driver_tiers


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
    """STRICT_ISOLATION requires Tier 1 or 2 — raises on Windows (no KVM)."""
    if platform.system().lower() != "windows":
        pytest.skip("Windows-only")
    with pytest.raises(IsolationUnavailableError):
        await runtime.execute_isolated(
            ExecutionPayload(command="echo hi"),
            policy=IsolationPolicy.STRICT_ISOLATION,
        )


@pytest.mark.asyncio
async def test_firecracker_request_degrades_on_windows(runtime):
    """Requesting FIRECRACKER on Windows falls back to lower tier."""
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo fallback"),
        required_tier=IsolationTier.FIRECRACKER,
        policy=IsolationPolicy.BEST_AVAILABLE,
    )
    if platform.system().lower() == "windows":
        assert result.negotiation.fallback_level > 0
        assert result.tier_used != IsolationTier.FIRECRACKER


@pytest.mark.asyncio
async def test_negotiation_attached_to_result(runtime):
    """NegotiationResult is attached to ExecutionResult."""
    result = await runtime.execute_isolated(ExecutionPayload(command="echo hi"))
    assert result.negotiation is not None
    assert result.negotiation.actual_tier == result.tier_used


@pytest.mark.asyncio
async def test_correlation_id_propagated(runtime):
    """ExecutionContext.correlation_id reaches ExecutionResult."""
    ctx = ExecutionContext(correlation_id="integ-b-999")
    result = await runtime.execute_isolated(
        ExecutionPayload(command="echo corr"),
        ctx=ctx,
    )
    assert result.correlation_id == "integ-b-999"


@pytest.mark.asyncio
async def test_negotiation_history_recorded(runtime):
    """Negotiations persisted to DB after execute_isolated."""
    await runtime.execute_isolated(ExecutionPayload(command="echo history"))
    history = runtime.get_negotiation_history(limit=5)
    assert len(history) >= 1
    assert history[0]["actual_tier"] is not None


def test_firecracker_not_available_on_windows():
    """CapabilitySnapshot correctly shows Firecracker unavailable on Windows."""
    if platform.system().lower() != "windows":
        pytest.skip("Windows-only")
    from core.isolation_abstraction.isolation_capability_detector import get_capability_detector
    snap = get_capability_detector().detect()
    assert snap.has_firecracker is False
    assert IsolationTier.FIRECRACKER not in snap.available_tiers


def test_get_vm_manager_has_all_components():
    """VMManager provides all required sub-components."""
    from core.vm_isolation.vm_manager import get_vm_manager
    from core.vm_isolation.hypervisor_guardian import HypervisorGuardian
    from core.vm_isolation.vm_lifecycle import VMLifecycleTracker
    from core.vm_isolation.vm_policy_engine import VMPolicyEngine
    mgr = get_vm_manager()
    assert isinstance(mgr.guardian, HypervisorGuardian)
    assert isinstance(mgr.lifecycle, VMLifecycleTracker)
    assert isinstance(mgr.policy_engine, VMPolicyEngine)
