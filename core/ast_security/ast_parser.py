"""
ASTParser — safe, defensive code-to-AST conversion for Nexus BNL.

NEVER executes code. Only parses text into an AST for static analysis.
Handles syntax errors gracefully and extracts structural metadata.
"""

import ast
import tokenize
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 5 * 1024 * 1024  # 5 MB hard limit


@dataclass
class ParseResult:
    """Result of parsing a code string."""
    success:       bool
    tree:          Optional[ast.AST]
    source:        str
    line_count:    int
    token_count:   int
    syntax_error:  Optional[str]
    imports:       List[str]        = field(default_factory=list)
    function_defs: List[str]        = field(default_factory=list)
    class_defs:    List[str]        = field(default_factory=list)
    calls:         List[str]        = field(default_factory=list)
    strings:       List[str]        = field(default_factory=list)
    attributes:    List[str]        = field(default_factory=list)
    global_names:  Set[str]         = field(default_factory=set)
    has_main:      bool             = False
    encoding:      str              = "utf-8"
    metadata:      Dict[str, Any]   = field(default_factory=dict)


class ASTParser:
    """
    Parses Python source code into AST + extracts structural metadata.
    All operations are purely static — no code is executed.
    """

    def parse(self, source: str, filename: str = "<unknown>") -> ParseResult:
        """Parse source code. Returns ParseResult regardless of success."""
        # Size guard
        if len(source.encode("utf-8", errors="replace")) > MAX_SOURCE_BYTES:
            return ParseResult(
                success=False, tree=None, source=source[:200],
                line_count=0, token_count=0,
                syntax_error=f"Source too large (>{MAX_SOURCE_BYTES//1024}KB)",
            )

        lines = source.splitlines()
        line_count = len(lines)

        # Parse AST
        tree: Optional[ast.AST] = None
        syntax_error: Optional[str] = None
        try:
            tree = ast.parse(source, filename=filename, mode="exec")
        except SyntaxError as exc:
            syntax_error = f"SyntaxError at line {exc.lineno}: {exc.msg}"
            logger.debug("[AST] Parse error in %s: %s", filename, syntax_error)
        except Exception as exc:
            syntax_error = str(exc)

        # Token count
        token_count = self._count_tokens(source)

        result = ParseResult(
            success=tree is not None,
            tree=tree,
            source=source,
            line_count=line_count,
            token_count=token_count,
            syntax_error=syntax_error,
        )

        if tree is not None:
            self._extract_metadata(tree, result)

        return result

    def parse_file(self, path: Path) -> ParseResult:
        """Parse a file from disk. Reads bytes and detects encoding."""
        if not path.exists():
            return ParseResult(
                success=False, tree=None, source="",
                line_count=0, token_count=0,
                syntax_error=f"File not found: {path}",
            )
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ParseResult(
                success=False, tree=None, source="",
                line_count=0, token_count=0,
                syntax_error=f"Cannot read file: {exc}",
            )
        result = self.parse(source, filename=str(path))
        result.metadata["filepath"] = str(path)
        return result

    # ── Metadata extraction ────────────────────────────────────────────────────

    def _extract_metadata(self, tree: ast.AST, result: ParseResult) -> None:
        visitor = _MetadataVisitor()
        try:
            visitor.visit(tree)
        except Exception as exc:
            logger.debug("[AST] Metadata extraction error: %s", exc)
            return

        result.imports       = visitor.imports
        result.function_defs = visitor.function_defs
        result.class_defs    = visitor.class_defs
        result.calls         = visitor.calls
        result.strings       = visitor.strings[:500]  # cap to avoid memory issues
        result.attributes    = visitor.attributes
        result.global_names  = visitor.global_names
        result.has_main      = visitor.has_main
        result.metadata.update({
            "has_try_except":    visitor.has_try_except,
            "has_decorators":    visitor.has_decorators,
            "assign_count":      visitor.assign_count,
            "loop_count":        visitor.loop_count,
            "nested_depth":      visitor.max_depth,
        })

    @staticmethod
    def _count_tokens(source: str) -> int:
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
            return len(tokens)
        except Exception:
            return 0

    def extract_string_literals(self, tree: ast.AST) -> List[str]:
        """Return all string constants from the AST."""
        strings: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
        return strings

    def get_call_names(self, tree: ast.AST) -> List[Tuple[str, int]]:
        """Return (qualified_call_name, line_number) for every Call node."""
        calls: List[Tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name:
                    calls.append((name, getattr(node, "lineno", 0)))
        return calls

    def get_import_names(self, tree: ast.AST) -> List[Tuple[str, int]]:
        """Return (module_name, line_number) for every Import/ImportFrom."""
        imports: List[Tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((alias.name, getattr(node, "lineno", 0)))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append((f"{mod}.{alias.name}" if mod else alias.name,
                                    getattr(node, "lineno", 0)))
        return imports


# ── Internal AST visitor ───────────────────────────────────────────────────────

class _MetadataVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports:       List[str] = []
        self.function_defs: List[str] = []
        self.class_defs:    List[str] = []
        self.calls:         List[str] = []
        self.strings:       List[str] = []
        self.attributes:    List[str] = []
        self.global_names:  Set[str]  = set()
        self.has_main         = False
        self.has_try_except   = False
        self.has_decorators   = False
        self.assign_count     = 0
        self.loop_count       = 0
        self._depth           = 0
        self.max_depth        = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            full = f"{mod}.{alias.name}" if mod else alias.name
            self.imports.append(full)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_defs.append(node.name)
        if node.decorator_list:
            self.has_decorators = True
        self._depth += 1
        self.max_depth = max(self.max_depth, self._depth)
        self.generic_visit(node)
        self._depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_defs.append(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_defs.append(node.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            self.calls.append(name)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and len(node.value) > 3:
            self.strings.append(node.value)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        full = _attr_name(node)
        if full:
            self.attributes.append(full)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.assign_count += 1
        for t in node.targets:
            if isinstance(t, ast.Name):
                self.global_names.add(t.id)
        self.generic_visit(node)

    def visit_For(self, node) -> None:
        self.loop_count += 1
        self.generic_visit(node)

    def visit_While(self, node) -> None:
        self.loop_count += 1
        self.generic_visit(node)

    def visit_Try(self, node) -> None:
        self.has_try_except = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        # Detect `if __name__ == "__main__":`
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and any(
                    isinstance(c, ast.Constant) and c.value == "__main__"
                    for c in test.comparators
                )):
            self.has_main = True
        self.generic_visit(node)


def _call_name(node: ast.expr) -> str:
    """Extract a dotted call name from a Call's func node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _attr_name(node: ast.Attribute) -> str:
    """Extract dotted attribute path."""
    if isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    if isinstance(node.value, ast.Attribute):
        parent = _attr_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return node.attr
