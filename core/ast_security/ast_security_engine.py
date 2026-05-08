"""
ASTSecurityEngine — main orchestrator and public API for Nexus BNL AST Security.

This is the single entry point for all code security scanning.
Every code artifact submitted for execution MUST pass through this engine first.

Pipeline:
    1. ASTParser.parse(source)            → ParseResult
    2. SemanticAnalyzer.analyze(result)   → SemanticReport
    3. BehavioralRiskScorer.score(report) → RiskAssessment
    4. QuarantineDecisionEngine.decide()  → QuarantineDecision
    5. ASTAuditLogger.save_scan()         → persisted to DB

Returns a ScanResult that callers use to decide whether to proceed with execution.

Usage:
    engine = get_ast_engine()
    result = engine.scan(source_code, filename="agent_script.py")
    if result.blocked:
        raise SecurityError(result.decision.action)
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from core.ast_security.ast_parser import ASTParser
from core.ast_security.semantic_analyzer import SemanticAnalyzer, SemanticReport
from core.ast_security.behavioral_risk_scorer import BehavioralRiskScorer, RiskAssessment
from core.ast_security.quarantine_decision_engine import QuarantineDecisionEngine, QuarantineDecision
from core.ast_security.ast_audit_logger import ASTAuditLogger, get_ast_audit_logger
from core.ast_security.dangerous_patterns import RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """The unified result of a full AST security scan."""
    scan_id:    str
    filename:   str
    blocked:    bool
    risk_level: str
    final_score: int
    action:     str
    report:     SemanticReport = field(repr=False)
    assessment: RiskAssessment = field(repr=False)
    decision:   QuarantineDecision = field(repr=False)

    @property
    def safe(self) -> bool:
        return not self.blocked

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id":     self.scan_id,
            "filename":    self.filename,
            "blocked":     self.blocked,
            "safe":        self.safe,
            "risk_level":  self.risk_level,
            "final_score": self.final_score,
            "action":      self.action,
            "summary":     self.report.to_summary_dict(),
            "assessment":  self.assessment.to_dict(),
            "decision":    self.decision.to_dict(),
        }

    def to_full_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        d["full_report"] = self.report.to_full_dict()
        return d


class ASTSecurityEngine:
    """
    Singleton orchestrator for the complete AST security pipeline.
    Thread-safe — safe to call from multiple async contexts.
    NEVER executes any code under analysis.
    """

    _instance: Optional["ASTSecurityEngine"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ASTSecurityEngine":
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
            self._parser    = ASTParser()
            self._analyzer  = SemanticAnalyzer()
            self._scorer    = BehavioralRiskScorer()
            self._decider   = QuarantineDecisionEngine()
            self._db        = get_ast_audit_logger()
            self._initialized = True
            logger.info("[AST] ASTSecurityEngine initialized")

    # ── Public API ─────────────────────────────────────────────────────────────

    def scan(
        self,
        source: str,
        filename: str = "<code>",
        agent_id: Optional[str] = None,
        scan_id: Optional[str] = None,
    ) -> ScanResult:
        """
        Full scan pipeline. Returns ScanResult.
        Does NOT execute the source code under any circumstances.
        """
        sid = scan_id or str(uuid.uuid4())
        logger.info("[AST] Scan started: %s filename=%s agent=%s",
                    sid[:8], filename, agent_id)

        # 1. Parse
        parse_result = self._parser.parse(source, filename=filename)

        # 2. Semantic analysis
        report = self._analyzer.analyze(parse_result, scan_id=sid, filename=filename)

        # 3. Risk scoring
        assessment = self._scorer.score(report)

        # 4. Quarantine decision
        decision = self._decider.decide(assessment, agent_id=agent_id)

        # 5. Persist
        try:
            self._db.save_scan(report, assessment, decision, source=source, agent_id=agent_id)
        except Exception as exc:
            logger.error("[AST] Failed to save scan: %s", exc)

        result = ScanResult(
            scan_id=sid,
            filename=filename,
            blocked=decision.block_execution,
            risk_level=assessment.risk_level,
            final_score=assessment.final_score,
            action=decision.action,
            report=report,
            assessment=assessment,
            decision=decision,
        )

        logger.info(
            "[AST] Scan complete: %s level=%s score=%d blocked=%s",
            sid[:8], result.risk_level, result.final_score, result.blocked,
        )
        return result

    def scan_file(
        self,
        path: Path,
        agent_id: Optional[str] = None,
        scan_id: Optional[str] = None,
    ) -> ScanResult:
        """Scan a file from disk."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            # Return a safe error result — cannot read file, block by default
            sid = scan_id or str(uuid.uuid4())
            logger.error("[AST] Cannot read file %s: %s", path, exc)
            return self._error_result(sid, str(path), f"Cannot read file: {exc}")
        return self.scan(source, filename=str(path), agent_id=agent_id, scan_id=scan_id)

    def quick_check(self, source: str) -> bool:
        """
        Fast check: returns True if code is SAFE or LOW risk (allow execution).
        Does NOT save to DB.
        """
        parse_result = self._parser.parse(source)
        report = self._analyzer.analyze(parse_result)
        assessment = self._scorer.score(report)
        return assessment.risk_level in (RiskLevel.SAFE, RiskLevel.LOW)

    # ── Query delegates ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return self._db.get_stats()

    def list_scans(
        self,
        risk_level: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        return self._db.list_scans(risk_level=risk_level, agent_id=agent_id, limit=limit)

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        return self._db.get_scan(scan_id)

    def list_threats(self, limit: int = 100) -> list:
        return self._db.list_threats(limit=limit)

    def list_quarantine_decisions(self, blocked_only: bool = False) -> list:
        return self._db.list_quarantine_decisions(blocked_only=blocked_only)

    def get_forensic_report(self, scan_id: str) -> Optional[Dict]:
        return self._db.get_forensic_report(scan_id)

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _error_result(scan_id: str, filename: str, error: str) -> "ScanResult":
        from core.ast_security.semantic_analyzer import SemanticReport
        from core.ast_security.behavioral_risk_scorer import RiskAssessment
        from core.ast_security.quarantine_decision_engine import QuarantineDecision
        report = SemanticReport(scan_id=scan_id, filename=filename,
                                has_syntax_error=True, syntax_error=error)
        assessment = RiskAssessment(scan_id=scan_id, raw_score=0, final_score=0,
                                    risk_level=RiskLevel.SAFE, is_blacklisted=False,
                                    combo_bonuses=0, reasoning=[error])
        decision = QuarantineDecision(scan_id=scan_id, risk_level=RiskLevel.SAFE,
                                      action="ALLOW", sandbox_mode=None,
                                      block_execution=False, notify_security=False,
                                      create_snapshot=False, revoke_agent=False)
        return ScanResult(scan_id=scan_id, filename=filename, blocked=False,
                          risk_level=RiskLevel.SAFE, final_score=0, action="ALLOW",
                          report=report, assessment=assessment, decision=decision)


# ── Singleton accessor ─────────────────────────────────────────────────────────

_engine: Optional[ASTSecurityEngine] = None
_engine_lock = threading.Lock()


def get_ast_engine() -> ASTSecurityEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = ASTSecurityEngine()
    return _engine
