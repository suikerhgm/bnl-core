"""
isolation_negotiator.py — IsolationNegotiator + NegotiationResult
Task 4 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: ONLY stdlib + isolation_driver + isolation_capability_detector
                 + isolation_strategy_manager.
No imports from audit logger, unified runtime, or drivers.
"""
from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from core.isolation_abstraction.isolation_driver import (
    IsolationTier,
    DriverCapabilities,
    TIER_CAPABILITIES,
    TIER_SECURITY_SCORES,
    TIER_RISK_ADJUSTMENTS,
)
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy,
    IsolationStrategyManager,
)


# ---------------------------------------------------------------------------
# NegotiationResult
# ---------------------------------------------------------------------------

@dataclass
class NegotiationResult:
    # Selection outcome
    requested_tier: Optional[IsolationTier]
    actual_tier: IsolationTier
    policy: IsolationPolicy
    reason: str

    # Execution context
    host_os: str
    fallback_level: int
    fallback_chain: tuple                        # tuple[IsolationTier, ...] — tiers tried before selection

    # Driver quality
    driver_capabilities: DriverCapabilities
    security_score: int                          # base TIER_SECURITY_SCORES value
    risk_adjusted_score: int                     # security_score + TIER_RISK_ADJUSTMENTS

    # Support flags (derived from driver_capabilities)
    forensic_support: bool
    behavioral_support: bool

    # Full reasoning trail
    candidate_drivers: tuple                     # tuple[IsolationTier, ...] — all available tiers
    rejection_reasons: dict                      # {tier_name: reason_str}
    capability_mismatches: dict                  # {} for now (future use)
    policy_rejections: dict                      # {} for now (future use)

    # Post-execution enrichment (set later by UnifiedIsolationRuntime)
    execution_duration_ms: Optional[int] = None
    actual_runtime_health: Optional[str] = None
    post_execution_anomalies: list = field(default_factory=list)
    degradation_impact: Optional[str] = None

    # Future-readiness
    remote_execution_ready: bool = False
    degradation_acceptable: bool = True

    # Forensic metadata
    negotiation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    decision_entropy: float = 0.0                # 0 = one option, 1 = many equally good
    selection_confidence: float = 1.0            # 0–1
    runtime_stability_estimate: float = 1.0      # future: fed by RuntimeHealthStats

    # Telemetry fields
    preferred_runtime_types: list = field(default_factory=list)
    forbidden_runtime_types: list = field(default_factory=list)
    degradation_telemetry: dict = field(default_factory=dict)
    # degradation_telemetry keys: original_requested, degradation_path, host_state

    negotiated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# IsolationNegotiator
# ---------------------------------------------------------------------------

class IsolationNegotiator:
    def __init__(self) -> None:
        self._strategy = IsolationStrategyManager()

    def negotiate(
        self,
        snapshot: CapabilitySnapshot,
        policy: IsolationPolicy,
        requested_tier: Optional[IsolationTier] = None,
        min_security_score: int = 0,
        required_capabilities: Optional[set[str]] = None,
        preferred_runtime_types: Optional[list[str]] = None,
        forbidden_runtime_types: Optional[list[str]] = None,
        preferred_capabilities: Optional[set[str]] = None,
    ) -> NegotiationResult:
        # Step 1: delegate to strategy manager
        selected, tried, rejections = self._strategy.select_tier(
            snapshot=snapshot,
            policy=policy,
            requested_tier=requested_tier,
            min_security_score=min_security_score,
            required_capabilities=required_capabilities,
            preferred_runtime_types=preferred_runtime_types,
            forbidden_runtime_types=forbidden_runtime_types,
            preferred_capabilities=preferred_capabilities,
        )

        # Step 2: look up capabilities for selected tier
        caps = TIER_CAPABILITIES[selected]

        # Step 3: compute scores
        security_score = TIER_SECURITY_SCORES[selected]
        risk_adjusted_score = security_score + TIER_RISK_ADJUSTMENTS[selected]

        # Step 4: compute fallback_level
        if requested_tier is None or selected == requested_tier:
            fallback_level = 0
        else:
            fallback_level = selected.value - requested_tier.value

        # If a specific tier was requested but not available, record that rejection
        # so rejection_reasons is populated even when BEST_AVAILABLE policy skips it
        if (
            requested_tier is not None
            and requested_tier not in snapshot.available_tiers
            and requested_tier.name not in rejections
        ):
            rejections = dict(rejections)  # make a mutable copy
            rejections[requested_tier.name] = "tier not available on this host"

        # Step 5: compute decision_entropy
        viable_count = len(snapshot.available_tiers) - len(rejections)
        if viable_count <= 1:
            decision_entropy = 0.0
        else:
            decision_entropy = math.log2(viable_count) / math.log2(5)
            decision_entropy = max(0.0, min(1.0, decision_entropy))

        # Step 6: compute selection_confidence
        selection_confidence = 1.0 - (len(rejections) / max(1, len(snapshot.available_tiers)))
        selection_confidence = max(0.0, min(1.0, selection_confidence))

        # Step 7: build degradation_telemetry
        if fallback_level > 0:
            degradation_telemetry = {
                "original_requested": requested_tier.name if requested_tier else None,
                "degradation_path": [t.name for t in tried] + [selected.name],
                "host_state": {
                    "has_kvm": snapshot.has_kvm,
                    "has_docker": snapshot.has_docker,
                    "host_os": snapshot.host_os,
                },
            }
        else:
            degradation_telemetry = {}

        # Step 8: build reason string
        if fallback_level == 0 or requested_tier is None:
            reason = f"exact_match:{selected.name}"
        else:
            reason = f"fallback_from_{requested_tier.name}_to_{selected.name}:level={fallback_level}"

        # Step 9: construct and return NegotiationResult
        return NegotiationResult(
            requested_tier=requested_tier,
            actual_tier=selected,
            policy=policy,
            reason=reason,
            host_os=snapshot.host_os,
            fallback_level=fallback_level,
            fallback_chain=tuple(t for t in tried if t != selected),
            driver_capabilities=caps,
            security_score=security_score,
            risk_adjusted_score=risk_adjusted_score,
            forensic_support=caps.supports_forensics,
            behavioral_support=caps.supports_behavioral_lab,
            candidate_drivers=tuple(sorted(snapshot.available_tiers)),
            rejection_reasons=dict(rejections),
            capability_mismatches={},
            policy_rejections={},
            decision_entropy=decision_entropy,
            selection_confidence=selection_confidence,
            preferred_runtime_types=list(preferred_runtime_types) if preferred_runtime_types else [],
            forbidden_runtime_types=list(forbidden_runtime_types) if forbidden_runtime_types else [],
            degradation_telemetry=degradation_telemetry,
        )


# ---------------------------------------------------------------------------
# Singleton getter
# ---------------------------------------------------------------------------

_negotiator_instance: Optional[IsolationNegotiator] = None
_negotiator_lock = threading.Lock()


def get_negotiator() -> IsolationNegotiator:
    global _negotiator_instance
    if _negotiator_instance is None:
        with _negotiator_lock:
            if _negotiator_instance is None:
                _negotiator_instance = IsolationNegotiator()
    return _negotiator_instance
