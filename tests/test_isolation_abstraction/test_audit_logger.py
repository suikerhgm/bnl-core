"""
tests/test_isolation_abstraction/test_audit_logger.py
Task 8 — IsolationAuditLogger tests (11 tests).
"""
import json
import sqlite3
import pytest
from pathlib import Path
from core.isolation_abstraction.isolation_audit_logger import IsolationAuditLogger


@pytest.fixture
def tmp_logger(tmp_path):
    return IsolationAuditLogger(db_path=tmp_path / "test_audit.db")


def test_tables_created_on_init(tmp_logger):
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    required = {"virtual_machines", "vm_sessions", "vm_events", "vm_escape_attempts",
                "vm_policies", "vm_forensics", "vm_snapshots", "vm_runtime_metrics"}
    assert required.issubset(tables)


def test_log_event_writes_row(tmp_logger):
    tmp_logger.log_event(
        vm_id="vm-001", event_type="BOOT", severity="INFO",
        description="VM booted", metadata={},
    )
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        rows = list(conn.execute("SELECT vm_id, event_type FROM vm_events"))
    assert rows == [("vm-001", "BOOT")]


def test_log_event_returns_event_id(tmp_logger):
    eid = tmp_logger.log_event(
        vm_id="vm-001", event_type="TEST", severity="INFO",
        description="test", metadata={},
    )
    assert isinstance(eid, str) and len(eid) == 36  # UUID format


def test_hash_chain_intact_after_multiple_events(tmp_logger):
    for i in range(5):
        tmp_logger.log_event(
            vm_id="vm-001", event_type=f"EVT_{i}", severity="INFO",
            description=f"event {i}", metadata={"idx": i},
        )
    assert tmp_logger.verify_chain() is True


def test_tamper_detection(tmp_logger):
    tmp_logger.log_event(vm_id="vm-001", event_type="BOOT", severity="INFO",
                          description="ok", metadata={})
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        conn.execute("UPDATE vm_events SET description='TAMPERED'")
    assert tmp_logger.verify_chain() is False


def test_prev_hash_chaining(tmp_logger):
    tmp_logger.log_event(vm_id="v", event_type="A", severity="INFO", description="a", metadata={})
    tmp_logger.log_event(vm_id="v", event_type="B", severity="INFO", description="b", metadata={})
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        rows = list(conn.execute("SELECT row_hash, prev_hash FROM vm_events ORDER BY timestamp ASC"))
    assert rows[1][1] == rows[0][0]  # second row's prev_hash = first row's row_hash


def test_log_negotiation_writes_session(tmp_path):
    from datetime import datetime, timezone
    from core.isolation_abstraction.isolation_driver import IsolationTier, TIER_CAPABILITIES
    from core.isolation_abstraction.isolation_strategy_manager import IsolationPolicy
    from core.isolation_abstraction.isolation_negotiator import NegotiationResult
    logger = IsolationAuditLogger(db_path=tmp_path / "neg.db")
    result = NegotiationResult(
        requested_tier=IsolationTier.DOCKER_HARDENED,
        actual_tier=IsolationTier.DOCKER_HARDENED,
        policy=IsolationPolicy.BEST_AVAILABLE,
        reason="exact_match:DOCKER_HARDENED",
        host_os="windows",
        fallback_level=0,
        fallback_chain=(),
        driver_capabilities=TIER_CAPABILITIES[IsolationTier.DOCKER_HARDENED],
        security_score=70,
        risk_adjusted_score=70,
        forensic_support=True,
        behavioral_support=True,
        candidate_drivers=(IsolationTier.DOCKER_HARDENED,),
        rejection_reasons={},
        capability_mismatches={},
        policy_rejections={},
    )
    logger.log_negotiation("sess-001", "vm-001", result)
    with sqlite3.connect(str(tmp_path / "neg.db")) as conn:
        rows = list(conn.execute("SELECT session_id, actual_tier FROM vm_sessions"))
    assert rows[0] == ("sess-001", "DOCKER_HARDENED")


def test_log_vm_created_and_destroyed(tmp_logger):
    tmp_logger.log_vm_created(
        vm_id="vm-abc", session_id="s1", tier="DOCKER_HARDENED",
        agent_id="agent-1", security_score=70, risk_adjusted_score=70,
    )
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        row = conn.execute("SELECT status FROM virtual_machines WHERE vm_id='vm-abc'").fetchone()
    assert row[0] == "RUNNING"
    tmp_logger.log_vm_destroyed("vm-abc")
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        row = conn.execute("SELECT status FROM virtual_machines WHERE vm_id='vm-abc'").fetchone()
    assert row[0] == "DESTROYED"


def test_empty_chain_is_valid(tmp_logger):
    assert tmp_logger.verify_chain() is True


def test_correlation_id_stored(tmp_logger):
    tmp_logger.log_event(
        vm_id="vm-001", event_type="TEST", severity="INFO",
        description="test", metadata={}, correlation_id="corr-xyz",
    )
    with sqlite3.connect(str(tmp_logger._db)) as conn:
        row = conn.execute("SELECT correlation_id FROM vm_events").fetchone()
    assert row[0] == "corr-xyz"


def test_thread_safety(tmp_logger):
    import threading
    errors = []
    def write():
        try:
            for i in range(10):
                tmp_logger.log_event(
                    vm_id="vm-t", event_type="T", severity="INFO",
                    description=str(i), metadata={},
                )
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=write) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
    assert tmp_logger.verify_chain() is True
