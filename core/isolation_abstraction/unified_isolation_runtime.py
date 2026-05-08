"""
unified_isolation_runtime.py — UnifiedIsolationRuntime
Task 9 of the Nexus BNL Isolation Abstraction Layer.

The ONLY public API for all isolation operations.
Responsibilities: negotiate → delegate to driver → audit.
Dependency rule: may import from all isolation_abstraction sub-modules + drivers.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
from core.isolation_abstraction.isolation_capability_detector import (
    get_capability_detector, CapabilitySnapshot,
)
from core.isolation_abstraction.isolation_driver import (
    IsolationDriver, IsolationTier, ExecutionPayload, ExecutionResult,
    RuntimeConfig, RuntimeHandle, RuntimeLifecycleState, ExecutionContext,
)
from core.isolation_abstraction.isolation_negotiator import (
    get_negotiator, NegotiationResult,
)
from core.isolation_abstraction.isolation_strategy_manager import (
    IsolationPolicy, IsolationUnavailableError,
)


class UnifiedIsolationRuntime:
    """
    SINGLETON. The only public API for all isolation operations.
    Callers never import from vm_isolation/, sandbox/, or isolation/ directly.
    Responsibilities: negotiate → delegate to driver → audit.
    """

    def __init__(self, audit_logger: Optional[IsolationAuditLogger] = None) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._detector = get_capability_detector()
        self._negotiator = get_negotiator()
        self._drivers: list[IsolationDriver] = self._build_driver_list()

    def _build_driver_list(self) -> list[IsolationDriver]:
        """Build driver list in tier order. Missing deps degrade gracefully."""
        drivers: list[IsolationDriver] = []
        # Tier 1: Firecracker
        try:
            from core.vm_isolation.firecracker_runtime import FirecrackerRuntime
            drivers.append(FirecrackerRuntime())
        except ImportError:
            pass
        # Tier 3: Docker hardened
        try:
            from core.isolation_abstraction.drivers.docker_hardened_driver import DockerHardenedDriver
            drivers.append(DockerHardenedDriver())
        except ImportError:
            pass
        # Tier 4: Sandbox
        try:
            from core.isolation_abstraction.drivers.sandbox_driver import SandboxDriver
            drivers.append(SandboxDriver())
        except ImportError:
            pass
        # Tier 5: ProcessJail — always available
        try:
            from core.isolation_abstraction.drivers.process_jail_driver import ProcessJailDriver
            drivers.append(ProcessJailDriver())
        except ImportError:
            pass
        return drivers

    def _get_driver(self, tier: IsolationTier) -> Optional[IsolationDriver]:
        for d in self._drivers:
            if d.tier == tier and d.is_available():
                return d
        return None

    async def execute_isolated(
        self,
        payload: ExecutionPayload,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        ctx: Optional[ExecutionContext] = None,
        required_tier: Optional[IsolationTier] = None,
        minimum_security_score: int = 0,
        requires_forensics: bool = False,
        requires_network_isolation: bool = False,
        requires_behavioral_lab: bool = False,
        requires_live_forensics: bool = False,
        preferred_runtime_types: Optional[list[str]] = None,
        forbidden_runtime_types: Optional[list[str]] = None,
    ) -> ExecutionResult:
        ctx = ctx or ExecutionContext()
        required_caps = self._build_required_caps(
            requires_forensics, requires_network_isolation,
            requires_behavioral_lab, requires_live_forensics,
        )
        snap = self._detector.detect()
        negotiation = self._negotiator.negotiate(
            snap, policy, required_tier,
            min_security_score=minimum_security_score,
            required_capabilities=required_caps or None,
            preferred_runtime_types=preferred_runtime_types,
            forbidden_runtime_types=forbidden_runtime_types,
        )
        driver = self._get_driver(negotiation.actual_tier)
        if driver is None:
            raise IsolationUnavailableError(
                f"Driver for {negotiation.actual_tier} not instantiated"
            )
        session_id = str(uuid.uuid4())
        config = RuntimeConfig(
            agent_id=ctx.execution_id,
            max_runtime_seconds=payload.timeout_seconds,
        )
        handle = await driver.create_runtime(config)
        self._logger.log_negotiation(session_id, handle.runtime_id, negotiation)
        self._logger.log_vm_created(
            vm_id=handle.runtime_id,
            session_id=session_id,
            tier=negotiation.actual_tier.name,
            agent_id=ctx.execution_id,
            security_score=negotiation.security_score,
            risk_adjusted_score=negotiation.risk_adjusted_score,
            fallback_level=negotiation.fallback_level,
        )

        # Log degradation telemetry if fallback occurred
        if negotiation.fallback_level > 0:
            self._log_degradation(negotiation, ctx)

        result = await driver.execute(handle, payload, ctx)
        result.negotiation = negotiation

        if ctx.preserve_forensics and result.runtime_state == RuntimeLifecycleState.QUARANTINED:
            await driver.quarantine(handle, "preserve_forensics")
        else:
            await driver.destroy(handle)
            self._logger.log_vm_destroyed(handle.runtime_id)

        self._logger.log_event(
            vm_id=handle.runtime_id,
            event_type="EXECUTION_COMPLETE",
            severity="INFO",
            description=f"tier={negotiation.actual_tier.name} success={result.success}",
            metadata={
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "fallback_level": negotiation.fallback_level,
            },
            correlation_id=ctx.correlation_id,
            origin_component="unified_isolation_runtime",
        )
        return result

    async def create_isolated_runtime(
        self,
        policy: IsolationPolicy = IsolationPolicy.BEST_AVAILABLE,
        minimum_security_score: int = 0,
        ctx: Optional[ExecutionContext] = None,
    ) -> RuntimeHandle:
        ctx = ctx or ExecutionContext()
        snap = self._detector.detect()
        negotiation = self._negotiator.negotiate(
            snap, policy, min_security_score=minimum_security_score,
        )
        driver = self._get_driver(negotiation.actual_tier)
        if driver is None:
            raise IsolationUnavailableError(
                f"Driver for {negotiation.actual_tier} not instantiated"
            )
        config = RuntimeConfig(agent_id=ctx.execution_id)
        handle = await driver.create_runtime(config)
        self._logger.log_event(
            vm_id=handle.runtime_id,
            event_type="RUNTIME_CREATED",
            severity="INFO",
            description=f"tier={negotiation.actual_tier.name}",
            metadata={"tier": negotiation.actual_tier.name, "policy": policy.value},
            correlation_id=ctx.correlation_id,
            origin_component="unified_isolation_runtime",
        )
        return handle

    async def destroy_runtime(self, handle: RuntimeHandle) -> None:
        driver = self._get_driver(handle.tier)
        if driver:
            await driver.destroy(handle)
            self._logger.log_vm_destroyed(handle.runtime_id)

    def refresh_capabilities(self, reason: str = "manual_refresh") -> CapabilitySnapshot:
        try:
            return self._detector.refresh_capabilities(
                reason=reason, requester="unified_runtime"
            )
        except ValueError:
            return self._detector.detect()

    def get_negotiation_history(self, limit: int = 100) -> list[dict]:
        import sqlite3
        try:
            with sqlite3.connect(str(self._logger._db)) as conn:
                rows = conn.execute(
                    "SELECT session_id, vm_id, actual_tier, policy, "
                    "negotiation_result, started_at "
                    "FROM vm_sessions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"session_id": r[0], "vm_id": r[1], "actual_tier": r[2],
                 "policy": r[3], "negotiation": r[4], "started_at": r[5]}
                for r in rows
            ]
        except Exception:
            return []

    # ── Future hook (Plan C) ─────────────────────────────────────────────────

    async def execute_on_remote_node(
        self,
        node_id: str,
        payload: ExecutionPayload,
        ctx: Optional[ExecutionContext] = None,
    ) -> ExecutionResult:
        """Future: routes to a remote Linux isolation node."""
        raise NotImplementedError("remote_execution — Plan C")

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_required_caps(
        forensics: bool,
        network: bool,
        behavioral: bool,
        live_forensics: bool,
    ) -> set[str]:
        caps: set[str] = set()
        if forensics:
            caps.add("supports_forensics")
        if network:
            caps.add("supports_network_isolation")
        if behavioral:
            caps.add("supports_behavioral_lab")
        if live_forensics:
            caps.add("supports_live_forensics")
        return caps

    def _log_degradation(self, negotiation: NegotiationResult, ctx: ExecutionContext) -> None:
        self._logger.log_event(
            vm_id="system",
            event_type="DEGRADATION",
            severity="WARNING",
            description=(
                f"Requested {negotiation.requested_tier}, "
                f"got {negotiation.actual_tier.name} "
                f"(level={negotiation.fallback_level})"
            ),
            metadata={
                "original_requested": (
                    negotiation.requested_tier.name if negotiation.requested_tier else None
                ),
                "actual": negotiation.actual_tier.name,
                "fallback_level": negotiation.fallback_level,
                "fallback_chain": [t.name for t in negotiation.fallback_chain],
                "policy": negotiation.policy.value,
            },
            correlation_id=ctx.correlation_id,
            origin_component="unified_isolation_runtime",
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_runtime_instance: Optional[UnifiedIsolationRuntime] = None
_runtime_lock = threading.Lock()


def get_unified_runtime() -> UnifiedIsolationRuntime:
    global _runtime_instance
    if _runtime_instance is None:
        with _runtime_lock:
            if _runtime_instance is None:
                _runtime_instance = UnifiedIsolationRuntime()
    return _runtime_instance
