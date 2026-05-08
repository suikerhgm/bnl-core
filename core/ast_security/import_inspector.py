"""
ImportInspector — detects dangerous and suspicious imports via AST analysis.
Checks individual imports AND dangerous combinations.
"""

import ast
import logging
from typing import List, Set

from core.ast_security.ast_parser import ParseResult
from core.ast_security.dangerous_patterns import (
    DANGEROUS_IMPORTS, HIGH_RISK_IMPORT_COMBOS, ThreatPattern,
)

logger = logging.getLogger(__name__)


class ImportFinding:
    __slots__ = ("pattern", "module", "line")
    def __init__(self, pattern: ThreatPattern, module: str, line: int):
        self.pattern = pattern
        self.module  = module
        self.line    = line

    def to_dict(self):
        return {
            "id":          self.pattern.id,
            "category":    self.pattern.category,
            "name":        self.pattern.name,
            "description": self.pattern.description,
            "risk_score":  self.pattern.risk_score,
            "blacklisted": self.pattern.blacklisted,
            "module":      self.module,
            "line":        self.line,
        }


class ImportInspector:
    """Inspect all imports in an AST for dangerous modules and combinations."""

    def inspect(self, result: ParseResult) -> List[ImportFinding]:
        findings: List[ImportFinding] = []
        if not result.tree:
            return findings

        seen_modules: Set[str] = set()

        for node in ast.walk(result.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    findings += self._check_module(alias.name, getattr(node, "lineno", 0))
                    seen_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                root = mod.split(".")[0]
                seen_modules.add(root)
                # Also check sub-imports like `from subprocess import Popen`
                for alias in node.names:
                    full = f"{mod}.{alias.name}" if mod else alias.name
                    findings += self._check_module(full, getattr(node, "lineno", 0))
                findings += self._check_module(mod, getattr(node, "lineno", 0))

        # Check dangerous combinations
        for combo, combo_name, risk in HIGH_RISK_IMPORT_COMBOS:
            if combo.issubset(seen_modules):
                findings.append(ImportFinding(
                    ThreatPattern(
                        f"COMBO_{combo_name.upper()}", "import_combo",
                        f"Dangerous import combination: {combo_name}",
                        f"Modules {combo} used together — {combo_name}",
                        risk,
                    ),
                    module="+".join(sorted(combo)),
                    line=0,
                ))

        return findings

    @staticmethod
    def _check_module(module: str, line: int) -> List[ImportFinding]:
        findings = []
        # Exact match
        pat = DANGEROUS_IMPORTS.get(module)
        if pat:
            findings.append(ImportFinding(pat, module, line))
            return findings
        # Root match (e.g., "ctypes.windll" → check "ctypes")
        root = module.split(".")[0]
        pat = DANGEROUS_IMPORTS.get(root)
        if pat and root != module:
            findings.append(ImportFinding(pat, module, line))
        return findings
