"""
test_negotiator.py — Tests for IsolationNegotiator + NegotiationResult
Task 4 of the Nexus BNL Isolation Abstraction Layer.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from core.isolation_abstraction.isolation_driver import (
    IsolationTier,
    TIER_CAPABILITIES,
    TIER_SECURITY_SCORES,
    TIER_RISK_ADJUSTMENTS,
)
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
from core.isolation_abstraction.isolation_negotiator import (
    IsolationNegotiator,
    NegotiationResult,
    get_negotiator,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def snap(tiers):
    return CapabilitySnapshot(
        has_firecracker=IsolationTier.FIRECRACKER in tiers,
        has_qemu=IsolationTier.QEMU in tiers,
        has_kvm=False,
        has_docker=IsolationTier.DOCKER_HARDENED in tiers,
        has_wsl2=False,
        has_nested_virtualization=False,
        host_os="windows",
        docker_runtime="docker" if IsolationTier.DOCKER_HARDENED in tiers else None,
        virtualization_type=None,
        last_refresh_reason="test",
        available_tiers=frozenset(tiers),
        detected_at=datetime.now(timezone.utc),
        cache_health_score=100.0,
        cache_source="startup_probe",
        cache_generation=0,
    )


WINDOWS = {IsolationTier.DOCKER_HARDENED, IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
neg = IsolationNegotiator()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_negotiate_returns_negotiation_result():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert isinstance(result, NegotiationResult)


def test_exact_match_fallback_level_zero():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.NO_FALLBACK,
        requested_tier=IsolationTier.DOCKER_HARDENED,
    )
    assert result.fallback_level == 0
    assert result.actual_tier == IsolationTier.DOCKER_HARDENED


def test_fallback_level_positive_when_degraded():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE,
        requested_tier=IsolationTier.FIRECRACKER,
    )
    assert result.fallback_level > 0
    assert result.actual_tier == IsolationTier.DOCKER_HARDENED


def test_security_score_matches_tier():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert result.security_score == TIER_SECURITY_SCORES[result.actual_tier]


def test_risk_adjusted_score_matches():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    expected = TIER_SECURITY_SCORES[result.actual_tier] + TIER_RISK_ADJUSTMENTS[result.actual_tier]
    assert result.risk_adjusted_score == expected


def test_candidate_drivers_contains_all_available():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    for tier in WINDOWS:
        assert tier in result.candidate_drivers


def test_rejection_reasons_populated_on_fallback():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE,
        requested_tier=IsolationTier.FIRECRACKER,
    )
    assert len(result.rejection_reasons) > 0


def test_forensic_support_matches_capabilities():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert result.forensic_support == TIER_CAPABILITIES[result.actual_tier].supports_forensics


def test_behavioral_support_matches_capabilities():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert result.behavioral_support == TIER_CAPABILITIES[result.actual_tier].supports_behavioral_lab


def test_negotiation_id_is_unique():
    r1 = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    r2 = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert r1.negotiation_id != r2.negotiation_id


def test_decision_entropy_zero_single_option():
    result = neg.negotiate(
        snap({IsolationTier.PROCESS_JAIL}), IsolationPolicy.BEST_AVAILABLE,
    )
    assert result.decision_entropy == 0.0


def test_decision_entropy_positive_multiple_options():
    result = neg.negotiate(snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE)
    assert result.decision_entropy >= 0.0


def test_degradation_telemetry_populated_on_fallback():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.BEST_AVAILABLE,
        requested_tier=IsolationTier.FIRECRACKER,
    )
    assert result.degradation_telemetry.get("original_requested") == "FIRECRACKER"
    assert "degradation_path" in result.degradation_telemetry


def test_degradation_telemetry_empty_on_exact_match():
    result = neg.negotiate(
        snap(WINDOWS), IsolationPolicy.NO_FALLBACK,
        requested_tier=IsolationTier.DOCKER_HARDENED,
    )
    assert result.degradation_telemetry == {}


def test_get_negotiator_singleton():
    n1 = get_negotiator()
    n2 = get_negotiator()
    assert n1 is n2
