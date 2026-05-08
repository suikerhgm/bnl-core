"""
isolation_strategy_manager.py — IsolationStrategyManager
Task 3 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: ONLY stdlib + isolation_driver + isolation_capability_detector.
No I/O, no threading, no singletons — pure computation.
"""
from __future__ import annotations

from enum import Enum

from core.isolation_abstraction.isolation_driver import (
    IsolationTier,
    TIER_CAPABILITIES,
    TIER_SECURITY_SCORES,
    TIER_RISK_ADJUSTMENTS,
)
from core.isolation_abstraction.isolation_capability_detector import CapabilitySnapshot


# ---------------------------------------------------------------------------
# IsolationPolicy
# ---------------------------------------------------------------------------

class IsolationPolicy(str, Enum):
    BEST_AVAILABLE   = "best_available"
    SAFE_DEGRADATION = "safe_degradation"
    STRICT_ISOLATION = "strict_isolation"
    NO_FALLBACK      = "no_fallback"


# ---------------------------------------------------------------------------
# IsolationUnavailableError
# ---------------------------------------------------------------------------

class IsolationUnavailableError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Tier → runtime type name mapping
# ---------------------------------------------------------------------------

_TIER_RUNTIME_TYPE: dict[IsolationTier, str] = {
    IsolationTier.FIRECRACKER:     "firecracker",
    IsolationTier.QEMU:            "qemu",
    IsolationTier.DOCKER_HARDENED: "docker",
    IsolationTier.SANDBOX:         "sandbox",
    IsolationTier.PROCESS_JAIL:    "jail",
}


# ---------------------------------------------------------------------------
# IsolationStrategyManager
# ---------------------------------------------------------------------------

class IsolationStrategyManager:
    """
    Pure, stateless strategy selector.
    No I/O — fully testable without mocks.
    """

    def select_tier(
        self,
        snapshot: CapabilitySnapshot,
        policy: IsolationPolicy,
        requested_tier: IsolationTier | None,
        min_security_score: int = 0,
        required_capabilities: set[str] | None = None,
        preferred_runtime_types: list[str] | None = None,
        forbidden_runtime_types: list[str] | None = None,
        preferred_capabilities: set[str] | None = None,
    ) -> tuple[IsolationTier, list[IsolationTier], dict[str, str]]:
        """
        Select the best available isolation tier given all constraints.

        Returns:
            (selected_tier, tried_tiers_list, rejection_reasons_dict)

        Raises:
            IsolationUnavailableError if no tier satisfies all constraints.
        """
        # Step 1: sort available tiers — IntEnum lowest first = best first
        candidates: list[IsolationTier] = sorted(snapshot.available_tiers)

        # Step 2: filter out forbidden runtime types
        if forbidden_runtime_types:
            forbidden_set = set(forbidden_runtime_types)
            candidates = [
                t for t in candidates
                if _TIER_RUNTIME_TYPE.get(t) not in forbidden_set
            ]

        # Step 3: re-order preferred runtime types (don't remove non-preferred)
        if preferred_runtime_types:
            preferred_set = set(preferred_runtime_types)
            preferred_tiers = [
                t for t in candidates
                if _TIER_RUNTIME_TYPE.get(t) in preferred_set
            ]
            other_tiers = [
                t for t in candidates
                if _TIER_RUNTIME_TYPE.get(t) not in preferred_set
            ]
            candidates = preferred_tiers + other_tiers

        # Step 4: evaluate ALL candidates — collect rejections for all that fail,
        # then pick the first passing tier.
        tried: list[IsolationTier] = []
        rejections: dict[str, str] = {}
        selected: IsolationTier | None = None

        for tier in candidates:
            tried.append(tier)
            tier_name = tier.name

            # 4a. min_security_score check
            effective_score = TIER_SECURITY_SCORES[tier] + TIER_RISK_ADJUSTMENTS[tier]
            if effective_score < min_security_score:
                rejections[tier_name] = (
                    f"security_score {effective_score} < required {min_security_score}"
                )
                continue

            # 4b. required_capabilities check
            if required_capabilities:
                caps = TIER_CAPABILITIES[tier]
                missing = [
                    cap for cap in required_capabilities
                    if not getattr(caps, cap, False)
                ]
                if missing:
                    rejections[tier_name] = (
                        f"missing required capabilities: {missing}"
                    )
                    continue

            # 4c. Policy rules
            rejection = self._check_policy(
                tier=tier,
                policy=policy,
                requested_tier=requested_tier,
                required_capabilities=required_capabilities,
            )
            if rejection is not None:
                rejections[tier_name] = rejection
                continue

            # All checks passed — record as winner (first one wins), but keep
            # iterating so we accumulate rejection reasons for the rest.
            if selected is None:
                selected = tier

        if selected is not None:
            return selected, tried, rejections

        # No candidate passed — raise with informative message
        raise IsolationUnavailableError(
            f"No isolation tier satisfies all constraints. "
            f"policy={policy.value!r}, "
            f"min_security_score={min_security_score}, "
            f"available_tiers={list(snapshot.available_tiers)}, "
            f"rejections={rejections}"
        )

    # ------------------------------------------------------------------
    # Internal: policy filter
    # ------------------------------------------------------------------

    def _check_policy(
        self,
        tier: IsolationTier,
        policy: IsolationPolicy,
        requested_tier: IsolationTier | None,
        required_capabilities: set[str] | None,
    ) -> str | None:
        """
        Return a rejection reason string if the tier violates the policy,
        or None if it passes.
        """
        if policy == IsolationPolicy.NO_FALLBACK:
            if requested_tier is not None and tier != requested_tier:
                return (
                    f"NO_FALLBACK policy requires exact tier {requested_tier.name!r}, "
                    f"got {tier.name!r}"
                )

        elif policy == IsolationPolicy.STRICT_ISOLATION:
            if tier not in (IsolationTier.FIRECRACKER, IsolationTier.QEMU):
                return (
                    f"STRICT_ISOLATION policy requires FIRECRACKER or QEMU, "
                    f"got {tier.name!r}"
                )

        elif policy == IsolationPolicy.SAFE_DEGRADATION:
            # Reject SANDBOX or PROCESS_JAIL when network isolation is required
            if tier > IsolationTier.DOCKER_HARDENED:
                if required_capabilities and "supports_network_isolation" in required_capabilities:
                    return (
                        f"SAFE_DEGRADATION policy rejects {tier.name!r} "
                        f"when supports_network_isolation is required"
                    )

        # BEST_AVAILABLE: no additional policy filter
        return None
