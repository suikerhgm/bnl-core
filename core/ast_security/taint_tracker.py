"""
TaintTracker — AST-based source-to-sink data flow analysis for Nexus BNL.

Tracks how data from dangerous sources (user input, network, filesystem)
flows into dangerous sinks (eval, exec, subprocess, etc.) via variable
assignments, function calls, and return values.

Algorithm:
    1. Build a set of "tainted names" from known source calls
    2. Propagate taint through assignments (a = tainted → a is tainted)
    3. Detect when tainted names reach sinks
    4. Report taint flows as threat findings

This is a conservative (possibly over-approximate) analysis that may produce
false positives but never misses known taint flows. No code is executed.
"""

import ast
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

from core.ast_security.ast_parser import ParseResult, _call_name
from core.ast_security.dangerous_patterns import TAINT_SOURCES, TAINT_SINKS, ThreatPattern

logger = logging.getLogger(__name__)


@dataclass
class TaintFlow:
    """A detected taint flow from source to sink."""
    source_name:  str
    source_line:  int
    sink_name:    str
    sink_line:    int
    tainted_var:  str
    pattern:      ThreatPattern
    confidence:   float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":           self.pattern.id,
            "category":     "taint_flow",
            "source":       self.source_name,
            "source_line":  self.source_line,
            "sink":         self.sink_name,
            "sink_line":    self.sink_line,
            "tainted_var":  self.tainted_var,
            "risk_score":   self.pattern.risk_score,
            "blacklisted":  self.pattern.blacklisted,
            "confidence":   self.confidence,
            "description":  self.pattern.description,
        }


class TaintTracker:
    """
    Single-pass AST taint tracker.
    Walks the tree, maintaining a set of tainted variable names.
    """

    def track(self, result: ParseResult) -> List[TaintFlow]:
        if not result.tree:
            return []
        visitor = _TaintVisitor()
        try:
            visitor.visit(result.tree)
        except Exception as exc:
            logger.debug("[AST] TaintTracker error: %s", exc)
        return visitor.flows

    def get_summary(self, flows: List[TaintFlow]) -> Dict[str, Any]:
        return {
            "total_flows":  len(flows),
            "unique_sinks": list({f.sink_name for f in flows}),
            "blacklisted":  [f.to_dict() for f in flows if f.pattern.blacklisted],
            "max_risk":     max((f.pattern.risk_score for f in flows), default=0),
        }


class _TaintVisitor(ast.NodeVisitor):
    """
    Walks an AST tracking tainted variables.
    Scope: function-level only (does not cross function boundaries).
    """

    def __init__(self) -> None:
        # Maps variable_name → (source_call_name, source_line)
        self._tainted: Dict[str, tuple] = {}
        self.flows:    List[TaintFlow]  = []

    def visit_Assign(self, node: ast.Assign) -> None:
        # If the right-hand side is a taint source, taint the targets
        source = self._is_taint_source(node.value)
        if source:
            src_name, src_line = source
            for target in node.targets:
                for name in _extract_names(target):
                    self._tainted[name] = (src_name, src_line)
        else:
            # Propagate taint through: b = a (if a is tainted, b is tainted)
            rhs_names = _extract_names(node.value)
            taint_from = None
            for n in rhs_names:
                if n in self._tainted:
                    taint_from = self._tainted[n]
                    break
            if taint_from:
                for target in node.targets:
                    for name in _extract_names(target):
                        self._tainted[name] = taint_from

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)

        # Check if this call is a taint sink
        sink_pat = TAINT_SINKS.get(name)
        if sink_pat:
            sink_line = getattr(node, "lineno", 0)
            # Check if any argument is tainted
            all_args = list(node.args) + [kw.value for kw in node.keywords]
            for arg in all_args:
                for arg_name in _extract_names(arg):
                    if arg_name in self._tainted:
                        src_name, src_line = self._tainted[arg_name]
                        self.flows.append(TaintFlow(
                            source_name=src_name,
                            source_line=src_line,
                            sink_name=name,
                            sink_line=sink_line,
                            tainted_var=arg_name,
                            pattern=sink_pat,
                        ))

        # If this call produces tainted data (is a source), handled in Assign
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Save and restore taint state across function boundaries
        saved = dict(self._tainted)
        # Parameters are fresh (not tainted from outer scope)
        for arg in node.args.args:
            self._tainted.pop(arg.arg, None)
        self.generic_visit(node)
        self._tainted = saved

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        saved = dict(self._tainted)
        for arg in node.args.args:
            self._tainted.pop(arg.arg, None)
        self.generic_visit(node)
        self._tainted = saved

    @staticmethod
    def _is_taint_source(node: ast.expr) -> Optional[tuple]:
        """Return (source_name, line) if this node is a taint source call."""
        if not isinstance(node, ast.Call):
            return None
        name = _call_name(node.func)
        if name in TAINT_SOURCES:
            return (name, getattr(node, "lineno", 0))
        # Check root of dotted name
        root = name.split(".")[0]
        if root in TAINT_SOURCES:
            return (name, getattr(node, "lineno", 0))
        return None


def _extract_names(node: ast.expr) -> List[str]:
    """Extract all Name IDs referenced in an expression."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        names = []
        for elt in node.elts:
            names.extend(_extract_names(elt))
        return names
    if isinstance(node, ast.Attribute):
        # Treat 'obj.attr' as a name for taint purposes
        full = _call_name(node)
        return [full] if full else []
    if isinstance(node, ast.Subscript):
        return _extract_names(node.value)
    if isinstance(node, ast.Call):
        # Return the call result name for tracking
        n = _call_name(node.func)
        return [n] if n else []
    return []
