"""
core.ast_security — AST Security Engine for Nexus BNL.

Public API:
    get_ast_engine()   — ASTSecurityEngine singleton (main entry point)
    ScanResult         — result of a full pipeline scan
    RiskLevel          — SAFE / LOW / MEDIUM / HIGH / CRITICAL / BLACKLISTED
"""

from core.ast_security.dangerous_patterns import RiskLevel, ThreatPattern
from core.ast_security.ast_security_engine import ASTSecurityEngine, ScanResult, get_ast_engine
from core.ast_security.ast_audit_logger import ASTAuditLogger, get_ast_audit_logger
from core.ast_security.semantic_analyzer import SemanticAnalyzer, SemanticReport
from core.ast_security.taint_tracker import TaintTracker, TaintFlow

__all__ = [
    "RiskLevel",
    "ThreatPattern",
    "ASTSecurityEngine",
    "ScanResult",
    "get_ast_engine",
    "ASTAuditLogger",
    "get_ast_audit_logger",
    "SemanticAnalyzer",
    "SemanticReport",
    "TaintTracker",
    "TaintFlow",
]
