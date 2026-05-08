import pytest
from core.vm_isolation.vm_escape_detector import (
    VMEscapeDetector, EscapeSignal, EscapeSignalType, EscapeSeverity,
)


def test_escape_signal_types_exist():
    assert EscapeSignalType.HYPERVISOR_PROBE.value == "hypervisor_probe"
    assert EscapeSignalType.DOCKER_SOCKET_PROBE.value == "docker_socket_probe"
    assert EscapeSignalType.NAMESPACE_ESCAPE.value == "namespace_escape"
    assert EscapeSignalType.SIDE_CHANNEL_PROBE.value == "side_channel_probe"
    assert EscapeSignalType.DEVICE_ENUMERATION.value == "device_enumeration"


def test_escape_signal_dataclass():
    sig = EscapeSignal(
        vm_id="vm-test",
        signal_type=EscapeSignalType.HYPERVISOR_PROBE,
        severity=EscapeSeverity.HIGH,
        evidence={"detail": "probe detected"},
        detection_method="heuristic",
    )
    assert sig.vm_id == "vm-test"
    assert sig.severity == EscapeSeverity.HIGH
    assert isinstance(sig.evidence, dict)


def test_check_hypervisor_probing_benign_returns_empty():
    detector = VMEscapeDetector()
    signals = detector.check_hypervisor_probing("vm-test", {})
    assert signals == []


def test_check_hypervisor_probing_detects_flag():
    detector = VMEscapeDetector()
    signals = detector.check_hypervisor_probing("vm-test", {"suspicious_hypercalls": True})
    assert len(signals) == 1
    assert signals[0].signal_type == EscapeSignalType.HYPERVISOR_PROBE
    assert signals[0].severity == EscapeSeverity.HIGH


def test_check_docker_socket_returns_list():
    detector = VMEscapeDetector()
    signals = detector.check_docker_socket_access("vm-test")
    assert isinstance(signals, list)


def test_check_namespace_escape_detects_violation():
    detector = VMEscapeDetector()
    signals = detector.check_namespace_escape("vm-test", {"namespace_violation": True})
    assert len(signals) == 1
    assert signals[0].signal_type == EscapeSignalType.NAMESPACE_ESCAPE
    assert signals[0].severity == EscapeSeverity.CRITICAL


def test_scan_all_returns_list():
    detector = VMEscapeDetector()
    signals = detector.scan_all("vm-test", runtime_metadata={})
    assert isinstance(signals, list)
    for s in signals:
        assert isinstance(s, EscapeSignal)


def test_scan_all_with_suspicious_metadata():
    detector = VMEscapeDetector()
    signals = detector.scan_all("vm-test", runtime_metadata={"suspicious_hypercalls": True})
    assert len(signals) >= 1
    assert any(s.signal_type == EscapeSignalType.HYPERVISOR_PROBE for s in signals)
