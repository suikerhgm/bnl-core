"""
PersistenceDetector — detects persistence mechanisms, self-replication,
scheduled tasks, registry modification, and autorun behavior.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult
from core.ast_security.dangerous_patterns import PERSISTENCE_STRINGS, ThreatPattern

logger = logging.getLogger(__name__)

_COMPILED_PERSIST = [(re.compile(p, re.DOTALL | re.IGNORECASE), t)
                     for p, t in PERSISTENCE_STRINGS]

# Self-replication: using __file__ + shutil.copy / open+write pattern
_SELF_COPY_PATTERNS = [
    re.compile(r"(?i)shutil\.(copy|copy2|copyfile).*__file__"),
    re.compile(r"(?i)__file__.*shutil\.(copy|copy2|copyfile)"),
    re.compile(r"(?i)open\s*\(\s*__file__"),
    re.compile(r"(?i)sys\.argv\[0\].*shutil\.(copy|copy2)"),
]

# Worm-like propagation
_WORM_PATTERNS = [
    re.compile(r"(?i)glob\.glob\s*\(.*\*\.py\s*\).*open|os\.walk.*\.py.*open.*write"),
    re.compile(r"(?i)os\.walk.*shutil\.copy|glob\.iglob.*shutil\.copy"),
]


class PersistenceFinding:
    __slots__ = ("pattern", "line", "snippet")
    def __init__(self, pattern: ThreatPattern, line: int = 0, snippet: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "persistence",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
        }


class PersistenceDetector:
    """Detect persistence, self-replication, and worm-like propagation patterns."""

    def detect(self, result: ParseResult) -> List[PersistenceFinding]:
        findings: List[PersistenceFinding] = []
        source = result.source

        # Regex-based patterns
        for compiled, threat in _COMPILED_PERSIST:
            if compiled.search(source):
                line = _find_line(source, compiled)
                findings.append(PersistenceFinding(threat, line=line,
                                                   snippet=compiled.pattern[:60]))

        # Self-copy patterns
        for pat in _SELF_COPY_PATTERNS:
            if pat.search(source):
                line = _find_line(source, pat)
                findings.append(PersistenceFinding(
                    ThreatPattern("PER_SELFCOPY", "persistence",
                                  "Self-copy behavior",
                                  "Script copies itself to another location", 65),
                    line=line, snippet=pat.pattern[:60],
                ))
                break

        # Worm-like propagation
        for pat in _WORM_PATTERNS:
            if pat.search(source):
                line = _find_line(source, pat)
                findings.append(PersistenceFinding(
                    ThreatPattern("PER_WORM", "persistence",
                                  "Worm-like propagation",
                                  "Iterates over .py files and copies/writes to them",
                                  80, blacklisted=True),
                    line=line, snippet=pat.pattern[:60],
                ))
                break

        # AST: writing to startup-like path
        if result.tree:
            findings += self._ast_scan(result.tree)

        return findings

    def _ast_scan(self, tree: ast.AST) -> List[PersistenceFinding]:
        findings = []
        _startup_re = re.compile(
            r"(?i)(startup|autorun|autostart|\\Microsoft\\Windows\\CurrentVersion\\Run"
            r"|\.bashrc|\.bash_profile|LaunchAgents|LaunchDaemons|cron)"
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _startup_re.search(node.value):
                    findings.append(PersistenceFinding(
                        ThreatPattern("PER_PATH", "persistence",
                                      "Persistence path in string literal",
                                      f"Startup/autorun path: {node.value[:60]}", 40),
                        line=getattr(node, "lineno", 0),
                        snippet=node.value[:80],
                    ))
        return findings


def _find_line(source: str, compiled: re.Pattern) -> int:
    m = compiled.search(source)
    return source[:m.start()].count("\n") + 1 if m else 0
