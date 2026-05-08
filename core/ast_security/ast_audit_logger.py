"""
ASTAuditLogger — SQLite persistence for AST security scan results.

DB: data/nexus_ast_security.db
Tables:
    ast_scans           — one row per scan with summary
    threat_patterns     — individual findings from each scan
    semantic_risks      — taint flows and semantic analysis results
    quarantine_decisions— actions taken per scan
    forensic_reports    — full JSON report for critical scans
    taint_flows         — taint flow records for dashboard
"""

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.ast_security.semantic_analyzer import SemanticReport
from core.ast_security.behavioral_risk_scorer import RiskAssessment
from core.ast_security.quarantine_decision_engine import QuarantineDecision

logger = logging.getLogger(__name__)

DB_PATH = Path("data/nexus_ast_security.db")

_DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS ast_scans (
    scan_id          TEXT PRIMARY KEY,
    filename         TEXT DEFAULT '',
    line_count       INTEGER DEFAULT 0,
    token_count      INTEGER DEFAULT 0,
    has_syntax_error INTEGER DEFAULT 0,
    total_findings   INTEGER DEFAULT 0,
    raw_risk_score   INTEGER DEFAULT 0,
    final_score      INTEGER DEFAULT 0,
    risk_level       TEXT DEFAULT 'SAFE',
    action           TEXT DEFAULT 'ALLOW',
    agent_id         TEXT,
    scanned_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    source_hash      TEXT DEFAULT '',
    source_preview   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS threat_patterns (
    finding_id      TEXT PRIMARY KEY,
    scan_id         TEXT NOT NULL,
    pattern_id      TEXT NOT NULL,
    category        TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    risk_score      INTEGER DEFAULT 0,
    blacklisted     INTEGER DEFAULT 0,
    line_number     INTEGER DEFAULT 0,
    snippet         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS semantic_risks (
    risk_id         TEXT PRIMARY KEY,
    scan_id         TEXT NOT NULL,
    risk_type       TEXT NOT NULL,
    description     TEXT DEFAULT '',
    risk_score      INTEGER DEFAULT 0,
    details         TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS quarantine_decisions (
    decision_id       TEXT PRIMARY KEY,
    scan_id           TEXT NOT NULL,
    risk_level        TEXT NOT NULL,
    action            TEXT NOT NULL,
    sandbox_mode      TEXT,
    block_execution   INTEGER DEFAULT 0,
    notify_security   INTEGER DEFAULT 0,
    create_snapshot   INTEGER DEFAULT 0,
    revoke_agent      INTEGER DEFAULT 0,
    reasoning         TEXT DEFAULT '[]',
    decided_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS forensic_reports (
    report_id        TEXT PRIMARY KEY,
    scan_id          TEXT NOT NULL,
    risk_level       TEXT NOT NULL,
    full_report      TEXT NOT NULL,
    created_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS taint_flows (
    flow_id         TEXT PRIMARY KEY,
    scan_id         TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    source_line     INTEGER DEFAULT 0,
    sink_name       TEXT NOT NULL,
    sink_line       INTEGER DEFAULT 0,
    tainted_var     TEXT DEFAULT '',
    risk_score      INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_scans_level    ON ast_scans(risk_level);
CREATE INDEX IF NOT EXISTS idx_scans_agent    ON ast_scans(agent_id);
CREATE INDEX IF NOT EXISTS idx_scans_ts       ON ast_scans(scanned_at);
CREATE INDEX IF NOT EXISTS idx_tp_scan        ON threat_patterns(scan_id);
CREATE INDEX IF NOT EXISTS idx_qd_scan        ON quarantine_decisions(scan_id);
CREATE INDEX IF NOT EXISTS idx_tf_scan        ON taint_flows(scan_id);
"""

import hashlib


class ASTAuditLogger:
    """Thread-safe singleton for persisting AST scan results."""

    _instance: Optional["ASTAuditLogger"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ASTAuditLogger":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = str(DB_PATH)
            with sqlite3.connect(self._db) as c:
                c.executescript(_DDL)
            self._initialized = True
            logger.info("[AST] ASTAuditLogger initialized at %s", self._db)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Persist full scan result ───────────────────────────────────────────────

    def save_scan(
        self,
        report: SemanticReport,
        assessment: RiskAssessment,
        decision: QuarantineDecision,
        source: str = "",
        agent_id: Optional[str] = None,
    ) -> str:
        scan_id = report.scan_id or assessment.scan_id or str(uuid.uuid4())
        source_hash = hashlib.sha256(source.encode()).hexdigest() if source else ""
        source_preview = source[:200].replace("\n", "\\n")

        with self._conn() as conn:
            # Main scan record
            conn.execute(
                """INSERT OR REPLACE INTO ast_scans
                   (scan_id, filename, line_count, token_count, has_syntax_error,
                    total_findings, raw_risk_score, final_score, risk_level, action,
                    agent_id, source_hash, source_preview)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scan_id, report.filename, report.line_count, report.token_count,
                 int(report.has_syntax_error), report.total_findings,
                 report.raw_risk_score, assessment.final_score,
                 assessment.risk_level, decision.action, agent_id,
                 source_hash, source_preview),
            )

            # Threat patterns
            for f in report.all_findings():
                p = getattr(f, "pattern", None)
                if not p:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO threat_patterns
                       (finding_id, scan_id, pattern_id, category, name,
                        description, risk_score, blacklisted, line_number, snippet)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), scan_id, p.id, p.category, p.name,
                     p.description, p.risk_score, int(p.blacklisted),
                     getattr(f, "line", 0), getattr(f, "snippet", "")[:200]),
                )

            # Taint flows
            for flow in report.taint_flows:
                conn.execute(
                    """INSERT OR IGNORE INTO taint_flows
                       (flow_id, scan_id, source_name, source_line, sink_name,
                        sink_line, tainted_var, risk_score, confidence)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), scan_id,
                     flow.source_name, flow.source_line,
                     flow.sink_name, flow.sink_line,
                     flow.tainted_var, flow.pattern.risk_score, flow.confidence),
                )

            # Quarantine decision
            conn.execute(
                """INSERT OR IGNORE INTO quarantine_decisions
                   (decision_id, scan_id, risk_level, action, sandbox_mode,
                    block_execution, notify_security, create_snapshot, revoke_agent, reasoning)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), scan_id, decision.risk_level, decision.action,
                 decision.sandbox_mode, int(decision.block_execution),
                 int(decision.notify_security), int(decision.create_snapshot),
                 int(decision.revoke_agent), json.dumps(decision.reasoning[:10])),
            )

            # Forensic report for HIGH+
            if assessment.final_score >= 51:
                full = {
                    "report":     report.to_full_dict(),
                    "assessment": assessment.to_dict(),
                    "decision":   decision.to_dict(),
                }
                conn.execute(
                    """INSERT OR IGNORE INTO forensic_reports
                       (report_id, scan_id, risk_level, full_report)
                       VALUES (?,?,?,?)""",
                    (str(uuid.uuid4()), scan_id, assessment.risk_level,
                     json.dumps(full, default=str)),
                )

        logger.info("[AST] Scan saved: %s level=%s score=%d",
                    scan_id[:16], assessment.risk_level, assessment.final_score)
        return scan_id

    # ── Query methods ──────────────────────────────────────────────────────────

    def list_scans(
        self,
        risk_level: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if risk_level:
            clauses.append("risk_level=?"); params.append(risk_level)
        if agent_id:
            clauses.append("agent_id=?"); params.append(agent_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM ast_scans {where} ORDER BY scanned_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM ast_scans WHERE scan_id=?", (scan_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["findings"] = [dict(r) for r in conn.execute(
                "SELECT * FROM threat_patterns WHERE scan_id=?", (scan_id,)
            ).fetchall()]
            d["taint_flows"] = [dict(r) for r in conn.execute(
                "SELECT * FROM taint_flows WHERE scan_id=?", (scan_id,)
            ).fetchall()]
            d["decision"] = dict(conn.execute(
                "SELECT * FROM quarantine_decisions WHERE scan_id=?", (scan_id,)
            ).fetchone() or {})
        return d

    def list_quarantine_decisions(
        self, blocked_only: bool = False, limit: int = 50
    ) -> List[Dict[str, Any]]:
        where = "WHERE block_execution=1" if blocked_only else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM quarantine_decisions {where} ORDER BY decided_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_threats(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM threat_patterns ORDER BY risk_score DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_forensic_report(self, scan_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT full_report FROM forensic_reports WHERE scan_id=?", (scan_id,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total      = conn.execute("SELECT COUNT(*) FROM ast_scans").fetchone()[0]
            blocked    = conn.execute(
                "SELECT COUNT(*) FROM ast_scans WHERE action IN ('BLOCK','EMERGENCY')"
            ).fetchone()[0]
            blacklisted = conn.execute(
                "SELECT COUNT(*) FROM ast_scans WHERE risk_level='BLACKLISTED'"
            ).fetchone()[0]
            critical   = conn.execute(
                "SELECT COUNT(*) FROM ast_scans WHERE risk_level='CRITICAL'"
            ).fetchone()[0]
            findings   = conn.execute("SELECT COUNT(*) FROM threat_patterns").fetchone()[0]
            taints     = conn.execute("SELECT COUNT(*) FROM taint_flows").fetchone()[0]
            forensics  = conn.execute("SELECT COUNT(*) FROM forensic_reports").fetchone()[0]
        return {
            "total_scans":      total,
            "blocked_scans":    blocked,
            "blacklisted_scans": blacklisted,
            "critical_scans":   critical,
            "total_findings":   findings,
            "taint_flows":      taints,
            "forensic_reports": forensics,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_logger_inst: Optional[ASTAuditLogger] = None
_logger_lock = threading.Lock()


def get_ast_audit_logger() -> ASTAuditLogger:
    global _logger_inst
    if _logger_inst is None:
        with _logger_lock:
            if _logger_inst is None:
                _logger_inst = ASTAuditLogger()
    return _logger_inst
