"""
SemanticAnalyzer — master orchestrator that runs all detectors over an AST
and aggregates findings into a unified SemanticReport.

This module coordinates:
    ImportInspector, ObfuscationDetector, SubprocessDetector,
    PersistenceDetector, ExfiltrationDetector, PrivilegeEscalationDetector,
    FilesystemTraversalDetector, RuntimePayloadDetector, TaintTracker

All analysis is purely static — no code is executed.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.ast_security.ast_parser import ASTParser, ParseResult
from core.ast_security.import_inspector import ImportInspector, ImportFinding
from core.ast_security.obfuscation_detector import ObfuscationDetector, ObfuscationFinding
from core.ast_security.subprocess_detector import SubprocessDetector, SubprocessFinding
from core.ast_security.persistence_detector import PersistenceDetector, PersistenceFinding
from core.ast_security.exfiltration_detector import ExfiltrationDetector, ExfiltrationFinding
from core.ast_security.privilege_escalation_detector import (
    PrivilegeEscalationDetector, PrivilegeEscalationFinding,
)
from core.ast_security.filesystem_traversal_detector import (
    FilesystemTraversalDetector, FilesystemFinding,
)
from core.ast_security.runtime_payload_detector import (
    RuntimePayloadDetector, RuntimePayloadFinding,
)
from core.ast_security.taint_tracker import TaintTracker, TaintFlow

logger = logging.getLogger(__name__)


@dataclass
class SemanticReport:
    """Aggregated output of all detectors for one code sample."""
    scan_id:     str = ""
    filename:    str = ""
    line_count:  int = 0
    token_count: int = 0
    has_syntax_error: bool = False
    syntax_error: str = ""

    # Per-detector findings
    import_findings:     List[ImportFinding]          = field(default_factory=list)
    obfuscation:         List[ObfuscationFinding]     = field(default_factory=list)
    subprocess_abuse:    List[SubprocessFinding]      = field(default_factory=list)
    persistence:         List[PersistenceFinding]     = field(default_factory=list)
    exfiltration:        List[ExfiltrationFinding]    = field(default_factory=list)
    privilege_esc:       List[PrivilegeEscalationFinding] = field(default_factory=list)
    filesystem:          List[FilesystemFinding]      = field(default_factory=list)
    runtime_payload:     List[RuntimePayloadFinding]  = field(default_factory=list)
    taint_flows:         List[TaintFlow]              = field(default_factory=list)

    # Aggregate
    total_findings:  int  = 0
    has_blacklisted: bool = False
    raw_risk_score:  int  = 0

    def all_findings(self) -> List[Any]:
        return (
            self.import_findings + self.obfuscation + self.subprocess_abuse
            + self.persistence + self.exfiltration + self.privilege_esc
            + self.filesystem + self.runtime_payload
        )

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "scan_id":       self.scan_id,
            "filename":      self.filename,
            "line_count":    self.line_count,
            "token_count":   self.token_count,
            "syntax_error":  self.syntax_error,
            "total_findings": self.total_findings,
            "has_blacklisted": self.has_blacklisted,
            "raw_risk_score":  self.raw_risk_score,
            "finding_counts": {
                "imports":     len(self.import_findings),
                "obfuscation": len(self.obfuscation),
                "subprocess":  len(self.subprocess_abuse),
                "persistence": len(self.persistence),
                "exfiltration": len(self.exfiltration),
                "privilege":   len(self.privilege_esc),
                "filesystem":  len(self.filesystem),
                "runtime":     len(self.runtime_payload),
                "taint_flows": len(self.taint_flows),
            },
        }

    def to_full_dict(self) -> Dict[str, Any]:
        d = self.to_summary_dict()
        d["findings"] = {
            "imports":     [f.to_dict() for f in self.import_findings],
            "obfuscation": [f.to_dict() for f in self.obfuscation],
            "subprocess":  [f.to_dict() for f in self.subprocess_abuse],
            "persistence": [f.to_dict() for f in self.persistence],
            "exfiltration": [f.to_dict() for f in self.exfiltration],
            "privilege":   [f.to_dict() for f in self.privilege_esc],
            "filesystem":  [f.to_dict() for f in self.filesystem],
            "runtime":     [f.to_dict() for f in self.runtime_payload],
            "taint_flows": [f.to_dict() for f in self.taint_flows],
        }
        return d


class SemanticAnalyzer:
    """
    Runs all detectors over a ParseResult and returns a SemanticReport.
    Stateless — safe to call concurrently.
    """

    def __init__(self) -> None:
        self._import_inspector = ImportInspector()
        self._obf_detector     = ObfuscationDetector()
        self._sub_detector     = SubprocessDetector()
        self._per_detector     = PersistenceDetector()
        self._exf_detector     = ExfiltrationDetector()
        self._priv_detector    = PrivilegeEscalationDetector()
        self._fs_detector      = FilesystemTraversalDetector()
        self._rt_detector      = RuntimePayloadDetector()
        self._taint_tracker    = TaintTracker()

    def analyze(self, result: ParseResult, scan_id: str = "",
                filename: str = "") -> SemanticReport:
        """Run all detectors. Returns SemanticReport. Does NOT execute code."""
        report = SemanticReport(
            scan_id=scan_id,
            filename=filename or result.metadata.get("filepath", "<unknown>"),
            line_count=result.line_count,
            token_count=result.token_count,
            has_syntax_error=not result.success,
            syntax_error=result.syntax_error or "",
        )

        # Syntax error = still run regex detectors on raw source
        try:
            report.import_findings  = self._import_inspector.inspect(result)
        except Exception as exc:
            logger.debug("[AST] ImportInspector error: %s", exc)

        try:
            report.obfuscation     = self._obf_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] ObfuscationDetector error: %s", exc)

        try:
            report.subprocess_abuse = self._sub_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] SubprocessDetector error: %s", exc)

        try:
            report.persistence     = self._per_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] PersistenceDetector error: %s", exc)

        try:
            report.exfiltration    = self._exf_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] ExfiltrationDetector error: %s", exc)

        try:
            report.privilege_esc   = self._priv_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] PrivilegeDetector error: %s", exc)

        try:
            report.filesystem      = self._fs_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] FilesystemDetector error: %s", exc)

        try:
            report.runtime_payload = self._rt_detector.detect(result)
        except Exception as exc:
            logger.debug("[AST] RuntimePayloadDetector error: %s", exc)

        try:
            report.taint_flows     = self._taint_tracker.track(result)
        except Exception as exc:
            logger.debug("[AST] TaintTracker error: %s", exc)

        # Aggregate
        all_findings = report.all_findings()
        report.total_findings  = len(all_findings) + len(report.taint_flows)
        report.has_blacklisted = any(
            getattr(f, "pattern", None) and f.pattern.blacklisted
            for f in all_findings
        )
        report.raw_risk_score  = min(100, sum(
            getattr(f, "pattern", None) and f.pattern.risk_score or 0
            for f in all_findings
        ) + sum(f.pattern.risk_score for f in report.taint_flows))

        logger.info(
            "[AST] Analysis complete: scan_id=%s findings=%d blacklisted=%s risk=%d",
            scan_id[:8] if scan_id else "?",
            report.total_findings,
            report.has_blacklisted,
            report.raw_risk_score,
        )
        return report

    def analyze_source(self, source: str, filename: str = "<code>",
                       scan_id: str = "") -> SemanticReport:
        """Convenience: parse + analyze in one call."""
        parser = ASTParser()
        result = parser.parse(source, filename=filename)
        return self.analyze(result, scan_id=scan_id, filename=filename)

    def analyze_file(self, path, scan_id: str = "") -> SemanticReport:
        """Convenience: parse a file + analyze."""
        from pathlib import Path
        parser = ASTParser()
        result = parser.parse_file(Path(path))
        return self.analyze(result, scan_id=scan_id, filename=str(path))
