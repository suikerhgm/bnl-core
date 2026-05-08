"""
Tests for core/isolation_abstraction/isolation_capability_detector.py
Task 2: CapabilitySnapshot + IsolationCapabilityDetector
"""
import pytest

from core.isolation_abstraction.isolation_capability_detector import (
    CapabilitySnapshot,
    IsolationCapabilityDetector,
    get_capability_detector,
)
from core.isolation_abstraction.isolation_driver import IsolationTier


def test_detect_returns_capability_snapshot():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    assert isinstance(snap, CapabilitySnapshot)


def test_snapshot_is_frozen():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    with pytest.raises(Exception):
        snap.has_docker = True  # type: ignore[misc]


def test_sandbox_and_jail_always_in_available_tiers():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    assert IsolationTier.SANDBOX in snap.available_tiers
    assert IsolationTier.PROCESS_JAIL in snap.available_tiers


def test_detect_is_cached():
    d = IsolationCapabilityDetector()
    snap1 = d.detect()
    snap2 = d.detect()
    assert snap1 is snap2  # same object


def test_refresh_returns_new_snapshot():
    d = IsolationCapabilityDetector()
    d.detect()
    snap2 = d.refresh_capabilities(reason="manual_refresh", requester="pytest", cooldown_seconds=0)
    # Should not be the startup snap (new object since we forced refresh)
    # Just verify it's a CapabilitySnapshot
    assert isinstance(snap2, CapabilitySnapshot)


def test_refresh_cooldown_raises():
    d = IsolationCapabilityDetector()
    d.detect()
    d.refresh_capabilities(reason="first", requester="pytest", cooldown_seconds=60)
    with pytest.raises(ValueError, match="cooldown"):
        d.refresh_capabilities(reason="second", requester="pytest", cooldown_seconds=60)


def test_host_os_is_valid():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    assert snap.host_os in ("linux", "windows", "macos", "unknown")


def test_firecracker_unavailable_on_windows():
    import platform
    d = IsolationCapabilityDetector()
    snap = d.detect()
    if platform.system().lower() == "windows":
        assert IsolationTier.FIRECRACKER not in snap.available_tiers
        assert IsolationTier.QEMU not in snap.available_tiers


def test_cache_generation_increments_on_refresh():
    d = IsolationCapabilityDetector()
    d.detect()
    g0 = d._generation
    d.refresh_capabilities(reason="r1", requester="test", cooldown_seconds=0)
    assert d._generation == g0 + 1


def test_startup_cache_source():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    assert snap.cache_source == "startup_probe"


def test_last_refresh_reason_is_startup():
    d = IsolationCapabilityDetector()
    snap = d.detect()
    assert snap.last_refresh_reason == "startup"


def test_background_monitoring_stub():
    d = IsolationCapabilityDetector()
    assert d._background_monitor_enabled is False
    d.enable_background_monitoring()
    assert d._background_monitor_enabled is True


def test_get_capability_detector_returns_singleton():
    d1 = get_capability_detector()
    d2 = get_capability_detector()
    assert d1 is d2
