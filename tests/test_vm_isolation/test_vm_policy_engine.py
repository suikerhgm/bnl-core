import pytest
from core.vm_isolation.vm_policy_engine import (
    VMProfile, VMPolicy, VMPolicyEngine, PROFILE_POLICIES,
)


def test_vm_profiles_exist():
    assert VMProfile.SAFE_VM.value == "safe_vm"
    assert VMProfile.RESTRICTED_VM.value == "restricted_vm"
    assert VMProfile.QUARANTINE_VM.value == "quarantine_vm"
    assert VMProfile.LOCKDOWN_VM.value == "lockdown_vm"


def test_vm_policy_is_frozen():
    p = PROFILE_POLICIES[VMProfile.SAFE_VM]
    with pytest.raises(Exception):
        p.allow_host_mounts = True


def test_safe_vm_policy_values():
    p = PROFILE_POLICIES[VMProfile.SAFE_VM]
    assert p.allow_host_mounts is False
    assert p.allow_shared_memory is False
    assert p.readonly_boot_layer is True
    assert p.disposable_disk is True
    assert p.auto_destroy_on_exit is True
    assert p.minimum_security_score == 60


def test_lockdown_vm_max_restrictions():
    p = PROFILE_POLICIES[VMProfile.LOCKDOWN_VM]
    assert p.allow_host_mounts is False
    assert p.allow_outbound_network is False
    assert p.minimum_security_score == 90
    assert "qemu" in p.forbidden_runtime_types


def test_quarantine_vm_no_network():
    p = PROFILE_POLICIES[VMProfile.QUARANTINE_VM]
    assert p.allow_outbound_network is False
    assert p.auto_destroy_on_exit is False  # forensic preservation


def test_policy_engine_get_policy():
    engine = VMPolicyEngine()
    p = engine.get_policy(VMProfile.SAFE_VM)
    assert isinstance(p, VMPolicy)
    assert p.profile == VMProfile.SAFE_VM


def test_policy_engine_validate_tier_passes():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    ok, reason = engine.validate_tier(IsolationTier.DOCKER_HARDENED, VMProfile.SAFE_VM)
    assert ok is True
    assert reason is None


def test_policy_engine_validate_tier_fails_lockdown_score():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    ok, reason = engine.validate_tier(IsolationTier.SANDBOX, VMProfile.LOCKDOWN_VM)
    assert ok is False
    assert reason is not None


def test_policy_engine_validate_tier_fails_forbidden():
    from core.isolation_abstraction.isolation_driver import IsolationTier
    engine = VMPolicyEngine()
    ok, reason = engine.validate_tier(IsolationTier.QEMU, VMProfile.LOCKDOWN_VM)
    assert ok is False
    assert "forbidden" in reason.lower()


def test_all_profiles_have_policies():
    for profile in VMProfile:
        assert profile in PROFILE_POLICIES
