"""
isolation_audit_logger.py — IsolationAuditLogger + full DB schema
Task 8 of the Nexus BNL Isolation Abstraction Layer.

Dependency rule: ONLY stdlib. NegotiationResult imported under TYPE_CHECKING only.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.isolation_abstraction.isolation_negotiator import NegotiationResult

_DEFAULT_DB = Path("data/nexus_vm_isolation.db")

# ---------------------------------------------------------------------------
# DDL — 8 tables + indexes
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS virtual_machines (
    vm_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    tier TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_tier TEXT,
    fallback_level INTEGER DEFAULT 0,
    security_score INTEGER,
    risk_adjusted_score INTEGER,
    node_id TEXT,
    cluster_id TEXT,
    remote_runtime BOOLEAN DEFAULT FALSE,
    created_at TEXT,
    destroyed_at TEXT,
    agent_id TEXT
);

CREATE TABLE IF NOT EXISTS vm_sessions (
    session_id TEXT PRIMARY KEY,
    vm_id TEXT,
    requested_tier TEXT,
    actual_tier TEXT,
    policy TEXT,
    negotiation_result TEXT,
    candidate_drivers TEXT,
    rejection_reasons TEXT,
    capability_mismatches TEXT,
    policy_rejections TEXT,
    execution_duration_ms INTEGER,
    actual_runtime_health TEXT,
    post_execution_anomalies TEXT,
    degradation_impact TEXT,
    started_at TEXT,
    ended_at TEXT,
    exit_reason TEXT
);

CREATE TABLE IF NOT EXISTS vm_events (
    event_id TEXT PRIMARY KEY,
    vm_id TEXT,
    event_type TEXT,
    severity TEXT,
    description TEXT,
    metadata TEXT,
    correlation_id TEXT,
    runtime_chain_id TEXT,
    origin_layer TEXT,
    origin_component TEXT,
    timestamp TEXT,
    row_hash TEXT,
    prev_hash TEXT
);

CREATE TABLE IF NOT EXISTS vm_escape_attempts (
    attempt_id TEXT PRIMARY KEY,
    vm_id TEXT,
    signal_type TEXT,
    detection_method TEXT,
    evidence TEXT,
    side_channel_indicators TEXT,
    vm_fingerprinting_detected BOOLEAN,
    hypervisor_api_abuse BOOLEAN,
    timing_anomaly_detected BOOLEAN,
    severity TEXT,
    response_action TEXT,
    forensic_snapshot_id TEXT,
    partial_failure_tracking TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS vm_policies (
    policy_id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    definition TEXT NOT NULL,
    minimum_security_score INTEGER,
    allowed_runtime_types TEXT,
    forbidden_runtime_types TEXT,
    minimum_required_capabilities TEXT,
    version INTEGER DEFAULT 1,
    signature TEXT,
    created_at TEXT,
    superseded_at TEXT
);

CREATE TABLE IF NOT EXISTS vm_forensics (
    forensic_id TEXT PRIMARY KEY,
    vm_id TEXT,
    session_id TEXT,
    timeline TEXT,
    process_tree TEXT,
    network_flows TEXT,
    filesystem_diff TEXT,
    memory_hashes TEXT,
    runtime_entropy_score REAL,
    suspicious_api_sequences TEXT,
    behavioral_anomaly_score REAL,
    cross_runtime_correlations TEXT,
    attack_graph TEXT,
    repeated_behavioral_fingerprints TEXT,
    shared_anomaly_signatures TEXT,
    campaign_correlation_id TEXT,
    memory_metadata TEXT,
    escape_signals TEXT,
    hypervisor_alerts TEXT,
    risk_score INTEGER,
    preserved_at TEXT,
    trigger TEXT
);

CREATE TABLE IF NOT EXISTS vm_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    vm_id TEXT,
    snapshot_type TEXT,
    state_path TEXT,
    manifest_hash TEXT,
    parent_snapshot_id TEXT,
    is_secure_boot_verified BOOLEAN,
    tpm_measurement TEXT,
    attestation_report TEXT,
    created_at TEXT,
    restored_at TEXT
);

CREATE TABLE IF NOT EXISTS vm_runtime_metrics (
    metric_id TEXT PRIMARY KEY,
    vm_id TEXT,
    cpu_percent REAL,
    ram_mb REAL,
    disk_io_kbps REAL,
    network_kbps REAL,
    process_count INTEGER,
    entropy_score REAL,
    crypto_mining_score REAL,
    burst_detected BOOLEAN,
    scheduler_latency_ms REAL,
    hypervisor_pressure_score REAL,
    isolation_stability_score REAL,
    anomaly_flags TEXT,
    timestamp TEXT
);

CREATE INDEX IF NOT EXISTS idx_vm_events_vm_id ON vm_events(vm_id);
CREATE INDEX IF NOT EXISTS idx_vm_events_severity ON vm_events(severity);
CREATE INDEX IF NOT EXISTS idx_vm_events_timestamp ON vm_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_vm_events_correlation ON vm_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_vm_sessions_vm_id ON vm_sessions(vm_id);
CREATE INDEX IF NOT EXISTS idx_virtual_machines_status ON virtual_machines(status);
CREATE INDEX IF NOT EXISTS idx_virtual_machines_agent ON virtual_machines(agent_id);
"""


# ---------------------------------------------------------------------------
# IsolationAuditLogger
# ---------------------------------------------------------------------------

class IsolationAuditLogger:
    """Append-only, hash-chained SQLite audit logger. Thread-safe."""

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self._db = db_path
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev_hash: Optional[str] = None
        with sqlite3.connect(str(self._db)) as conn:
            conn.executescript(_DDL)   # creates all 8 tables + indexes
        self._prev_hash = self._load_last_hash()

    def _load_last_hash(self) -> Optional[str]:
        try:
            with sqlite3.connect(str(self._db)) as conn:
                row = conn.execute(
                    "SELECT row_hash FROM vm_events ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def _canonical(self, data: dict) -> str:
        """Deterministic JSON — sorted keys, no whitespace, ASCII-safe."""
        return json.dumps(data, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, default=str)

    def log_event(
        self,
        vm_id: str,
        event_type: str,
        severity: str,
        description: str,
        metadata: dict,
        correlation_id: Optional[str] = None,
        runtime_chain_id: Optional[str] = None,
        origin_layer: str = "isolation_abstraction",
        origin_component: Optional[str] = None,
    ) -> str:
        """Append a hash-chained event row. Returns event_id."""
        with self._lock:
            event_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            event_dict = {
                "event_id": event_id,
                "vm_id": vm_id,
                "event_type": event_type,
                "severity": severity,
                "description": description,
                "metadata": metadata,
                "timestamp": now,
                "prev_hash": self._prev_hash or "",
            }
            raw = self._canonical(event_dict)
            row_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    """INSERT INTO vm_events
                    (event_id, vm_id, event_type, severity, description, metadata,
                     correlation_id, runtime_chain_id, origin_layer, origin_component,
                     timestamp, row_hash, prev_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, vm_id, event_type, severity, description,
                     self._canonical(metadata),
                     correlation_id, runtime_chain_id, origin_layer, origin_component,
                     now, row_hash, self._prev_hash),
                )
            self._prev_hash = row_hash
            return event_id

    def log_negotiation(
        self,
        session_id: str,
        vm_id: Optional[str],
        result: "NegotiationResult",
    ) -> None:
        """Write negotiation result to vm_sessions."""
        with self._lock:
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO vm_sessions
                    (session_id, vm_id, requested_tier, actual_tier, policy,
                     negotiation_result, candidate_drivers, rejection_reasons,
                     capability_mismatches, policy_rejections, started_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        session_id,
                        vm_id,
                        result.requested_tier.name if result.requested_tier else None,
                        result.actual_tier.name,
                        result.policy.value,
                        self._canonical({
                            "reason": result.reason,
                            "fallback_level": result.fallback_level,
                            "security_score": result.security_score,
                            "risk_adjusted_score": result.risk_adjusted_score,
                            "negotiation_id": result.negotiation_id,
                            "decision_entropy": result.decision_entropy,
                            "selection_confidence": result.selection_confidence,
                        }),
                        self._canonical([t.name for t in result.candidate_drivers]),
                        self._canonical(result.rejection_reasons),
                        self._canonical(result.capability_mismatches),
                        self._canonical(result.policy_rejections),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def log_vm_created(
        self,
        vm_id: str,
        session_id: str,
        tier: str,
        agent_id: str,
        security_score: int,
        risk_adjusted_score: int,
        fallback_level: int = 0,
    ) -> None:
        """Register a VM in virtual_machines table."""
        with self._lock:
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO virtual_machines
                    (vm_id, session_id, profile, tier, status, security_score,
                     risk_adjusted_score, fallback_level, agent_id, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (vm_id, session_id, "safe", tier, "RUNNING",
                     security_score, risk_adjusted_score, fallback_level,
                     agent_id, datetime.now(timezone.utc).isoformat()),
                )

    def log_vm_destroyed(self, vm_id: str) -> None:
        with self._lock:
            with sqlite3.connect(str(self._db)) as conn:
                conn.execute(
                    "UPDATE virtual_machines SET status='DESTROYED', destroyed_at=? WHERE vm_id=?",
                    (datetime.now(timezone.utc).isoformat(), vm_id),
                )

    def verify_chain(self) -> bool:
        """Returns True if the hash chain is unbroken and untampered."""
        try:
            with sqlite3.connect(str(self._db)) as conn:
                rows = list(conn.execute(
                    "SELECT event_id, vm_id, event_type, severity, description, "
                    "metadata, timestamp, row_hash, prev_hash "
                    "FROM vm_events ORDER BY timestamp ASC"
                ))
        except Exception:
            return False

        prev = None
        for row in rows:
            event_id, vm_id, event_type, severity, description, meta_str, ts, row_hash, prev_hash = row
            if prev_hash != prev:
                return False
            try:
                metadata = json.loads(meta_str) if meta_str else {}
            except Exception:
                metadata = {}
            event_dict = {
                "event_id": event_id,
                "vm_id": vm_id,
                "event_type": event_type,
                "severity": severity,
                "description": description,
                "metadata": metadata,
                "timestamp": ts,
                "prev_hash": prev_hash or "",
            }
            raw = self._canonical(event_dict)
            expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            if expected != row_hash:
                return False
            prev = row_hash
        return True

    # ── Future export hooks (stubs) ──────────────────────────────────────────

    def export_forensic_bundle(self, vm_id: str, output_path: Path) -> None:
        """Future: exports all events for vm_id as a signed forensic bundle."""
        raise NotImplementedError("forensic_bundle export — Plan C")

    def sync_to_siem(self, endpoint: str) -> None:
        """Future: pushes audit trail to external SIEM connector."""
        raise NotImplementedError("SIEM sync — Plan C")
