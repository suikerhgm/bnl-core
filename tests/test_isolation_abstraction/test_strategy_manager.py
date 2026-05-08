"""
test_strategy_manager.py — Tests for IsolationStrategyManager
Task 3 of the Nexus BNL Isolation Abstraction Layer.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from core.isolation_abstraction.isolation_driver import IsolationTier
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy,
    IsolationStrategyManager,
    IsolationUnavailableError,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def snap(tiers: set) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        has_firecracker=IsolationTier.FIRECRACKER in tiers,
        has_qemu=IsolationTier.QEMU in tiers,
        has_kvm=any(t in tiers for t in (IsolationTier.FIRECRACKER, IsolationTier.QEMU)),
        has_docker=IsolationTier.DOCKER_HARDENED in tiers,
        has_wsl2=False,
        has_nested_virtualization=False,
        host_os="linux" if IsolationTier.FIRECRACKER in tiers else "windows",
        docker_runtime="docker" if IsolationTier.DOCKER_HARDENED in tiers else None,
        virtualization_type=None,
        last_refresh_reason="test",
        available_tiers=frozenset(tiers),
        detected_at=datetime.now(timezone.utc),
        cache_health_score=100.0,
        cache_source="startup_probe",
        cache_generation=0,
    )


ALL_TIERS = {
    IsolationTier.FIRECRACKER,
    IsolationTier.QEMU,
    IsolationTier.DOCKER_HARDENED,
    IsolationTier.SANDBOX,
    IsolationTier.PROCESS_JAIL,
}
WINDOWS_TIERS = {
    IsolationTier.DOCKER_HARDENED,
    IsolationTier.SANDBOX,
    IsolationTier.PROCESS_JAIL,
}
MINIMAL_TIERS = {IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}

mgr = IsolationStrategyManager()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_best_available_picks_firecracker_when_available():
    tier, *_ = mgr.select_tier(snap(ALL_TIERS), IsolationPolicy.BEST_AVAILABLE, None)
    assert tier == IsolationTier.FIRECRACKER


def test_best_available_falls_back_to_docker_on_windows():
    tier, *_ = mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None)
    assert tier == IsolationTier.DOCKER_HARDENED


def test_strict_isolation_blocks_if_no_kvm():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.STRICT_ISOLATION, None)


def test_strict_isolation_picks_firecracker_when_available():
    tier, *_ = mgr.select_tier(snap(ALL_TIERS), IsolationPolicy.STRICT_ISOLATION, None)
    assert tier == IsolationTier.FIRECRACKER


def test_no_fallback_raises_if_exact_tier_unavailable():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.NO_FALLBACK, IsolationTier.FIRECRACKER)


def test_no_fallback_succeeds_exact_match():
    tier, *_ = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.NO_FALLBACK, IsolationTier.DOCKER_HARDENED
    )
    assert tier == IsolationTier.DOCKER_HARDENED


def test_minimum_security_score_filters_low_tiers():
    tier, _, rejections = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None, min_security_score=65,
    )
    assert tier == IsolationTier.DOCKER_HARDENED  # score=70 passes
    assert "SANDBOX" in rejections  # score=40 rejected


def test_required_capability_filters_incompatible_drivers():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(
            snap(MINIMAL_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
            required_capabilities={"supports_forensics"},
        )


def test_forbidden_runtime_types_excludes_docker():
    tier, *_ = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
        forbidden_runtime_types=["docker"],
    )
    assert tier != IsolationTier.DOCKER_HARDENED
    assert tier in (IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL)


def test_preferred_runtime_types_reorders_without_excluding():
    # Prefer sandbox over docker — docker still available as fallback
    tier, *_ = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None,
        preferred_runtime_types=["sandbox"],
    )
    assert tier == IsolationTier.SANDBOX


def test_safe_degradation_allows_docker():
    tier, *_ = mgr.select_tier(snap(WINDOWS_TIERS), IsolationPolicy.SAFE_DEGRADATION, None)
    assert tier == IsolationTier.DOCKER_HARDENED


def test_safe_degradation_blocks_jail_when_network_required():
    with pytest.raises(IsolationUnavailableError):
        mgr.select_tier(
            snap(MINIMAL_TIERS), IsolationPolicy.SAFE_DEGRADATION, None,
            required_capabilities={"supports_network_isolation"},
        )


def test_returns_rejection_reasons_on_fallback():
    _, tried, rejections = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None, min_security_score=65,
    )
    assert len(rejections) > 0


def test_returns_tried_tiers_list():
    _, tried, _ = mgr.select_tier(
        snap(WINDOWS_TIERS), IsolationPolicy.BEST_AVAILABLE, None, min_security_score=65,
    )
    assert isinstance(tried, list)
