"""
RuntimePayloadDetector — detects dynamic code execution, pickle/marshal payloads,
self-modifying code, and runtime injection patterns.
"""

import ast
import re
import logging
from typing import Any, Dict, List

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import DANGEROUS_CALLS, ThreatPattern

logger = logging.getLogger(__name__)

_PAYLOAD_PATTERNS = [
    (re.compile(r"(?i)marshal\.loads\s*\("),
     ThreatPattern("PAY001", "payload", "marshal.loads()",
                   "Bytecode deserialization — payload vector", 55)),
    (re.compile(r"(?i)pickle\.(loads|load)\s*\("),
     ThreatPattern("PAY002", "payload", "pickle.loads()",
                   "Arbitrary object deserialization", 55, cwe="CWE-502")),
    (re.compile(r"(?i)types\.CodeType\s*\("),
     ThreatPattern("PAY003", "payload", "types.CodeType()",
                   "Manual code object construction — shellcode-like", 70)),
    (re.compile(r"(?i)dis\.dis\s*\(|dis\.disassemble"),
     ThreatPattern("PAY004", "payload", "dis.dis() — disassembly",
                   "Runtime disassembly — anti-analysis or obfuscation research", 20)),
    (re.compile(r"(?i)ctypes\.string_at|ctypes\.cast.*c_char_p"),
     ThreatPattern("PAY005", "payload", "ctypes memory read",
                   "Reading raw memory via ctypes", 45)),
    (re.compile(r"(?i)(mmap\.mmap|mmap\.ACCESS_WRITE).*PROT_EXEC"
                r"|ctypes\.memmove.*mmap"),
     ThreatPattern("PAY006", "payload", "Executable memory mapping",
                   "Creating executable memory region — shellcode", 85, blacklisted=True)),
    (re.compile(r"(?i)cffi\.FFI\s*\(\s*\)"),
     ThreatPattern("PAY007", "payload", "CFFI usage",
                   "Foreign Function Interface — arbitrary C code execution", 40)),
    (re.compile(r"(?i)importlib\.import_module\s*\("),
     ThreatPattern("PAY008", "payload", "importlib.import_module()",
                   "Dynamic module import", 25)),
    (re.compile(r"(?i)(zipimport|zipfile.*exec|ZipImporter)"),
     ThreatPattern("PAY009", "payload", "ZIP-based code import",
                   "Importing code from ZIP — hidden payload vector", 35)),
    (re.compile(r"(?i)__code__\s*=|co_code\s*=|co_consts\s*="),
     ThreatPattern("PAY010", "payload", "Code object mutation",
                   "Modifying Python code object — code injection", 80, blacklisted=True)),
]

_COMPILED_PAY = [(pat, t) for pat, t in _PAYLOAD_PATTERNS]

_EXEC_IN_LOOP = re.compile(r"(?i)(for|while).*\n.*exec\s*\(")


class RuntimePayloadFinding:
    __slots__ = ("pattern", "line", "snippet")
    def __init__(self, pattern: ThreatPattern, line: int = 0, snippet: str = ""):
        self.pattern = pattern
        self.line    = line
        self.snippet = snippet[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.pattern.id,
            "category":    "runtime_payload",
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "line":        self.line,
            "snippet":     self.snippet,
        }


class RuntimePayloadDetector:
    """Detect runtime payload injection and dynamic code execution patterns."""

    def detect(self, result: ParseResult) -> List[RuntimePayloadFinding]:
        findings: List[RuntimePayloadFinding] = []
        source = result.source

        for compiled, threat in _COMPILED_PAY:
            m = compiled.search(source)
            if m:
                line = source[:m.start()].count("\n") + 1
                findings.append(RuntimePayloadFinding(threat, line=line,
                                                      snippet=m.group()[:80]))

        # exec() in loop
        if _EXEC_IN_LOOP.search(source):
            findings.append(RuntimePayloadFinding(
                ThreatPattern("PAY_EXEC_LOOP", "payload",
                              "exec() inside loop",
                              "exec() called inside a loop — payload generation", 55),
                snippet="exec() in loop",
            ))

        # AST: eval/exec with non-literal argument
        if result.tree:
            findings += self._ast_dynamic_exec(result.tree)

        return findings

    def _ast_dynamic_exec(self, tree: ast.AST) -> List[RuntimePayloadFinding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in ("eval", "exec", "compile"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            # Flag if argument is NOT a simple string literal (i.e., dynamic)
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                findings.append(RuntimePayloadFinding(
                    ThreatPattern("PAY_DYN_EXEC", "payload",
                                  f"{name}(dynamic)",
                                  f"{name}() called with dynamic/computed argument", 65),
                    line=getattr(node, "lineno", 0),
                    snippet=f"{name}(<dynamic>)",
                ))
        return findings
