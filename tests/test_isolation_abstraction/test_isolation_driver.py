"""
Tests for core/isolation_abstraction/isolation_driver.py
Task 1: Core Types + IsolationDriver Protocol
"""
import pytest
from datetime import datetime

from core.isolation_abstraction import (
    IsolationTier,
    IsolationDriver,
    DriverCapabilities,
    RuntimeHandle,
    RuntimeLifecycleState,
    ExecutionPayload,
    ExecutionContext,
    ExecutionResult,
    SnapshotRef,
    RuntimeConfig,
    RuntimeHealthStats,
    TIER_CAPABILITIES,
    TIER_SECURITY_SCORES,
    TIER_RISK_ADJUSTMENTS,
    _set_handle_state,
    _get_handle_state,
    _clear_handle_state,
)


def test_isolation_tier_is_ordered():
    assert IsolationTier.FIRECRACKER < IsolationTier.DOCKER_HARDENED < IsolationTier.PROCESS_JAIL


def test_driver_capabilities_is_immutable():
    caps = TIER_CAPABILITIES[IsolationTier.PROCESS_JAIL]
    with pytest.raises(Exception):
        caps.supports_snapshots = True  # must raise FrozenInstanceError


def test_all_tiers_have_capabilities():
    for tier in IsolationTier:
        assert tier in TIER_CAPABILITIES
        assert tier in TIER_SECURITY_SCORES


def test_firecracker_has_strongest_score():
    assert TIER_SECURITY_SCORES[IsolationTier.FIRECRACKER] > TIER_SECURITY_SCORES[IsolationTier.DOCKER_HARDENED]
    assert TIER_SECURITY_SCORES[IsolationTier.DOCKER_HARDENED] > TIER_SECURITY_SCORES[IsolationTier.PROCESS_JAIL]


def test_qemu_has_negative_risk_adjustment():
    assert TIER_RISK_ADJUSTMENTS[IsolationTier.QEMU] < 0


def test_runtime_handle_is_frozen():
    h = RuntimeHandle(runtime_id="abc", runtime_type="jail", tier=IsolationTier.PROCESS_JAIL, created_at=datetime.utcnow())
    with pytest.raises(Exception):
        h.runtime_id = "xyz"


def test_runtime_handle_hashes_by_id():
    h1 = RuntimeHandle(runtime_id="abc", runtime_type="jail", tier=IsolationTier.PROCESS_JAIL, created_at=datetime.utcnow())
    h2 = RuntimeHandle(runtime_id="abc", runtime_type="docker", tier=IsolationTier.DOCKER_HARDENED, created_at=datetime.utcnow())
    assert h1 == h2
    assert hash(h1) == hash(h2)


def test_handle_state_registry_isolation():
    _set_handle_state("r1", "foo", "bar")
    _set_handle_state("r2", "foo", "baz")
    assert _get_handle_state("r1", "foo") == "bar"
    assert _get_handle_state("r2", "foo") == "baz"
    _clear_handle_state("r1")
    assert _get_handle_state("r1", "foo") is None


def test_snapshot_ref_frozen():
    ref = SnapshotRef(available=False, reason="not_supported")
    with pytest.raises(Exception):
        ref.available = True


def test_execution_context_auto_generates_id():
    ctx = ExecutionContext()
    assert ctx.execution_id is not None
    ctx2 = ExecutionContext()
    assert ctx.execution_id != ctx2.execution_id


def test_runtime_lifecycle_state_values():
    assert RuntimeLifecycleState.CREATED == "created"
    assert RuntimeLifecycleState.QUARANTINED == "quarantined"


def test_isolation_driver_cannot_be_instantiated():
    with pytest.raises(TypeError):
        IsolationDriver()


def test_tier_capabilities_cover_all_fields():
    # Every tier's DriverCapabilities must have all expected fields populated
    from dataclasses import fields
    dc_fields = {f.name for f in fields(DriverCapabilities)}
    for tier in IsolationTier:
        caps = TIER_CAPABILITIES[tier]
        for field_name in dc_fields:
            assert hasattr(caps, field_name), f"{tier} missing field {field_name}"
