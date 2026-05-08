from __future__ import annotations
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger
from core.isolation_abstraction.isolation_driver import IsolationTier, RuntimeLifecycleState
from core.vm_isolation.vm_policy_engine import VMProfile


class VMLifecycleTracker:
    """
    Tracks VM state transitions in memory + persists to nexus_vm_isolation.db.
    Thread-safe. In-memory cache for fast lookups.
    """

    def __init__(self, audit_logger: Optional[IsolationAuditLogger] = None) -> None:
        self._logger = audit_logger or IsolationAuditLogger()
        self._states: dict[str, RuntimeLifecycleState] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        vm_id: str,
        tier: IsolationTier,
        profile: VMProfile,
        agent_id: str,
        security_score: int,
        risk_adjusted_score: int,
        fallback_level: int = 0,
    ) -> str:
        session_id = str(uuid.uuid4())
        with self._lock:
            self._states[vm_id] = RuntimeLifecycleState.RUNNING
        self._logger.log_vm_created(
            vm_id=vm_id,
            session_id=session_id,
            tier=tier.name,
            agent_id=agent_id,
            security_score=security_score,
            risk_adjusted_score=risk_adjusted_score,
            fallback_level=fallback_level,
        )
        self._logger.log_event(
            vm_id=vm_id,
            event_type="VM_CREATED",
            severity="INFO",
            description=f"profile={profile.value} tier={tier.name}",
            metadata={
                "session_id": session_id,
                "profile": profile.value,
                "tier": tier.name,
                "security_score": security_score,
                "fallback_level": fallback_level,
            },
            origin_component="vm_lifecycle_tracker",
        )
        return session_id

    def transition(
        self,
        vm_id: str,
        new_state: RuntimeLifecycleState,
        reason: str = "",
    ) -> None:
        with self._lock:
            old_state = self._states.get(vm_id, RuntimeLifecycleState.CREATED)
            self._states[vm_id] = new_state
        severity = "WARNING" if new_state in (
            RuntimeLifecycleState.QUARANTINED, RuntimeLifecycleState.FAILED
        ) else "INFO"
        self._logger.log_event(
            vm_id=vm_id,
            event_type="STATE_TRANSITION",
            severity=severity,
            description=f"{old_state.value} -> {new_state.value}",
            metadata={"old_state": old_state.value, "new_state": new_state.value, "reason": reason},
            origin_component="vm_lifecycle_tracker",
        )
        if new_state == RuntimeLifecycleState.DESTROYED:
            self._logger.log_vm_destroyed(vm_id)

    def get_state(self, vm_id: str) -> Optional[RuntimeLifecycleState]:
        with self._lock:
            return self._states.get(vm_id)

    def list_active(self) -> list[dict]:
        """Returns VMs not in DESTROYED or FAILED state (from DB)."""
        try:
            with sqlite3.connect(str(self._logger._db)) as conn:
                rows = conn.execute(
                    "SELECT vm_id, tier, status, security_score, agent_id "
                    "FROM virtual_machines WHERE status NOT IN ('DESTROYED', 'FAILED') "
                    "ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            return [
                {"vm_id": r[0], "tier": r[1], "status": r[2],
                 "security_score": r[3], "agent_id": r[4]}
                for r in rows
            ]
        except Exception:
            return []
