"""
core/runtime/entrypoint_detector.py
=====================================
Auto-detection of FastAPI / Flask entrypoints in generated project directories.

Uses only text analysis — never imports or executes project files.

Priority order:
  1. Any file named app.py / main.py / server.py / backend.py that contains
     an ASGI/WSGI app definition, found via recursive scan.
  2. Shorter paths (root-level) preferred over deeply nested ones.
  3. Known layout shortcuts: backend/ and src/ subdirs are tried first.

Skips: venv, .venv, env, node_modules, __pycache__, .git, snapshots.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

# File name candidates tried in this order within each directory
_ENTRY_NAMES = ("app.py", "main.py", "server.py", "backend.py")

# Directories pruned during os.walk
_SKIP_DIRS = frozenset({
    "venv", ".venv", "env", ".env",
    "node_modules", "__pycache__",
    ".git", ".pytest_cache",
    "snapshots", "tests", "test",
})

# Regex patterns that indicate an ASGI/WSGI app object is defined in the file
_APP_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bapp\s*=\s*FastAPI\s*\("),
    re.compile(r"\bapp\s*=\s*Flask\s*\("),
    re.compile(r"\bapplication\s*=\s*FastAPI\s*\("),
    re.compile(r"\bapplication\s*=\s*Flask\s*\("),
    # Generic: app = AnyCallable(  — lower confidence, used as fallback
    re.compile(r"\bapp\s*=\s*\w+\s*\("),
]

# High-confidence patterns (framework explicitly imported)
_FASTAPI_IMPORT = re.compile(r"from fastapi import|import fastapi")
_FLASK_IMPORT   = re.compile(r"from flask import|import flask")


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class EntrypointInfo:
    file_path:    Path   # absolute path to the entrypoint file
    module_path:  str    # dotted module path, e.g. "sistema_monitoreo.app"
    app_variable: str    # variable name of the ASGI app (almost always "app")
    framework:    str    # "fastapi" | "flask" | "unknown"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _detect_framework(content: str) -> str:
    if _FASTAPI_IMPORT.search(content):
        return "fastapi"
    if _FLASK_IMPORT.search(content):
        return "flask"
    if re.search(r"FastAPI\s*\(", content):
        return "fastapi"
    if re.search(r"Flask\s*\(", content):
        return "flask"
    return "unknown"


def _has_app_definition(content: str) -> bool:
    """Return True if the file appears to define an ASGI/WSGI application."""
    return any(p.search(content) for p in _APP_PATTERNS)


def _file_to_module(project_path: Path, file_path: Path) -> str:
    """
    Convert an absolute file path to a dotted uvicorn module string.

    Examples:
        <root>/app.py                  → "app"
        <root>/backend/app.py          → "backend.app"
        <root>/sistema_monitoreo/app.py → "sistema_monitoreo.app"
    """
    rel   = file_path.relative_to(project_path)
    parts = list(rel.parts)
    parts[-1] = parts[-1][:-3]          # strip ".py"
    return ".".join(parts)


def _score(rel_parts: tuple, name: str) -> tuple:
    """
    Sort key: prefer shallower paths and canonical names.

    Lower score → higher priority.
    """
    depth = len(rel_parts)
    name_prio = _ENTRY_NAMES.index(name) if name in _ENTRY_NAMES else 99
    return (depth, name_prio)


def _scan_candidates(project_path: Path) -> List[Path]:
    """
    Recursively find all files matching *_ENTRY_NAMES*, skipping noise dirs.

    Returns a list sorted by (depth, name_priority) — best candidates first.
    """
    hits: List[Path] = []

    for root, dirs, files in os.walk(str(project_path)):
        root_path = Path(root)
        # Prune in-place so os.walk won't descend into skipped dirs
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

        for name in _ENTRY_NAMES:
            if name in files:
                hits.append(root_path / name)

    hits.sort(key=lambda p: _score(p.relative_to(project_path).parts, p.name))
    return hits


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_entrypoint(project_path: Path) -> Optional[EntrypointInfo]:
    """
    Auto-detect the best ASGI/WSGI entrypoint in *project_path*.

    Logs [ENTRYPOINT] messages at each decision point.

    Returns:
        EntrypointInfo on success, None if no valid entrypoint is found.
    """
    project_path = Path(project_path).resolve()
    logger.info("[ENTRYPOINT] scanning %s", project_path.name)

    candidates = _scan_candidates(project_path)
    if not candidates:
        logger.warning("[ENTRYPOINT] no candidates found in %s", project_path.name)
        return None

    rel_paths = [str(c.relative_to(project_path).as_posix()) for c in candidates]
    logger.info("[ENTRYPOINT] candidates: %s", rel_paths)

    for candidate in candidates:
        rel = candidate.relative_to(project_path).as_posix()
        logger.info("[ENTRYPOINT] candidate found: %s", rel)

        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("[ENTRYPOINT] cannot read %s: %s", rel, exc)
            continue

        if not _has_app_definition(content):
            logger.debug("[ENTRYPOINT] %s — no app definition, skipping", rel)
            continue

        module    = _file_to_module(project_path, candidate)
        framework = _detect_framework(content)

        logger.info(
            "[ENTRYPOINT] selected: %s  module=%s  framework=%s",
            rel, module, framework,
        )
        return EntrypointInfo(
            file_path    = candidate,
            module_path  = module,
            app_variable = "app",
            framework    = framework,
        )

    logger.warning("[ENTRYPOINT] no valid entrypoint found in %s", project_path.name)
    return None
