"""
SubprocessDetector — detects subprocess abuse, reverse shell patterns, fork bombs,
and shell spawning via AST and regex analysis.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import (
    DANGEROUS_CALLS, REVERSE_SHELL_PATTERNS, ThreatPattern,
)

logger = logging.getLogger(__name__)

_COMPILED_REVSHELL = [(re.compile(p, re.DOTALL), t) for p, t in REVERSE_SHELL_PATTERNS]

# Fork bomb AST signature: a function that calls itself in a loop
_SUBPROCESS_NAMES = frozenset({
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "subprocess.check_output", "subprocess.check_call",
    "os.system", "os.popen", "os.execv", "os.execve", "os.execvp",
    "os.spawnl", "os.spawnle", "os.spawnlp",
})

_SHELL_SPAWN_STRINGS = re.compile(
    r"(?i)(/bin/sh|/bin/bash|cmd\.exe|powershell\.exe|pwsh\.exe)\s*"
)
_DANGEROUS_CMD_STRINGS = re.compile(
    r"(?i)(rm\s+-rf|del\s+/[fsq]|format\s+[a-z]:|mkfs|fdisk|dd\s+if=|"
    r"net\s+(user|localgroup)|reg\s+(add|delete)|schtasks\s+/create|"
    r"sc\s+create|attrib\s+[+-][srh])"
)


class SubprocessFinding:
    __slots__ = ("pattern", "line", "snippet", "shell_arg")
    def __init__(self, pattern: ThreatPattern, line: int = 0,
                 snippet: str = "", shell_arg: bool = False):
        self.pattern   = pattern
        self.line      = line
        self.snippet   = snippet[:200]
        self.shell_arg = shell_arg

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "subprocess",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
            "shell_arg":   self.shell_arg,
        }


class SubprocessDetector:
    """Detect subprocess abuse and reverse shell patterns."""

    def detect(self, result: ParseResult) -> List[SubprocessFinding]:
        findings: List[SubprocessFinding] = []
        findings += self._reverse_shell_scan(result.source)
        if result.tree:
            findings += self._ast_scan(result.tree, result.source)
        return findings

    def _reverse_shell_scan(self, source: str) -> List[SubprocessFinding]:
        findings = []
        for compiled, threat in _COMPILED_REVSHELL:
            if compiled.search(source):
                line = self._find_line(source, compiled)
                findings.append(SubprocessFinding(threat, line=line,
                                                  snippet=compiled.pattern[:60]))
        return findings

    def _ast_scan(self, tree: ast.AST, source: str) -> List[SubprocessFinding]:
        findings = []
        call_count: Dict[str, int] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            line = getattr(node, "lineno", 0)

            # Count subprocess calls for loop/fork-bomb detection
            if name in _SUBPROCESS_NAMES:
                call_count[name] = call_count.get(name, 0) + 1

            # Dangerous calls
            pat = DANGEROUS_CALLS.get(name)
            if pat and pat.category in ("subprocess", "os"):
                shell_arg = self._has_shell_true(node)
                snippet = self._node_source(node, source)

                # Extra risk if shell=True + string arg
                extra = ThreatPattern(
                    pat.id + ("_SHELL" if shell_arg else ""),
                    pat.category, pat.name + (" [shell=True]" if shell_arg else ""),
                    pat.description,
                    min(100, pat.risk_score + (20 if shell_arg else 0)),
                    blacklisted=pat.blacklisted,
                ) if shell_arg else pat

                findings.append(SubprocessFinding(extra, line=line,
                                                  snippet=snippet, shell_arg=shell_arg))

                # Check args for dangerous command strings
                arg_str = self._extract_string_arg(node)
                if arg_str:
                    if _SHELL_SPAWN_STRINGS.search(arg_str):
                        findings.append(SubprocessFinding(
                            ThreatPattern("SUB_SHELL_SPAWN", "subprocess",
                                          "Shell interpreter invocation",
                                          f"Subprocess spawns shell: {arg_str[:50]}", 55),
                            line=line, snippet=arg_str[:80],
                        ))
                    if _DANGEROUS_CMD_STRINGS.search(arg_str):
                        findings.append(SubprocessFinding(
                            ThreatPattern("SUB_DANGEROUS_CMD", "subprocess",
                                          "Dangerous shell command",
                                          f"Dangerous command in subprocess: {arg_str[:50]}", 60),
                            line=line, snippet=arg_str[:80],
                        ))

        # Fork bomb detection: many subprocess spawns or recursive call pattern
        for name, count in call_count.items():
            if count >= 5:
                findings.append(SubprocessFinding(
                    ThreatPattern("SUB_FORKBOMB", "subprocess",
                                  f"Potential fork bomb ({name}×{count})",
                                  f"{name} called {count} times — possible fork bomb",
                                  min(80, 25 + count * 8)),
                    snippet=f"{name} called {count}×",
                ))

        return findings

    @staticmethod
    def _has_shell_true(node: ast.Call) -> bool:
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                return bool(kw.value.value)
        return False

    @staticmethod
    def _extract_string_arg(node: ast.Call) -> str:
        if not node.args:
            return ""
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        # List of string literals: ["cmd", "arg"]
        if isinstance(arg, (ast.List, ast.Tuple)):
            parts = []
            for elt in arg.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    parts.append(elt.value)
            return " ".join(parts)
        return ""

    @staticmethod
    def _node_source(node: ast.AST, source: str) -> str:
        try:
            return ast.unparse(node)[:120]
        except Exception:
            return ""

    @staticmethod
    def _find_line(source: str, compiled: re.Pattern) -> int:
        m = compiled.search(source)
        return source[:m.start()].count("\n") + 1 if m else 0
