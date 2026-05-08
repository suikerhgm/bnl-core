"""
PrivilegeEscalationDetector — detects privilege escalation attempts, UAC bypass,
Windows token manipulation, and unsafe permission operations.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import DANGEROUS_CALLS, ThreatPattern

logger = logging.getLogger(__name__)

_PRIV_PATTERNS = [
    (re.compile(r"(?i)(SeDebugPrivilege|SeTcbPrivilege|SeImpersonatePrivilege"
                r"|SeAssignPrimaryTokenPrivilege)"),
     ThreatPattern("PRV001", "privilege", "Windows privilege constant",
                   "High-privilege Windows token constant", 70)),
    (re.compile(r"(?i)(AdjustTokenPrivileges|OpenProcessToken|LookupPrivilegeValue)"),
     ThreatPattern("PRV002", "privilege", "Token privilege manipulation",
                   "Windows API for token privilege adjustment", 75, blacklisted=True)),
    (re.compile(r"(?i)(UAC|bypassuac|elevat|runas.*administrator)"),
     ThreatPattern("PRV003", "privilege", "UAC bypass reference",
                   "User Account Control bypass attempt", 70)),
    (re.compile(r"(?i)(sudo\s+|su\s+-|sudo\s+-s)"),
     ThreatPattern("PRV004", "privilege", "sudo abuse",
                   "sudo command invocation", 45)),
    (re.compile(r"(?i)os\.(setuid|setgid|setreuid|setregid)\s*\("),
     ThreatPattern("PRV005", "privilege", "UID/GID change",
                   "Setting process user/group ID", 40)),
    (re.compile(r"(?i)(CreateProcessWithLogon|CreateProcessAsUser|ImpersonateLoggedOnUser)"),
     ThreatPattern("PRV006", "privilege", "Windows process impersonation",
                   "Creating process as another user", 75, blacklisted=True)),
    (re.compile(r"(?i)(chmod\s+[0-7]*7[0-7]*|os\.chmod.*0o7)"),
     ThreatPattern("PRV007", "privilege", "Dangerous chmod",
                   "Setting world-writable/executable permissions", 35)),
    (re.compile(r"(?i)(ctypes\.windll\.advapi32|advapi32\.dll)"),
     ThreatPattern("PRV008", "privilege", "advapi32 (Windows security API)",
                   "Direct Windows security API access", 55)),
]

_COMPILED_PRIV = [(pat, t) for pat, t in _PRIV_PATTERNS]

# AST-level: os.setuid(0) or os.setgid(0) with literal 0
_SETUID_ZERO = frozenset({"os.setuid", "os.setgid", "os.setreuid", "os.setregid"})


class PrivilegeEscalationFinding:
    __slots__ = ("pattern", "line", "snippet")
    def __init__(self, pattern: ThreatPattern, line: int = 0, snippet: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "privilege_escalation",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
        }


class PrivilegeEscalationDetector:
    """Detect privilege escalation techniques."""

    def detect(self, result: ParseResult) -> List[PrivilegeEscalationFinding]:
        findings: List[PrivilegeEscalationFinding] = []
        source = result.source

        for compiled, threat in _COMPILED_PRIV:
            if compiled.search(source):
                m = compiled.search(source)
                line = source[:m.start()].count("\n") + 1 if m else 0
                findings.append(PrivilegeEscalationFinding(
                    threat, line=line, snippet=compiled.pattern[:60]
                ))

        if result.tree:
            findings += self._ast_scan(result.tree)

        return findings

    def _ast_scan(self, tree: ast.AST) -> List[PrivilegeEscalationFinding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name in _SETUID_ZERO:
                # Flag setuid(0) — switching to root
                if (node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == 0):
                    findings.append(PrivilegeEscalationFinding(
                        ThreatPattern("PRV_ROOT", "privilege",
                                      f"{name}(0) — become root",
                                      f"Attempting to set UID/GID to root (0)", 80,
                                      blacklisted=True),
                        line=getattr(node, "lineno", 0),
                        snippet=f"{name}(0)",
                    ))
        return findings
