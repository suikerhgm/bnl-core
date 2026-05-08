"""
isolation_capability_detector.py — CapabilitySnapshot + IsolationCapabilityDetector
Task 2 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: ONLY stdlib imports + core.isolation_abstraction.isolation_driver.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.isolation_abstraction.isolation_driver import IsolationTier


# Cache source normalization
_CACHE_SOURCE_MAP = {
    "startup": "startup_probe",
    "manual_refresh": "manual_refresh",
    "docker_restart": "manual_refresh",
    "healthcheck_failure": "background_healthcheck",
    "background_healthcheck": "background_healthcheck",
}


# ---------------------------------------------------------------------------
# CapabilitySnapshot (frozen dataclass)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilitySnapshot:
    has_firecracker: bool
    has_qemu: bool
    has_kvm: bool
    has_docker: bool
    has_wsl2: bool
    has_nested_virtualization: bool
    host_os: str                      # "linux" | "windows" | "macos" | "unknown"
    docker_runtime: Optional[str]     # "docker" | "containerd" | "podman" | None
    virtualization_type: Optional[str]  # "kvm" | "hyperv" | "wsl2" | "qemu" | "firecracker" | None
    last_refresh_reason: Optional[str]  # "startup" | "manual_refresh" | "docker_restart" | "healthcheck_failure"
    available_tiers: frozenset        # frozenset[IsolationTier]
    detected_at: datetime
    # Cache metadata
    cache_health_score: float         # 0–100, degrades if probes fail — for now always 100.0
    cache_source: str                 # "startup_probe" | "manual_refresh" | "background_healthcheck"
    cache_generation: int             # increments on each refresh


# ---------------------------------------------------------------------------
# IsolationCapabilityDetector
# ---------------------------------------------------------------------------

class IsolationCapabilityDetector:
    """Thread-safe singleton-ready capability detector."""

    def __init__(self) -> None:
        self._cache: Optional[CapabilitySnapshot] = None
        self._cache_lock = threading.Lock()
        self._last_refresh_at: Optional[datetime] = None
        self._generation: int = 0
        self._background_monitor_enabled: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self) -> CapabilitySnapshot:
        """
        Run once at startup, cached. Thread-safe. reason='startup'.
        Subsequent calls return the cached snapshot (same object).
        """
        if self._cache is not None:
            return self._cache
        with self._cache_lock:
            # Double-checked locking
            if self._cache is None:
                self._cache = self._probe(reason="startup")
                # NOTE: _last_refresh_at is intentionally NOT set here.
                # The cooldown in refresh_capabilities only applies between
                # consecutive explicit refresh calls, not to the initial detect().
        return self._cache

    def refresh_capabilities(
        self,
        reason: str,
        requester: str,
        cooldown_seconds: int = 30,
    ) -> CapabilitySnapshot:
        """
        Force re-probe. Rate-limited by cooldown_seconds.
        Raises ValueError if called within cooldown window.
        """
        with self._cache_lock:
            if cooldown_seconds > 0 and self._last_refresh_at is not None:
                elapsed = (datetime.now(timezone.utc) - self._last_refresh_at).total_seconds()
                if elapsed < cooldown_seconds:
                    raise ValueError(
                        f"refresh_capabilities called within cooldown window "
                        f"({elapsed:.1f}s < {cooldown_seconds}s). "
                        f"requester={requester!r}, reason={reason!r}"
                    )
            self._generation += 1
            snap = self._probe(reason=reason)
            self._cache = snap
            self._last_refresh_at = snap.detected_at
        return snap

    def enable_background_monitoring(self, interval_seconds: int = 60) -> None:
        """
        Future stub. Sets self._background_monitor_enabled = True.
        Does NOT start a thread yet.
        """
        self._background_monitor_enabled = True

    # ------------------------------------------------------------------
    # Internal probe
    # ------------------------------------------------------------------

    def _probe(self, reason: str) -> CapabilitySnapshot:
        """Probe the host environment and build a CapabilitySnapshot."""
        health_score = 100.0  # Starts at 100, degrades on probe failures

        # host_os
        system = platform.system().lower()
        if system == "linux":
            host_os = "linux"
        elif system == "windows":
            host_os = "windows"
        elif system == "darwin":
            host_os = "macos"
        else:
            host_os = "unknown"

        # has_kvm: only meaningful on Linux
        has_kvm = (host_os == "linux") and Path("/dev/kvm").exists()

        # has_firecracker: binary present AND kvm available
        has_firecracker = (shutil.which("firecracker") is not None) and has_kvm

        # has_qemu: binary present AND kvm available
        has_qemu = (shutil.which("qemu-system-x86_64") is not None) and has_kvm

        # has_docker: docker info returns 0
        # With health degradation on timeout
        has_docker = False
        docker_runtime: Optional[str] = None
        try:
            result = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            has_docker = result.returncode == 0
            if has_docker:
                docker_runtime = "docker"
        except subprocess.TimeoutExpired:
            health_score -= 15.0  # docker exists but is unresponsive
        except Exception:
            pass  # not installed — not a health degradation, just unavailable

        # has_wsl2
        has_wsl2 = False
        if host_os == "linux":
            try:
                proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
                has_wsl2 = "microsoft" in proc_version.lower()
            except Exception:
                has_wsl2 = False
        if "WSL_DISTRO_NAME" in os.environ:
            has_wsl2 = True

        # virtualization_type
        if has_kvm:
            virtualization_type: Optional[str] = "kvm"
        elif host_os == "windows":
            virtualization_type = "hyperv"
        elif has_wsl2:
            virtualization_type = "wsl2"
        else:
            virtualization_type = None

        # has_nested_virtualization — not separately probed; derive from kvm
        has_nested_virtualization = has_kvm

        # available_tiers — always SANDBOX + PROCESS_JAIL
        tiers: set[IsolationTier] = {IsolationTier.SANDBOX, IsolationTier.PROCESS_JAIL}
        if has_docker:
            tiers.add(IsolationTier.DOCKER_HARDENED)
        if has_qemu:
            tiers.add(IsolationTier.QEMU)
        if has_firecracker:
            tiers.add(IsolationTier.FIRECRACKER)

        # cache metadata — normalize cache_source
        cache_source = _CACHE_SOURCE_MAP.get(reason, "manual_refresh")

        return CapabilitySnapshot(
            has_firecracker=has_firecracker,
            has_qemu=has_qemu,
            has_kvm=has_kvm,
            has_docker=has_docker,
            has_wsl2=has_wsl2,
            has_nested_virtualization=has_nested_virtualization,
            host_os=host_os,
            docker_runtime=docker_runtime,
            virtualization_type=virtualization_type,
            last_refresh_reason=reason,
            available_tiers=frozenset(tiers),
            detected_at=datetime.now(timezone.utc),
            cache_health_score=max(0.0, health_score),
            cache_source=cache_source,
            cache_generation=self._generation,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_detector_instance: Optional[IsolationCapabilityDetector] = None
_detector_lock = threading.Lock()


def get_capability_detector() -> IsolationCapabilityDetector:
    """Return the process-wide singleton IsolationCapabilityDetector."""
    global _detector_instance
    if _detector_instance is None:
        with _detector_lock:
            if _detector_instance is None:
                _detector_instance = IsolationCapabilityDetector()
    return _detector_instance
