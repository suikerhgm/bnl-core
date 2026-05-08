"""
ExfiltrationDetector — detects credential theft, data exfiltration, keyloggers,
screen capture, and external data sending patterns.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import (
    EXFILTRATION_STRINGS, RANSOMWARE_PATTERNS, ThreatPattern,
)

logger = logging.getLogger(__name__)

_COMPILED_EXF   = [(re.compile(p, re.DOTALL | re.IGNORECASE), t) for p, t in EXFILTRATION_STRINGS]
_COMPILED_RAN   = [(re.compile(p, re.DOTALL | re.IGNORECASE), t) for p, t in RANSOMWARE_PATTERNS]

# Credential-related string patterns
_CRED_STRINGS = re.compile(
    r"(?i)(password|passwd|api_key|api_secret|secret_key|access_token|"
    r"private_key|auth_token|bearer\s+[A-Za-z0-9])"
)

# Environment dump patterns
_ENV_DUMP = re.compile(
    r"(?i)(os\.environ\.items\(\)|dict\(os\.environ\)|json\.dumps\s*\(\s*.*environ)"
)

# Outbound network with credential data
_CRED_NETWORK = re.compile(
    r"(?i)(requests\.(post|put|patch)|urllib|httpx\.post).*"
    r"(password|token|key|secret|credential)"
)


class ExfiltrationFinding:
    __slots__ = ("pattern", "line", "snippet")
    def __init__(self, pattern: ThreatPattern, line: int = 0, snippet: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "exfiltration",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
        }


class ExfiltrationDetector:
    """Detect data exfiltration, ransomware, credential theft, and keyloggers."""

    def detect(self, result: ParseResult) -> List[ExfiltrationFinding]:
        findings: List[ExfiltrationFinding] = []
        source = result.source

        # Regex-based exfiltration
        for compiled, threat in _COMPILED_EXF:
            if compiled.search(source):
                line = _find_line(source, compiled)
                findings.append(ExfiltrationFinding(threat, line=line,
                                                    snippet=compiled.pattern[:60]))

        # Ransomware patterns
        for compiled, threat in _COMPILED_RAN:
            if compiled.search(source):
                line = _find_line(source, compiled)
                findings.append(ExfiltrationFinding(threat, line=line,
                                                    snippet=compiled.pattern[:60]))

        # Environment credential dump
        if _ENV_DUMP.search(source):
            findings.append(ExfiltrationFinding(
                ThreatPattern("EXF_ENVDUMP", "exfiltration",
                              "Full environment variable dump",
                              "Dumping all environment variables (credential harvest)", 40),
                line=_find_line(source, _ENV_DUMP),
            ))

        # Credential + network combo
        if _CRED_NETWORK.search(source):
            findings.append(ExfiltrationFinding(
                ThreatPattern("EXF_CREDNET", "exfiltration",
                              "Credential sent over network",
                              "Credential-related data sent via HTTP request", 65),
                line=_find_line(source, _CRED_NETWORK),
            ))

        # AST-level: look for credential strings in network call arguments
        if result.tree:
            findings += self._ast_credential_send(result.tree)

        return findings

    def _ast_credential_send(self, tree: ast.AST) -> List[ExfiltrationFinding]:
        """Detect calls like requests.post(url, data={'password': var})."""
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in ("requests.post", "requests.put", "requests.patch",
                            "httpx.post", "urllib.request.urlopen"):
                continue
            # Check keyword args for credential-related keys
            for kw in node.keywords:
                if kw.arg in ("data", "json", "params"):
                    if isinstance(kw.value, ast.Dict):
                        for k in kw.value.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                if _CRED_STRINGS.search(k.value):
                                    findings.append(ExfiltrationFinding(
                                        ThreatPattern("EXF_CRED_ARG", "exfiltration",
                                                      "Credential key in network request",
                                                      f"'{k.value}' sent via {name}", 60),
                                        line=getattr(node, "lineno", 0),
                                        snippet=f"{name}(..., {kw.arg}={{'{k.value}': ...}})",
                                    ))
        return findings


def _find_line(source: str, compiled: re.Pattern) -> int:
    m = compiled.search(source)
    return source[:m.start()].count("\n") + 1 if m else 0
