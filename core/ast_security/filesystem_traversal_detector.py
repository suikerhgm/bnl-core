"""
FilesystemTraversalDetector — detects path traversal, mass deletion,
credential file access, and workspace escape attempts in Python AST.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import ThreatPattern

logger = logging.getLogger(__name__)

_TRAVERSAL_STRINGS = re.compile(r"(\.\./|\.\.\\|%2e%2e|%252e%252e)", re.IGNORECASE)
_SENSITIVE_PATHS   = re.compile(
    r"(?i)(\.ssh[/\\]|/etc/(passwd|shadow|sudoers)|"
    r"C:\\Windows\\System32|NTDS\.dit|SAM|"
    r"\.aws/credentials|\.azure/|google.*credentials\.json|"
    r"id_rsa|authorized_keys|\.gnupg|\.keystore)"
)
_MASS_DELETE = re.compile(r"(?i)(shutil\.rmtree|os\.remove|os\.unlink).*os\.walk")
_RECURSIVE_GLOB = re.compile(r"(?i)glob\.glob\s*\([\"']?\*\*[/\\]?\*")

_DANGEROUS_OPENS = frozenset({
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
    "C:\\Windows\\System32\\config\\SAM",
    "~/.ssh/id_rsa", "~/.aws/credentials",
})


class FilesystemFinding:
    __slots__ = ("pattern", "line", "snippet")
    def __init__(self, pattern: ThreatPattern, line: int = 0, snippet: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "filesystem",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
        }


class FilesystemTraversalDetector:
    """Detect filesystem traversal, mass delete, and credential access."""

    def detect(self, result: ParseResult) -> List[FilesystemFinding]:
        findings: List[FilesystemFinding] = []
        source = result.source

        # Path traversal sequences
        if _TRAVERSAL_STRINGS.search(source):
            m = _TRAVERSAL_STRINGS.search(source)
            line = source[:m.start()].count("\n") + 1 if m else 0
            findings.append(FilesystemFinding(
                ThreatPattern("FS001", "filesystem", "Path traversal sequence",
                              "../ or URL-encoded traversal sequence", 45),
                line=line, snippet=m.group() if m else "",
            ))

        # Sensitive path access
        if _SENSITIVE_PATHS.search(source):
            m = _SENSITIVE_PATHS.search(source)
            line = source[:m.start()].count("\n") + 1 if m else 0
            findings.append(FilesystemFinding(
                ThreatPattern("FS002", "filesystem", "Sensitive file path",
                              f"Access to credential/system file: {m.group()[:50]}", 60),
                line=line, snippet=m.group()[:80],
            ))

        # Mass delete pattern
        if _MASS_DELETE.search(source):
            m = _MASS_DELETE.search(source)
            line = source[:m.start()].count("\n") + 1 if m else 0
            findings.append(FilesystemFinding(
                ThreatPattern("FS003", "filesystem", "Mass file deletion",
                              "os.walk + delete — recursive mass deletion pattern", 65),
                line=line,
            ))

        # Recursive glob (potential mass operation)
        if _RECURSIVE_GLOB.search(source):
            findings.append(FilesystemFinding(
                ThreatPattern("FS004", "filesystem", "Recursive glob pattern",
                              "glob.glob('**/*') — mass file operation", 20),
            ))

        # AST: open() with dangerous paths
        if result.tree:
            findings += self._ast_open_scan(result.tree)

        return findings

    def _ast_open_scan(self, tree: ast.AST) -> List[FilesystemFinding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in ("open", "pathlib.Path", "Path"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                path_val = arg.value
                if any(path_val.endswith(s) or path_val == s
                       for s in _DANGEROUS_OPENS):
                    findings.append(FilesystemFinding(
                        ThreatPattern("FS_OPEN_CRED", "filesystem",
                                      "Opening credential file",
                                      f"open({path_val!r}) — credential file", 65,
                                      blacklisted=False),
                        line=getattr(node, "lineno", 0),
                        snippet=f"open({path_val!r})",
                    ))
                if _TRAVERSAL_STRINGS.search(path_val):
                    findings.append(FilesystemFinding(
                        ThreatPattern("FS_PATH_TRAV", "filesystem",
                                      "Path traversal in open()",
                                      f"open() with traversal path: {path_val[:50]}", 50),
                        line=getattr(node, "lineno", 0),
                        snippet=f"open({path_val!r})",
                    ))
        return findings
