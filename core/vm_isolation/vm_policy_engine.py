from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from core.isolation_abstraction.isolation_driver import (
    IsolationTier, TIER_SECURITY_SCORES, TIER_RISK_ADJUSTMENTS,
)


class VMProfile(str, Enum):
    SAFE_VM       = "safe_vm"
    RESTRICTED_VM = "restricted_vm"
    QUARANTINE_VM = "quarantine_vm"
    LOCKDOWN_VM   = "lockdown_vm"


@dataclass(frozen=True)
class VMPolicy:
    profile: VMProfile
    allow_host_mounts: bool
    allow_outbound_network: bool
    allow_shared_memory: bool
    readonly_boot_layer: bool
    disposable_disk: bool
    encrypted_runtime_storage: bool
    max_cpu_percent: float
    max_ram_mb: int
    max_runtime_seconds: int
    auto_destroy_on_exit: bool
    minimum_security_score: int
    allowed_runtime_types: frozenset
    forbidden_runtime_types: frozenset


_TIER_RUNTIME_TYPE = {
    IsolationTier.FIRECRACKER:     "firecracker",
    IsolationTier.QEMU:            "qemu",
    IsolationTier.DOCKER_HARDENED: "docker",
    IsolationTier.SANDBOX:         "sandbox",
    IsolationTier.PROCESS_JAIL:    "jail",
}

PROFILE_POLICIES: dict[VMProfile, VMPolicy] = {
    VMProfile.SAFE_VM: VMPolicy(
        profile=VMProfile.SAFE_VM,
        allow_host_mounts=False, allow_outbound_network=True,
        allow_shared_memory=False, readonly_boot_layer=True,
        disposable_disk=True, encrypted_runtime_storage=False,
        max_cpu_percent=50.0, max_ram_mb=512, max_runtime_seconds=300,
        auto_destroy_on_exit=True, minimum_security_score=60,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker", "sandbox", "jail"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.RESTRICTED_VM: VMPolicy(
        profile=VMProfile.RESTRICTED_VM,
        allow_host_mounts=False, allow_outbound_network=False,
        allow_shared_memory=False, readonly_boot_layer=True,
        disposable_disk=True, encrypted_runtime_storage=True,
        max_cpu_percent=25.0, max_ram_mb=256, max_runtime_seconds=120,
        auto_destroy_on_exit=True, minimum_security_score=70,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.QUARANTINE_VM: VMPolicy(
        profile=VMProfile.QUARANTINE_VM,
        allow_host_mounts=False, allow_outbound_network=False,
        allow_shared_memory=False, readonly_boot_layer=True,
        disposable_disk=True, encrypted_runtime_storage=True,
        max_cpu_percent=10.0, max_ram_mb=128, max_runtime_seconds=60,
        auto_destroy_on_exit=False,  # preserve for forensics
        minimum_security_score=70,
        allowed_runtime_types=frozenset({"firecracker", "qemu", "docker"}),
        forbidden_runtime_types=frozenset(),
    ),
    VMProfile.LOCKDOWN_VM: VMPolicy(
        profile=VMProfile.LOCKDOWN_VM,
        allow_host_mounts=False, allow_outbound_network=False,
        allow_shared_memory=False, readonly_boot_layer=True,
        disposable_disk=True, encrypted_runtime_storage=True,
        max_cpu_percent=10.0, max_ram_mb=128, max_runtime_seconds=60,
        auto_destroy_on_exit=False,  # preserve for forensics
        minimum_security_score=90,
        allowed_runtime_types=frozenset({"firecracker"}),
        forbidden_runtime_types=frozenset({"qemu"}),
    ),
}


class VMPolicyEngine:
    """Validates tiers against VM profiles. Stateless."""

    def get_policy(self, profile: VMProfile) -> VMPolicy:
        return PROFILE_POLICIES[profile]

    def validate_tier(
        self,
        tier: IsolationTier,
        profile: VMProfile,
    ) -> Tuple[bool, Optional[str]]:
        """Returns (valid, rejection_reason). reason is None if valid."""
        policy = PROFILE_POLICIES[profile]
        runtime_type = _TIER_RUNTIME_TYPE[tier]

        if runtime_type in policy.forbidden_runtime_types:
            return False, f"runtime type '{runtime_type}' is forbidden for {profile.value}"

        if policy.allowed_runtime_types and runtime_type not in policy.allowed_runtime_types:
            return False, f"runtime type '{runtime_type}' not in allowed set for {profile.value}"

        effective_score = TIER_SECURITY_SCORES[tier] + TIER_RISK_ADJUSTMENTS[tier]
        if effective_score < policy.minimum_security_score:
            return False, (
                f"security score {effective_score} < minimum {policy.minimum_security_score} "
                f"for {profile.value}"
            )

        return True, None
