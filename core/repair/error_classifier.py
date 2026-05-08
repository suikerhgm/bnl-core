"""
core/repair/error_classifier.py
================================
ERROR_TAXONOMY_SYSTEM — classifies crash stderr into actionable categories.

Categories
----------
    import_error      — ImportError / cannot import name (symbol exists but not importable)
    dependency_error  — ModuleNotFoundError / No module named (package missing)
    syntax_error      — SyntaxError / IndentationError / unexpected EOF
    port_error        — Address already in use / WinError 10048
    runtime_error     — RuntimeError / AttributeError / TypeError / ValueError …
    unknown_error     — anything else
"""
from __future__ import annotations

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SAFE_PKG = re.compile(r"^[a-zA-Z0-9_\-]+$")

# ── Pattern registry (checked in order; first match wins) ─────────────────────

_PATTERNS: list[tuple[str, list[str]]] = [
    # dependency_error checked BEFORE import_error — "No module named" is more specific
    ("dependency_error", [
        r"ModuleNotFoundError:\s*No module named",
        r"No module named\s+['\"]",
        r"No matching distribution found for",
        r"Could not find a version that satisfies",
        r"pip.*install.*failed",
    ]),
    # import_error — module found but symbol missing
    ("import_error", [
        r"ImportError:\s*cannot import name",
        r"cannot import name\s+['\"]",
        r"ImportError:",
    ]),
    # syntax_error
    ("syntax_error", [
        r"SyntaxError:",
        r"IndentationError:",
        r"TabError:",
        r"unexpected EOF while parsing",
        r"unexpected EOF",
        r"invalid syntax",
        r"unexpected indent",
    ]),
    # port_error
    ("port_error", [
        r"[Aa]ddress already in use",
        r"WinError 10048",
        r"\[Errno 98\]",
        r"\[Errno 10048\]",
        r"Only one usage of each socket address",
        r"port.*already.*in use",
    ]),
    # runtime_error
    ("runtime_error", [
        r"RuntimeError:",
        r"AttributeError:",
        r"TypeError:",
        r"ValueError:",
        r"KeyError:",
        r"NameError:",
        r"RecursionError:",
        r"MemoryError:",
        r"OSError:",
        r"FileNotFoundError:",
        r"PermissionError:",
    ]),
]

# Pre-compile once at import time
_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (cat, [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats])
    for cat, pats in _PATTERNS
]


def classify_error(stderr: str) -> str:
    """
    Classify crash output and return the error category.

    Returns one of:
        import_error | dependency_error | syntax_error |
        port_error   | runtime_error   | unknown_error
    """
    if not stderr:
        return "unknown_error"

    for category, compiled_pats in _COMPILED:
        for pat in compiled_pats:
            if pat.search(stderr):
                logger.info("[CLASSIFIER] detected category=%s", category)
                return category

    logger.info("[CLASSIFIER] category=unknown_error (no pattern matched)")
    return "unknown_error"


def extract_package_name(stderr: str) -> Optional[str]:
    """
    For dependency_error: extract the top-level package name to pip-install.
    Returns None if extraction fails or name looks unsafe.
    """
    m = re.search(
        r"(?:ModuleNotFoundError|ImportError):\s*No module named\s+['\"]?([a-zA-Z0-9_\.]+)['\"]?",
        stderr,
    )
    if m:
        pkg = m.group(1).split(".")[0]
        if _SAFE_PKG.match(pkg):
            return pkg
    return None


def extract_import_details(stderr: str) -> Tuple[Optional[str], Optional[str]]:
    """
    For import_error: return (module_path, symbol_name).

    Example: "cannot import name 'login' from 'routes'"
    → ('routes', 'login')
    """
    m = re.search(
        r"cannot import name\s+['\"]([^'\"]+)['\"]\s+from\s+['\"]([^'\"]+)['\"]",
        stderr,
    )
    if m:
        return m.group(2), m.group(1)   # module_path, symbol
    m = re.search(r"cannot import name\s+['\"]([^'\"]+)['\"]", stderr)
    if m:
        return None, m.group(1)
    return None, None
