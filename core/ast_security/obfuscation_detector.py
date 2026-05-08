"""
ObfuscationDetector — detects code obfuscation, encoded payloads, and anti-analysis
techniques via both AST structure analysis and regex on the source text.
"""

import ast
import re
import logging
from typing import Any, Dict, List, Optional

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import (
    OBFUSCATION_REGEXES, ThreatPattern,
)

logger = logging.getLogger(__name__)

# Compiled patterns (done once at import time)
_COMPILED = [(re.compile(pat, re.DOTALL), threat) for pat, threat in OBFUSCATION_REGEXES]

# Additional AST-level obfuscation patterns
_EXEC_CHAIN_DEPTH = 3   # exec(eval(compile(...)))) depth


class ObfuscationFinding:
    __slots__ = ("pattern", "line", "snippet", "context")
    def __init__(self, pattern: ThreatPattern, line: int = 0,
                 snippet: str = "", context: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "obfuscation",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
            "context":     self.context,
        }


class ObfuscationDetector:
    """Detect obfuscation via AST structure + regex on source."""

    def detect(self, result: ParseResult) -> List[ObfuscationFinding]:
        findings: List[ObfuscationFinding] = []
        findings += self._regex_scan(result.source)
        if result.tree:
            findings += self._ast_scan(result.tree, result.source)
        return findings

    # ── Regex scan on raw source ───────────────────────────────────────────────

    def _regex_scan(self, source: str) -> List[ObfuscationFinding]:
        findings = []
        for compiled, threat in _COMPILED:
            for m in compiled.finditer(source):
                line = source[:m.start()].count("\n") + 1
                findings.append(ObfuscationFinding(
                    threat, line=line, snippet=m.group()[:100],
                ))
                break  # one finding per pattern per file is enough
        return findings

    # ── AST structure scan ─────────────────────────────────────────────────────

    def _ast_scan(self, tree: ast.AST, source: str) -> List[ObfuscationFinding]:
        findings = []
        visitor = _ObfuscationVisitor()
        try:
            visitor.visit(tree)
        except Exception:
            pass
        findings += visitor.findings

        # Detect exec/eval chain depth
        for node in ast.walk(tree):
            depth = _exec_chain_depth(node)
            if depth >= _EXEC_CHAIN_DEPTH:
                findings.append(ObfuscationFinding(
                    ThreatPattern(
                        "OBF_CHAIN", "obfuscation", f"exec/eval chain (depth={depth})",
                        f"Nested exec/eval chain of depth {depth}", min(80, 35 + depth * 10),
                    ),
                    line=getattr(node, "lineno", 0),
                    snippet=f"depth={depth}",
                ))

        return findings


class _ObfuscationVisitor(ast.NodeVisitor):
    def __init__(self):
        self.findings: List[ObfuscationFinding] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)

        # __builtins__["exec"] pattern
        if isinstance(node.func, ast.Subscript):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "__builtins__":
                self.findings.append(ObfuscationFinding(
                    ThreatPattern("OBF_BUILTINS", "obfuscation",
                                  "__builtins__ subscript",
                                  "Accessing builtins via subscript — obfuscation", 45),
                    line=getattr(node, "lineno", 0),
                ))

        # getattr(builtins, 'exec') or globals()['exec']
        if name in ("getattr", "globals") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if first.value in ("exec", "eval", "compile", "__import__"):
                    self.findings.append(ObfuscationFinding(
                        ThreatPattern("OBF_GETATTR_EXEC", "obfuscation",
                                      f"getattr/globals access to {first.value}",
                                      "Dynamic access to dangerous builtin", 50),
                        line=getattr(node, "lineno", 0),
                        snippet=f"{name}(..., '{first.value}')",
                    ))

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Detect string fragmentation: `s = 'ha' + 'ck' + ...`
        if isinstance(node.value, ast.BinOp):
            parts = _count_string_concat_parts(node.value)
            if parts >= 8:
                self.findings.append(ObfuscationFinding(
                    ThreatPattern("OBF_STRFRAG", "obfuscation",
                                  "String fragmentation",
                                  f"String built from {parts} concatenated parts", 25),
                    line=getattr(node, "lineno", 0),
                    snippet=f"({parts} parts)",
                ))
        self.generic_visit(node)


def _exec_chain_depth(node: ast.AST, current: int = 0) -> int:
    """Measure nesting depth of exec/eval/compile calls."""
    if not isinstance(node, ast.Call):
        return current
    name = _call_name(node.func)
    if name in ("exec", "eval", "compile"):
        # recurse into first argument
        if node.args and isinstance(node.args[0], ast.Call):
            return _exec_chain_depth(node.args[0], current + 1)
        return current + 1
    return current


def _count_string_concat_parts(node: ast.BinOp, count: int = 0) -> int:
    if not isinstance(node.op, ast.Add):
        return count
    left_count = count
    if isinstance(node.left, ast.BinOp):
        left_count = _count_string_concat_parts(node.left, count)
    elif isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
        left_count = count + 1
    right = 1 if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str) else 0
    return left_count + right
